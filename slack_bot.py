import os
import threading
import logging
from datetime import date

from slack_bolt import App
from dotenv import load_dotenv

import database as db
import analyzer

load_dotenv()
logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])
ADMIN_SLACK_ID = os.environ["ADMIN_SLACK_ID"]


# ---------------------------------------------------------------------------
# Modal definitions
# ---------------------------------------------------------------------------

def _scale_options():
    return [
        {"text": {"type": "plain_text", "text": str(i)}, "value": str(i)}
        for i in range(1, 6)
    ]


def annual_survey_modal():
    """年次サーベイ（人間性把握用・タイトルは曖昧）"""
    opts = _scale_options()
    return {
        "type": "modal",
        "callback_id": "personality_survey",
        "title": {"type": "plain_text", "text": "年次サーベイ"},
        "submit": {"type": "plain_text", "text": "送信"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "年に1回のサーベイです。正直にお答えください。\n回答内容は組織運営の参考にのみ使用します。"},
            },
            _scale_input("q1", "Q1: 困ったとき、誰かに相談することができますか？\n（1=ほぼできない　5=積極的にできる）", opts),
            _scale_input("q2", "Q2: 締め切りや責任が重なると、どちらかというと？\n（1=消耗する　5=力が出る）", opts),
            _scale_input("q3", "Q3: 自分の取り組みや成果を認めてもらうことはどれくらい大切ですか？\n（1=あまり気にしない　5=とても大切）", opts),
            _scale_input("q4", "Q4: 環境や仕事内容が変わることへの適応は？\n（1=苦手　5=得意）", opts),
            {
                "type": "input",
                "block_id": "q5",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "answer",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "例: 運動する、音楽を聴く、友人と話す"},
                },
                "label": {"type": "plain_text", "text": "Q5: 気持ちが重いと感じたとき、どう切り替えますか？"},
            },
        ],
    }


def monthly_checkin_modal():
    """月次チェックイン（状態把握用・タイトルは曖昧）"""
    opts = _scale_options()
    return {
        "type": "modal",
        "callback_id": "status_survey",
        "title": {"type": "plain_text", "text": "月次チェックイン"},
        "submit": {"type": "plain_text", "text": "送信"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "今月の状況を教えてください。数分で完了します。\n回答は担当者のみ参照します。"},
            },
            _scale_input("q1", "Q1: 最近の仕事量はどう感じますか？\n（1=少なすぎ　3=ちょうどよい　5=多すぎ）", opts),
            _scale_input("q2", "Q2: 仕事や活動への前向きさはどうですか？\n（1=低い　5=高い）", opts),
            {
                "type": "input",
                "block_id": "q3",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "answer",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "なければ「なし」と入力"},
                },
                "label": {"type": "plain_text", "text": "Q3: 最近困っていること・行き詰まっていることはありますか？"},
            },
            _scale_input("q4", "Q4: 周囲とのコミュニケーションは取れていますか？\n（1=取れていない　5=十分取れている）", opts),
        ],
    }


def _scale_input(block_id: str, label: str, opts: list) -> dict:
    return {
        "type": "input",
        "block_id": block_id,
        "element": {
            "type": "static_select",
            "action_id": "answer",
            "placeholder": {"type": "plain_text", "text": "選択"},
            "options": opts,
        },
        "label": {"type": "plain_text", "text": label},
    }


# ---------------------------------------------------------------------------
# Survey dispatch helpers
# ---------------------------------------------------------------------------

def send_status_survey(slack_user_id: str):
    ch = _dm_channel(slack_user_id)
    app.client.chat_postMessage(
        channel=ch,
        text="月次チェックインをお願いします。",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "今月の *チェックイン* の時期です。数分で完了します。"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "チェックインする"},
                        "action_id": "open_status_survey",
                        "style": "primary",
                    }
                ],
            },
        ],
    )


def send_annual_survey(slack_user_id: str):
    ch = _dm_channel(slack_user_id)
    app.client.chat_postMessage(
        channel=ch,
        text="年次サーベイをお願いします。",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "年に1回の *サーベイ* の時期です。\nご協力をお願いします。"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "サーベイに答える"},
                        "action_id": "open_annual_survey",
                        "style": "primary",
                    }
                ],
            },
        ],
    )


def _dm_channel(slack_user_id: str) -> str:
    result = app.client.conversations_open(users=slack_user_id)
    return result["channel"]["id"]


def _notify_manager(member_id: int, message: str):
    group = db.get_group_for_member(member_id)
    if not group:
        logger.warning(f"No group found for member_id={member_id}, falling back to admin")
        target = ADMIN_SLACK_ID
    else:
        target = group["manager_slack_user_id"]
    ch = _dm_channel(target)
    app.client.chat_postMessage(channel=ch, text=message, mrkdwn=True)


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

@app.action("open_status_survey")
def handle_open_status(ack, body, client):
    ack()
    slack_user_id = body["user"]["id"]
    member = db.get_member_by_slack_id(slack_user_id)
    if member:
        year_month = str(date.today())[:7]
        if db.has_status_check_this_month(member["id"], year_month):
            ch = _dm_channel(slack_user_id)
            client.chat_postMessage(
                channel=ch,
                text="今月のチェックインはすでに回答済みです。次回は来月お答えください。",
            )
            return
    client.views_open(trigger_id=body["trigger_id"], view=monthly_checkin_modal())


@app.action("open_annual_survey")
def handle_open_annual(ack, body, client):
    ack()
    slack_user_id = body["user"]["id"]
    # 年次サーベイは人間性プロファイル未完了のメンバーのみ受付
    member = db.get_member_by_slack_id(slack_user_id)
    if member and db.get_personality_profile(member["id"]):
        # 既に完了済みの場合もモーダルを開く（再回答可）
        pass
    client.views_open(trigger_id=body["trigger_id"], view=annual_survey_modal())


# ---------------------------------------------------------------------------
# Modal submission handlers
# ---------------------------------------------------------------------------

@app.view("personality_survey")
def handle_annual_submission(ack, body, view):
    ack()
    slack_user_id = body["user"]["id"]
    threading.Thread(target=_process_annual, args=(slack_user_id, view), daemon=True).start()


def _process_annual(slack_user_id: str, view: dict):
    member = db.get_member_by_slack_id(slack_user_id)
    if not member:
        logger.warning(f"Unknown Slack user: {slack_user_id}")
        return

    values = view["state"]["values"]
    responses = {
        "q1": int(values["q1"]["answer"]["selected_option"]["value"]),
        "q2": int(values["q2"]["answer"]["selected_option"]["value"]),
        "q3": int(values["q3"]["answer"]["selected_option"]["value"]),
        "q4": int(values["q4"]["answer"]["selected_option"]["value"]),
        "q5": values["q5"]["answer"]["value"],
    }

    profile_labels = analyzer.analyze_personality(responses)
    db.save_personality_profile(member["id"], responses, profile_labels)
    logger.info(f"Annual survey saved for {member['name']}")


@app.view("status_survey")
def handle_status_submission(ack, body, view):
    ack()
    slack_user_id = body["user"]["id"]
    threading.Thread(target=_process_status, args=(slack_user_id, view), daemon=True).start()


def _process_status(slack_user_id: str, view: dict):
    member = db.get_member_by_slack_id(slack_user_id)
    if not member:
        logger.warning(f"Unknown Slack user: {slack_user_id}")
        return

    # 今月すでに回答済みならブロック
    year_month = str(date.today())[:7]
    if db.has_status_check_this_month(member["id"], year_month):
        ch = _dm_channel(slack_user_id)
        app.client.chat_postMessage(
            channel=ch,
            text="今月のチェックインはすでに回答済みです。次回は来月お答えください。",
        )
        return

    # 年次サーベイ未完了なら月次チェックインをブロック
    if not db.get_personality_profile(member["id"]):
        ch = _dm_channel(slack_user_id)
        app.client.chat_postMessage(
            channel=ch,
            text="先に年次サーベイを完了してください。月次チェックインはその後ご利用いただけます。",
        )
        return

    values = view["state"]["values"]
    responses = {
        "q1": int(values["q1"]["answer"]["selected_option"]["value"]),
        "q2": int(values["q2"]["answer"]["selected_option"]["value"]),
        "q3": values["q3"]["answer"]["value"],
        "q4": int(values["q4"]["answer"]["selected_option"]["value"]),
    }

    personality_row = db.get_personality_profile(member["id"])
    personality = personality_row["profile_labels"] if personality_row else {}
    recent = db.get_recent_status_checks(member["id"], limit=3)

    analysis = analyzer.analyze_status(
        member_name=member["name"],
        personality=personality,
        recent_checks=recent,
        current=responses,
    )

    db.save_status_check(member["id"], str(date.today()), responses, analysis)
    logger.info(f"Status check saved for {member['name']}: alert_level={analysis.get('alert_level')}")

    if analyzer.needs_notification(analysis.get("alert_level", "clear")):
        message = analyzer.build_manager_message(member["name"], analysis)
        db.save_reminder(member["id"], analysis.get("reason", ""), message)
        try:
            _notify_manager(member["id"], message)
            logger.info(f"Manager notified about {member['name']} (level={analysis.get('alert_level')})")
        except Exception as e:
            logger.error(f"Failed to notify manager: {e}")


# ---------------------------------------------------------------------------
# Manager / Admin commands
# ---------------------------------------------------------------------------

def _is_admin(user_id: str) -> bool:
    return user_id == ADMIN_SLACK_ID


def _is_manager(user_id: str) -> bool:
    return _is_admin(user_id) or db.get_group_by_manager(user_id) is not None


@app.message("グループ作成")
def handle_create_group(message, say):
    if not _is_admin(message["user"]):
        return
    # format: グループ作成 グループ名 <@管理者SlackID>
    parts = message["text"].split()
    if len(parts) < 3:
        say("使い方: `グループ作成 グループ名 <@管理者SlackID>`")
        return
    name = parts[1]
    manager_id = parts[2].strip("<@>").split("|")[0]
    db.add_group(name, manager_id)
    say(
        f"グループ *{name}* を作成しました。担当管理者: <@{manager_id}>\n"
        f"管理者自身もアンケート対象にする場合は `メンバー追加` で <@{manager_id}> をメンバーに追加してください。"
        f"（状態レポートは管理者自身に届きます）"
    )


@app.message("メンバー追加")
def handle_add_member(message, say):
    if not _is_manager(message["user"]):
        return

    parts = message["text"].split()

    if _is_admin(message["user"]):
        # ADMIN format: メンバー追加 名前 <@SlackID> グループ名 役割（任意）
        if len(parts) < 4:
            say("使い方（管理者）: `メンバー追加 名前 <@SlackID> グループ名 役割（任意）`")
            return
        name = parts[1]
        slack_id = parts[2].strip("<@>").split("|")[0]
        group_name = parts[3]
        role = parts[4] if len(parts) > 4 else ""
        groups = db.get_all_groups()
        group = next((g for g in groups if g["name"] == group_name), None)
        if group is None:
            say(f"グループ「{group_name}」が見つかりません。`グループ一覧` で確認してください。")
            return
    else:
        # Manager format: メンバー追加 名前 <@SlackID> 役割（任意）
        if len(parts) < 3:
            say("使い方: `メンバー追加 名前 <@SlackID> 役割（任意）`")
            return
        group = db.get_group_by_manager(message["user"])
        if group is None:
            say("あなたはどのグループの管理者でもありません。")
            return
        name = parts[1]
        slack_id = parts[2].strip("<@>").split("|")[0]
        role = parts[3] if len(parts) > 3 else ""

    db.add_member(name, slack_id, group["id"], role)
    say(f"*{name}* さんをグループ「{group['name']}」に登録しました。（役割: {role or '未設定'}）")


@app.message("メンバー一覧")
def handle_list_members(message, say):
    if not _is_manager(message["user"]):
        return
    group = db.get_group_by_manager(message["user"])
    if group is None:
        say("担当グループが見つかりません。")
        return
    members = db.get_members_by_group(group["id"])
    if not members:
        say(f"グループ「{group['name']}」にメンバーはいません。")
        return
    lines = [f"*グループ「{group['name']}」のメンバー一覧*"]
    for m in members:
        lines.append(f"- {m['name']}（{m['role'] or '役割未設定'}）<@{m['slack_user_id']}>")
    say("\n".join(lines))


@app.message("チェックイン送信")
def handle_send_status(message, say):
    if not _is_manager(message["user"]):
        return
    group = db.get_group_by_manager(message["user"])
    if group is None:
        say("担当グループが見つかりません。")
        return
    members = db.get_members_by_group(group["id"])
    sent = 0
    for m in members:
        try:
            send_status_survey(m["slack_user_id"])
            db.record_survey_dispatch(m["id"], "status")
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send checkin to {m['name']}: {e}")
    say(f"{sent} 名に月次チェックインを送りました。")


@app.message("年次サーベイ送信")
def handle_send_annual(message, say):
    if not _is_manager(message["user"]):
        return
    group = db.get_group_by_manager(message["user"])
    if group is None:
        say("担当グループが見つかりません。")
        return
    members = db.get_members_by_group(group["id"])
    sent = 0
    for m in members:
        try:
            send_annual_survey(m["slack_user_id"])
            db.record_survey_dispatch(m["id"], "personality")
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send annual survey to {m['name']}: {e}")
    say(f"{sent} 名に年次サーベイを送りました。")


@app.message("グループ変更")
def handle_transfer_member(message, say):
    if not _is_manager(message["user"]):
        return
    # format: グループ変更 <@SlackID> 新グループ名
    parts = message["text"].split()
    if len(parts) < 3:
        say("使い方: `グループ変更 <@SlackID> 新グループ名`")
        return

    slack_id = parts[1].strip("<@>").split("|")[0]
    new_group_name = parts[2]

    groups = db.get_all_groups()
    new_group = next((g for g in groups if g["name"] == new_group_name), None)
    if new_group is None:
        say(f"グループ「{new_group_name}」が見つかりません。`グループ一覧` で確認してください。")
        return

    # 非ADMIN管理者は自分のグループのメンバーのみ移動可
    if not _is_admin(message["user"]):
        manager_group = db.get_group_by_manager(message["user"])
        member = db.get_member_by_slack_id(slack_id)
        if member is None:
            say("メンバーが見つかりません。")
            return
        if member["group_id"] != manager_group["id"]:
            say("他のグループのメンバーは操作できません。")
            return

    success = db.transfer_member_group(slack_id, new_group["id"])
    if success:
        member = db.get_member_by_slack_id(slack_id)
        say(f"*{member['name']}* さんをグループ「{new_group_name}」に移動しました。")
    else:
        say("メンバーが見つかりません。")


@app.message("グループ一覧")
def handle_list_groups(message, say):
    if not _is_admin(message["user"]):
        return
    groups = db.get_all_groups()
    if not groups:
        say("登録済みグループはありません。")
        return
    lines = ["*グループ一覧*"]
    for g in groups:
        lines.append(f"- {g['name']}　担当: <@{g['manager_slack_user_id']}>")
    say("\n".join(lines))
