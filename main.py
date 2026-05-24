import os
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import database as db
from slack_bot import app
from scheduler import start_scheduler
from slack_bolt.adapter.socket_mode import SocketModeHandler

if __name__ == "__main__":
    db.init_db()
    scheduler = start_scheduler(app)

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    logging.getLogger(__name__).info("Bot started")
    handler.start()
