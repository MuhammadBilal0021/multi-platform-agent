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
    from core.security import is_user_allowed, is_tool_allowed
    if not is_user_allowed("system") or not is_tool_allowed("web_search"):
        return ""
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
    if result.get("status") != "ok":
        return ""
    digest = result.get("response", "")
    logger.info("Generated digest: %d chars", len(digest))
    return digest


# =============================================================================
# STEP 3: DISTRIBUTE TO ALL PLATFORMS
# =============================================================================
def distribute_digest(digest: str):
    if os.environ.get("ENABLE_PUBLISHING", "").lower() != "true":
        return {"status":"draft","text":digest}
    from core.delivery import deliver_once
    from zoneinfo import ZoneInfo
    import requests
    day=datetime.now(ZoneInfo("Asia/Karachi")).date().isoformat()
    text=f"OmniAgent Daily Digest — {day}\n\n{digest}"
    results={}
    if GMAIL_ADDRESS and os.environ.get("GMAIL_APP_PASSWORD"):
        from adapters.email_adapter import send_email
        results["email"]=deliver_once(f"digest:{day}:email",lambda:send_email(GMAIL_ADDRESS,f"OmniAgent Digest {day}",text))
    def webhook(url,payload):
        response=requests.post(url,json=payload,timeout=10)
        response.raise_for_status()
        return {"status":"ok"}
    for platform,key,payload in [
        ("discord","DISCORD_WEBHOOK_URL",{"content":text[:1900],"allowed_mentions":{"parse":[]}}),
        ("slack","SLACK_WEBHOOK_URL",{"text":text[:3000]})]:
        url=os.environ.get(key)
        if url:
            results[platform]=deliver_once(f"digest:{day}:{platform}",lambda:webhook(url,payload))
    return results


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
    if digest and os.environ.get("ENABLE_PUBLISHING", "").lower() == "true":
        distribute_digest(digest)

    logger.info("=" * 60)
    logger.info("DAILY DIGEST COMPLETE")
    logger.info("=" * 60)

    return digest


if __name__ == "__main__":
    run_daily_digest()
