import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import database as db
import analyzer

logger = logging.getLogger(__name__)


def _send_status_surveys(app):
    from slack_bot import send_status_survey
    members = db.get_all_members()
    for m in members:
        # 2回連続未回答チェック（送信前に判定）
        consecutive = db.get_consecutive_no_responses(m["id"], "status")
        if consecutive >= 2:
            _notify_no_response(app, m)

        try:
            send_status_survey(m["slack_user_id"])
            db.record_survey_dispatch(m["id"], "status")
        except Exception as e:
            logger.error(f"Failed to send checkin to {m['name']}: {e}")

    logger.info(f"Monthly checkins sent to {len(members)} members")


def _send_annual_surveys(app):
    from slack_bot import send_annual_survey
    members = db.get_all_members()
    for m in members:
        try:
            send_annual_survey(m["slack_user_id"])
            db.record_survey_dispatch(m["id"], "personality")
        except Exception as e:
            logger.error(f"Failed to send annual survey to {m['name']}: {e}")

    logger.info(f"Annual surveys sent to {len(members)} members")


def _notify_no_response(app, member: dict):
    group = db.get_group_for_member(member["id"])
    if not group:
        logger.warning(f"No group for member {member['name']}, skipping no-response notification")
        return

    message = (
        f"👀 【注視】 *{member['name']}さん* の状態レポート\n\n"
        f"*状況*: 月次チェックインへの回答が2回連続でありません。\n"
        f"*対応方針*: 声かけは不要ですが、次回回答があるか注目してください。"
    )
    db.save_reminder(member["id"], "2回連続未回答", message)

    try:
        result = app.client.conversations_open(users=group["manager_slack_user_id"])
        ch = result["channel"]["id"]
        app.client.chat_postMessage(channel=ch, text=message, mrkdwn=True)
        logger.info(f"No-response notice sent for {member['name']}")
    except Exception as e:
        logger.error(f"Failed to send no-response notice: {e}")


def start_scheduler(app) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")

    # 月次チェックイン: 毎月1日・15日 09:00
    scheduler.add_job(
        lambda: _send_status_surveys(app),
        CronTrigger(day="1,15", hour=9, minute=0, timezone="Asia/Tokyo"),
        id="status_survey",
    )

    # 年次サーベイ: 毎年4月1日 09:00
    scheduler.add_job(
        lambda: _send_annual_surveys(app),
        CronTrigger(month=4, day=1, hour=9, minute=0, timezone="Asia/Tokyo"),
        id="annual_survey",
    )

    scheduler.start()
    logger.info("Scheduler started")
    return scheduler
