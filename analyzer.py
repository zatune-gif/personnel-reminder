import os
import json
import logging
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
_model = genai.GenerativeModel("gemini-1.5-flash")


def _call(prompt: str) -> str:
    response = _model.generate_content(prompt)
    return response.text.strip()


def _parse_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}") + 1
    return json.loads(text[start:end])


def analyze_personality(responses: dict) -> dict:
    prompt = f"""あなたは組織心理の専門家です。以下のアンケート回答から、このメンバーの人間性・傾向を分析してください。

アンケート回答:
Q1 困ったとき自分から相談できる (1=ほぼできない, 5=積極的にできる): {responses.get('q1')}
Q2 プレッシャー下でのパフォーマンス (1=消耗する, 5=力が出る): {responses.get('q2')}
Q3 評価・承認の重要度 (1=あまり気にしない, 5=とても重要): {responses.get('q3')}
Q4 変化・新環境への適応 (1=苦手, 5=得意): {responses.get('q4')}
Q5 ストレス発散方法: {responses.get('q5')}

以下のJSON形式のみで返してください（説明文不要）:
{{
  "tends_to_hold_alone": true,
  "pressure_tolerance": "high",
  "recognition_need": "medium",
  "adaptability": "high",
  "summary": "このメンバーの特徴を2-3文で"
}}

tends_to_hold_alone: Q1が2以下ならtrue
pressure_tolerance: Q2が4-5="high", 3="medium", 1-2="low"
recognition_need: Q3が4-5="high", 3="medium", 1-2="low"
adaptability: Q4が4-5="high", 3="medium", 1-2="low"
"""

    try:
        return _parse_json(_call(prompt))
    except Exception as e:
        logger.error(f"analyze_personality failed: {e}")
        return {
            "tends_to_hold_alone": responses.get("q1", 3) <= 2,
            "pressure_tolerance": "medium",
            "recognition_need": "medium",
            "adaptability": "medium",
            "summary": "分析に失敗しました。",
        }


def analyze_status(member_name: str, personality: dict, recent_checks: list, current: dict) -> dict:
    history_lines = ""
    for c in reversed(recent_checks):
        history_lines += (
            f"- {c['survey_date']}: 業務量={c['q1_workload']}, "
            f"モチベ={c['q2_motivation']}, コミュ={c['q4_communication']}\n"
        )

    holds_alone = personality.get("tends_to_hold_alone", False)
    pressure_tolerance = personality.get("pressure_tolerance", "medium")

    threshold_note = ""
    if holds_alone:
        threshold_note += "・このメンバーは抱え込みがちな傾向があります。スコアが少し悪化しただけでも早めにアラートを上げてください。\n"
    if pressure_tolerance == "low":
        threshold_note += "・プレッシャー耐性が低いため、業務量が多い場合は特に注意が必要です。\n"

    prompt = f"""あなたは組織マネジメントの専門家です。メンバーの現在の状態を分析し、管理者がアクションを取るべきか判断してください。

【メンバー名】{member_name}

【人間性プロファイル】
- 抱え込み傾向: {'あり' if holds_alone else 'なし'}
- プレッシャー耐性: {pressure_tolerance}
- 承認欲求: {personality.get('recognition_need', '不明')}
- 適応力: {personality.get('adaptability', '不明')}
- 特徴: {personality.get('summary', '未分析')}

【判断補正】
{threshold_note if threshold_note else '特になし'}

【過去のスコア推移】
{history_lines if history_lines else '初回回答のため履歴なし'}

【今回の回答】
- 業務量: {current.get('q1')} / 5（1=少なすぎ, 3=適切, 5=多すぎ）
- モチベーション: {current.get('q2')} / 5（1=低い, 5=高い）
- 困っていること: {current.get('q3') or 'なし'}
- コミュニケーション: {current.get('q4')} / 5（1=取れていない, 5=十分）

以下のJSON形式のみで返してください（説明文不要）:
{{
  "alert_level": "clear",
  "reason": "アラートレベルの理由",
  "suggested_action": "管理者へのアクション提案（具体的に）",
  "tone_advice": "声のかけ方のアドバイス（この人の人間性を踏まえて。声かけ不要レベルの場合は空文字）"
}}

alert_levelは以下の6段階で返してください:
- clear  (0): 問題なし。通知不要。
- stable (1): 安定。通知不要。
- notice (2): 注視。管理者へ情報共有のみ。声かけ不要。
- check  (3): 確認推奨。今週中に機会を作って声をかける。
- act    (4): 対応要。早めに1on1を設定する。
- urgent (5): 緊急。即日対応が必要。

声かけ不要レベル（notice）でも reason と suggested_action は記入すること。
suggested_actionはnoticeの場合「次回チェック時に〜を確認する」など観察方針を書くこと。
"""

    try:
        return _parse_json(_call(prompt))
    except Exception as e:
        logger.error(f"analyze_status failed: {e}")
        return {
            "alert_level": "clear",
            "reason": "分析に失敗しました。",
            "suggested_action": "手動で状態を確認してください。",
            "tone_advice": "",
        }


LEVEL_META = {
    #        label              声かけ要否
    "clear":  ("",                        False),
    "stable": ("",                        False),
    "notice": ("👀 【注視】",              False),
    "check":  ("📅 【今週中に声かけを】", True),
    "act":    ("⚠️ 【早めに1on1を】",    True),
    "urgent": ("🚨 【即日対応】",         True),
}

LEVEL_ORDER = ["clear", "stable", "notice", "check", "act", "urgent"]


def needs_notification(alert_level: str) -> bool:
    """notice以上は管理者に通知する。"""
    return LEVEL_ORDER.index(alert_level) >= LEVEL_ORDER.index("notice") if alert_level in LEVEL_ORDER else False


def build_manager_message(member_name: str, analysis: dict) -> str:
    level = analysis.get("alert_level", "clear")
    label, needs_action = LEVEL_META.get(level, ("", False))

    lines = [
        f"{label} *{member_name}さん* の状態レポート",
        "",
        f"*状況*: {analysis.get('reason', '')}",
        f"*対応方針*: {analysis.get('suggested_action', '')}",
    ]
    if needs_action and analysis.get("tone_advice"):
        lines.append(f"*声のかけ方*: {analysis.get('tone_advice')}")

    return "\n".join(lines)
