# =============================================================================
# run_all.py  —  Supervisor Script
# Launches all OmniAgent services in a single process using threads
# Used both locally and inside Docker
# =============================================================================

import os
import sys
import time
import logging
import threading
import signal

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.supervisor")

# Track threads for graceful shutdown
threads = []
shutdown_event = threading.Event()


def run_discord():
    """Start the Discord adapter."""
    try:
        from adapters.discord_adapter import bot
        import asyncio

        token = os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            logger.warning("DISCORD_BOT_TOKEN not set, skipping Discord adapter")
            return

        logger.info("Starting Discord adapter...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot.start(token))
    except Exception as e:
        logger.error("Discord adapter crashed: %s", e)


def run_slack():
    """Start the Slack adapter."""
    try:
        token = os.environ.get("SLACK_BOT_TOKEN")
        app_token = os.environ.get("SLACK_APP_TOKEN")
        if not token or not app_token:
            logger.warning("Slack tokens not set, skipping Slack adapter")
            return

        logger.info("Starting Slack adapter...")
        from adapters.slack_adapter import start_slack_bot
        start_slack_bot()
    except Exception as e:
        logger.error("Slack adapter crashed: %s", e)


def run_email():
    """Start the Email adapter."""
    try:
        gmail = os.environ.get("GMAIL_ADDRESS")
        gmail_pw = os.environ.get("GMAIL_APP_PASSWORD")
        if not gmail or not gmail_pw:
            logger.warning("Gmail credentials not set, skipping Email adapter")
            return

        logger.info("Starting Email adapter...")
        from adapters.email_adapter import poll_inbox
        poll_inbox()
    except Exception as e:
        logger.error("Email adapter crashed: %s", e)


def run_api():
    """Start the FastAPI server."""
    try:
        logger.info("Starting FastAPI server on port 8000...")
        import uvicorn
        uvicorn.run("api.main:app", host="0.0.0.0", port=8000, log_level="info")
    except Exception as e:
        logger.error("API server crashed: %s", e)


def run_scheduler():
    """Start the APScheduler."""
    try:
        logger.info("Starting Scheduler...")
        from workflows.scheduler import main as scheduler_main
        scheduler_main()
    except Exception as e:
        logger.error("Scheduler crashed: %s", e)


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    logger.info("Shutdown signal received. Stopping all services...")
    shutdown_event.set()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("=" * 60)
    logger.info("       OmniAgent Supervisor — Starting All Services")
    logger.info("=" * 60)

    services = [
        ("Discord", run_discord),
        ("Slack", run_slack),
        ("Email", run_email),
        ("API Server", run_api),
        ("Scheduler", run_scheduler),
    ]

    for name, func in services:
        t = threading.Thread(target=func, name=name, daemon=True)
        t.start()
        threads.append(t)
        logger.info("Launched: %s", name)
        time.sleep(1)  # Stagger startup to avoid resource contention

    logger.info("=" * 60)
    logger.info("       All services launched! Ctrl+C to stop.")
    logger.info("=" * 60)

    # Keep main thread alive
    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
