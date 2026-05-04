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
    tweet_text = result.get("response", "")

    if not tweet_text:
        logger.error("Brain returned empty tweet, aborting.")
        return

    # Step 3: Post the tweet
    logger.info("Generated tweet: %s", tweet_text[:100])
    post_result = post_tweet(tweet_text)
    logger.info("Tweet result: %s", post_result)

    return post_result


if __name__ == "__main__":
    run_news_tweet()
