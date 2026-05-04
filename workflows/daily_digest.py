# =============================================================================
# workflows/daily_digest.py  —  Autonomous Daily News Digest
# Searches the web for AI/tech news, asks the brain to summarize,
# and distributes the digest across all platforms
# =============================================================================

import os
import sys
import logging
from datetime import datetime

from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import run_brain
from core.state import AgentState
from core.tools import web_search

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.digest")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")


# =============================================================================
# STEP 1: GATHER NEWS
# =============================================================================
def gather_news() -> str:
    """Use Tavily web search to find the latest AI/tech news."""
    logger.info("Gathering latest AI & tech news...")
    topics = [
        "latest AI news today",
        "new technology breakthroughs 2026",
    ]
    all_results = []
    for topic in topics:
        try:
            results = web_search.invoke({"query": topic})
            all_results.append(f"### {topic}\n{results}")
        except Exception as e:
            logger.error("Search failed for '%s': %s", topic, e)
    
    combined = "\n\n".join(all_results)
    logger.info("Gathered %d chars of raw news data", len(combined))
    return combined


# =============================================================================
# STEP 2: ASK THE BRAIN TO WRITE THE DIGEST
# =============================================================================
def generate_digest(raw_news: str) -> str:
    """Send the raw news to the brain and ask it to write a clean digest."""
    prompt = (
        "You are a tech newsletter writer. Based on the following raw news data, "
        "write a clean, engaging daily digest with these sections:\n"
        "1. 🔥 Top Headlines (3-5 bullet points)\n"
        "2. 🤖 AI & Machine Learning Updates\n"
        "3. 💡 Interesting Reads\n\n"
        "Keep it concise but informative. Use emojis for visual appeal.\n\n"
        f"--- RAW NEWS DATA ---\n{raw_news[:4000]}"
    )

    state: AgentState = {
        "channel": "workflow",
        "user_id": "system",
        "username": "DailyDigest",
        "message": prompt,
        "history": [],
        "tool_results": [],
        "response": "",
        "metadata": {"workflow": "daily_digest"},
    }
    result = run_brain(state)
    digest = result.get("response", "Could not generate digest.")
    logger.info("Generated digest: %d chars", len(digest))
    return digest


# =============================================================================
# STEP 3: DISTRIBUTE TO ALL PLATFORMS
# =============================================================================
def distribute_digest(digest: str):
    """Send the digest to Discord, Slack, and Email."""
    today = datetime.now().strftime("%B %d, %Y")
    header = f"📰 **OmniAgent Daily Digest — {today}**\n\n"
    full_digest = header + digest

    # --- EMAIL ---
    try:
        from adapters.email_adapter import send_email
        if GMAIL_ADDRESS:
            result = send_email(
                to=GMAIL_ADDRESS,
                subject=f"🤖 OmniAgent Daily Digest — {today}",
                body=full_digest,
            )
            logger.info("Email digest: %s", result["status"])
    except Exception as e:
        logger.error("Failed to send email digest: %s", e)

    # --- DISCORD (via webhook) ---
    try:
        discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")
        if discord_webhook:
            import requests
            # Discord webhooks have a 2000 char limit
            truncated = full_digest[:1900]
            requests.post(discord_webhook, json={"content": truncated}, timeout=10)
            logger.info("Discord digest: sent via webhook")
        else:
            logger.info("Discord digest: skipped (no DISCORD_WEBHOOK_URL set)")
    except Exception as e:
        logger.error("Failed to send Discord digest: %s", e)

    # --- SLACK (via webhook) ---
    try:
        slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if slack_webhook:
            import requests
            requests.post(slack_webhook, json={"text": full_digest[:3000]}, timeout=10)
            logger.info("Slack digest: sent via webhook")
        else:
            logger.info("Slack digest: skipped (no SLACK_WEBHOOK_URL set)")
    except Exception as e:
        logger.error("Failed to send Slack digest: %s", e)

    logger.info("Digest distribution complete!")


# =============================================================================
# MAIN — RUN THE FULL PIPELINE
# =============================================================================
def run_daily_digest():
    """Execute the full digest pipeline: gather → generate → distribute."""
    logger.info("=" * 60)
    logger.info("STARTING DAILY DIGEST PIPELINE")
    logger.info("=" * 60)

    # Step 1: Gather
    raw_news = gather_news()
    if not raw_news:
        logger.error("No news gathered, aborting digest.")
        return

    # Step 2: Generate
    digest = generate_digest(raw_news)

    # Step 3: Distribute
    distribute_digest(digest)

    logger.info("=" * 60)
    logger.info("DAILY DIGEST COMPLETE")
    logger.info("=" * 60)

    return digest


if __name__ == "__main__":
    run_daily_digest()
