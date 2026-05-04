# =============================================================================
# adapters/twitter_adapter.py  —  Twitter/X Platform Adapter
# Posts tweets and provides post_tweet() for workflows
# Twitter Free tier: supports posting tweets only (1,500/month)
# =============================================================================

import os
import sys
import logging

from dotenv import load_dotenv
import tweepy

# Add project root to path so 'core' module is found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import run_brain
from core.state import AgentState

load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.twitter")

# Twitter credentials
API_KEY = os.environ.get("TWITTER_API_KEY")
API_SECRET = os.environ.get("TWITTER_API_SECRET")
ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
    print("ERROR: Twitter API credentials are missing in .env")
    exit(1)

# Twitter character limit
TWITTER_MAX_CHARS = 280


# =============================================================================
# TWITTER CLIENT SETUP
# =============================================================================
client_v2 = tweepy.Client(
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_TOKEN_SECRET,
)


# =============================================================================
# HELPER — TRUNCATE FOR TWITTER
# =============================================================================
def truncate_for_twitter(text: str) -> str:
    """Truncate text to fit Twitter's 280 character limit."""
    if len(text) <= TWITTER_MAX_CHARS:
        return text
    return text[: TWITTER_MAX_CHARS - 3] + "..."


# =============================================================================
# HELPER — INVOKE THE BRAIN FOR TWEET GENERATION
# =============================================================================
def invoke_brain_for_tweet(prompt: str) -> str:
    """Ask the brain to generate tweet content."""
    state: AgentState = {
        "channel": "twitter",
        "user_id": "system",
        "username": "OmniAgent",
        "message": prompt,
        "history": [],
        "tool_results": [],
        "response": "",
        "metadata": {"platform": "twitter"},
    }
    result = run_brain(state)
    return result.get("response", "")


# =============================================================================
# PUBLIC — POST A TWEET
# Used by workflows (news_tweet.py, daily_digest.py) to post content
# =============================================================================
def post_tweet(text: str) -> dict:
    """Post a tweet. Returns the tweet data or error."""
    try:
        tweet_text = truncate_for_twitter(text)
        response = client_v2.create_tweet(text=tweet_text)
        logger.info("Posted tweet: '%s...' (ID: %s)", tweet_text[:50], response.data["id"])
        return {"status": "ok", "tweet_id": response.data["id"]}
    except Exception as e:
        logger.error("Failed to post tweet: %s", e)
        return {"status": "error", "error": str(e)}


# =============================================================================
# PUBLIC — AI-GENERATED TWEET
# Asks the brain to generate a tweet on a topic, then posts it
# =============================================================================
def post_ai_tweet(topic: str) -> dict:
    """Generate a tweet about a topic using the brain, then post it."""
    prompt = (
        f"Write a single tweet (max 270 characters) about: {topic}. "
        "Make it engaging, informative, and include relevant hashtags. "
        "Output ONLY the tweet text, nothing else."
    )
    tweet_text = invoke_brain_for_tweet(prompt)
    if tweet_text:
        return post_tweet(tweet_text)
    return {"status": "error", "error": "Brain returned empty response"}


# =============================================================================
# ENTRY POINT — TEST POSTING
# =============================================================================
if __name__ == "__main__":
    logger.info("Testing Twitter adapter...")

    # Test: post a tweet to verify credentials work
    result = post_tweet(
        "🤖 OmniAgent is now live on Twitter! "
        "Powered by LangGraph + OpenRouter. #AI #Automation"
    )

    if result["status"] == "ok":
        logger.info("Twitter adapter working! Tweet posted successfully.")
    else:
        logger.error("Twitter adapter failed: %s", result["error"])
