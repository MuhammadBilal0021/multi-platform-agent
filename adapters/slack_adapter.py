# =============================================================================
# adapters/slack_adapter.py  —  Slack Platform Adapter
# Translates Slack messages → AgentState → brain → Slack reply
# Uses Socket Mode so no public URL is needed for development
# =============================================================================

import os
import sys
import logging

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Add project root to path so 'core' module is found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import run_brain
from core.state import AgentState
from core.memory import clear_history

load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.slack")

# Slack credentials
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")  # Needed for Socket Mode

if not SLACK_BOT_TOKEN or not SLACK_SIGNING_SECRET:
    print("ERROR: SLACK_BOT_TOKEN or SLACK_SIGNING_SECRET is missing in .env")
    exit(1)

# Initialize the Slack Bolt app
app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)


# =============================================================================
# HELPER — INVOKE THE BRAIN
# =============================================================================
def invoke_brain(user_id: str, username: str, message_text: str, metadata: dict) -> str:
    """Build AgentState and call run_brain(), return response text."""
    state: AgentState = {
        "channel":      "slack",
        "user_id":      user_id,
        "username":     username,
        "message":      message_text,
        "history":      [],   # run_brain() loads from SQLite automatically
        "tool_results": [],
        "response":     "",
        "metadata":     metadata,
    }
    result = run_brain(state)
    return result.get("response", "Sorry, I could not generate a response.")


# =============================================================================
# EVENT — APP MENTION
# Fires when someone @mentions the bot in a channel
# =============================================================================
@app.event("app_mention")
def handle_mention(event, say):
    user_id = event.get("user", "unknown")
    text = event.get("text", "").strip()
    channel = event.get("channel", "unknown")
    thread_ts = event.get("ts")

    # Strip the bot mention from the text (e.g., "<@U123ABC> hello" → "hello")
    # Bot mentions look like <@BOTID>
    import re
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    if not clean:
        say("Hi! Mention me with a question and I'll help.", thread_ts=thread_ts)
        return

    logger.info("[Mention] User %s in #%s: %s", user_id, channel, clean[:100])

    metadata = {
        "slack_channel": channel,
        "thread_ts": thread_ts,
    }

    try:
        response_text = invoke_brain(
            user_id=user_id,
            username=user_id,
            message_text=clean,
            metadata=metadata,
        )
    except Exception as e:
        logger.error("Brain error for Slack user %s: %s", user_id, e)
        response_text = "⚠️ Something went wrong while processing your request. Please try again."

    # Reply in thread to keep channels clean
    say(response_text, thread_ts=thread_ts)
    logger.info("Replied to %s (%d chars)", user_id, len(response_text))


# =============================================================================
# EVENT — DIRECT MESSAGE
# Fires when someone DMs the bot directly
# =============================================================================
@app.event("message")
def handle_dm(event, say):
    # Only respond to DMs (channel type "im"), ignore bot messages and subtypes
    if event.get("channel_type") != "im":
        return
    if event.get("subtype"):
        return
    if event.get("bot_id"):
        return

    user_id = event.get("user", "unknown")
    text = event.get("text", "").strip()

    if not text:
        return

    logger.info("[DM] User %s: %s", user_id, text[:100])

    metadata = {
        "slack_channel": event.get("channel", "dm"),
        "is_dm": True,
    }

    try:
        response_text = invoke_brain(
            user_id=user_id,
            username=user_id,
            message_text=text,
            metadata=metadata,
        )
    except Exception as e:
        logger.error("Brain error for Slack DM from %s: %s", user_id, e)
        response_text = "⚠️ Something went wrong while processing your request. Please try again."

    say(response_text)
    logger.info("Replied to DM from %s (%d chars)", user_id, len(response_text))


# =============================================================================
# SLASH COMMAND — /reset
# Clears the user's conversation memory for Slack
# =============================================================================
@app.command("/reset")
def handle_reset(ack, command):
    ack()
    user_id = command.get("user_id", "unknown")
    clear_history(user_id=user_id, channel="slack")
    logger.info("Memory cleared for Slack user %s", user_id)
    # Respond ephemerally (only the user sees it)
    return {"response_type": "ephemeral", "text": "✅ Memory cleared. Let's start fresh!"}


# =============================================================================
# SLASH COMMAND — /help
# =============================================================================
@app.command("/omnihelp")
def handle_help(ack, respond):
    ack()
    respond(
        text=(
            "🧠 *OmniAgent — Help*\n\n"
            "• *Chat:* Mention me with `@OmniAgent` in any channel or DM me directly.\n"
            "• *Web Search:* Ask about recent news, events, or anything I need to look up.\n"
            "• *Time & Date:* Ask what time it is in any timezone.\n"
            "• *Summarize Links:* Share a URL and ask me to summarize it.\n"
            "• `/reset` — Clear our conversation memory.\n"
            "• `/omnihelp` — Show this message.\n\n"
            "_Powered by LangGraph + OpenRouter_"
        ),
        response_type="ephemeral",
    )


# =============================================================================
# PUBLIC — START FUNCTION (used by run_all.py supervisor)
# =============================================================================
def start_slack_bot():
    """Start the Slack bot. Called by the supervisor."""
    if SLACK_APP_TOKEN:
        logger.info("Booting Slack adapter in Socket Mode...")
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        handler.start()
    else:
        logger.info("Booting Slack adapter in HTTP mode on port 3000...")
        app.start(port=3000)


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    start_slack_bot()

