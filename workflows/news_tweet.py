# =============================================================================
# workflows/news_tweet.py  —  AI News Tweet Generator
# Searches for trending AI news and posts a tweet about it
# =============================================================================

import os
import sys
import logging

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import run_brain
from core.state import AgentState
from core.tools import web_search
from adapters.twitter_adapter import post_tweet

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.news_tweet")


def run_news_tweet():
    """Search for AI news, generate a tweet, and post it."""
    from core.security import is_user_allowed, is_tool_allowed
    if not is_user_allowed("system") or not is_tool_allowed("web_search"):
        return {"status":"skipped"}
    logger.info("Starting news tweet workflow...")

    # Step 1: Search for news
    try:
        raw_news = web_search.invoke({"query": "latest AI news today"})
    except Exception as e:
        logger.error("Failed to search news: %s", e)
        return

    # Step 2: Ask brain to write a tweet
    prompt = (
        "Based on this news, write ONE engaging tweet (max 270 chars) "
        "about the most interesting AI development. Include 1-2 hashtags. "
        "Output ONLY the tweet text.\n\n"
        f"{raw_news[:2000]}"
    )

    state: AgentState = {
        "channel": "workflow",
        "user_id": "system",
        "username": "NewsTweet",
        "message": prompt,
        "history": [],
        "tool_results": [],
        "response": "",
        "metadata": {"workflow": "news_tweet"},
    }
    result = run_brain(state)
    if result.get("status") != "ok":
        logger.warning("Tweet generation did not succeed; nothing published")
        return {"status": "skipped"}
    tweet_text = result.get("response", "")

    if not tweet_text:
        logger.error("Brain returned empty tweet, aborting.")
        return

    # Step 3: Post the tweet
    logger.info("Generated tweet: %s", tweet_text[:100])
    if os.environ.get("ENABLE_PUBLISHING", "").lower() != "true":
        return {"status":"draft", "text":tweet_text}
    from core.delivery import deliver_once
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now=datetime.now(ZoneInfo("Asia/Karachi"))
    slot="12" if now.hour<18 else "18"
    post_result = deliver_once(f"tweet:{now.date()}:{slot}", lambda:post_tweet(tweet_text))
    logger.info("Tweet result: %s", post_result)

    return post_result


if __name__ == "__main__":
    run_news_tweet()
