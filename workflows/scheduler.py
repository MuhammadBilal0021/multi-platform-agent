# =============================================================================
# workflows/scheduler.py  —  APScheduler-based Workflow Scheduler
# Runs daily_digest and news_tweet on automated schedules
# =============================================================================

import os
import sys
import logging

from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.scheduler")

from workflows.daily_digest import run_daily_digest
def run_news_tweet():
    if os.environ.get("ENABLE_TWITTER_WORKFLOW", "").lower() == "true":
        from workflows.news_tweet import run_news_tweet as run
        return run()


def main():
    scheduler = BlockingScheduler(timezone="Asia/Karachi")

    # -------------------------------------------------------------------------
    # SCHEDULE 1: Daily Digest — every day at 9:00 AM PKT
    # -------------------------------------------------------------------------
    scheduler.add_job(
        run_daily_digest,
        CronTrigger(hour=9, minute=0, timezone="Asia/Karachi"),
        id="daily_digest",
        name="Daily AI News Digest",
        misfire_grace_time=3600,
    )
    logger.info("Scheduled: Daily Digest at 09:00 AM PKT")

    # -------------------------------------------------------------------------
    # SCHEDULE 2: News Tweet — every day at 12:00 PM and 6:00 PM PKT
    # (will only work once deployed to cloud due to Twitter API block)
    # -------------------------------------------------------------------------
    scheduler.add_job(
        run_news_tweet,
        CronTrigger(hour="12,18", minute=0, timezone="Asia/Karachi"),
        id="news_tweet",
        name="AI News Tweet",
        misfire_grace_time=3600,
    )
    logger.info("Scheduled: News Tweet at 12:00 PM & 6:00 PM PKT")

    # -------------------------------------------------------------------------
    # START
    # -------------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("OmniAgent Scheduler STARTED")
    logger.info("Ctrl+C to stop")
    logger.info("=" * 60)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
