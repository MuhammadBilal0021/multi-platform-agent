# =============================================================================
# api/main.py  —  FastAPI Webhook Server
# Receives webhooks from Slack, Email, and other platforms
# Also serves health check and stats endpoints for monitoring
# =============================================================================

import os
import sys
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import run_brain
from core.state import AgentState
from core.memory import get_all_logs

load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.api")

# Track server start time for uptime calculation
START_TIME = datetime.utcnow()


# =============================================================================
# APP LIFECYCLE
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("OmniAgent API server starting up")
    yield
    logger.info("OmniAgent API server shutting down")


app = FastAPI(
    title="OmniAgent API",
    description="Webhook receiver and monitoring API for the OmniAgent multi-platform brain.",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# GET /health  —  Health check endpoint
# =============================================================================
@app.get("/health")
async def health():
    """Health check — returns server status and uptime."""
    uptime = (datetime.utcnow() - START_TIME).total_seconds()
    return {
        "status": "healthy",
        "agent": "OmniAgent",
        "uptime_seconds": round(uptime, 1),
        "timestamp": datetime.utcnow().isoformat(),
    }


# =============================================================================
# GET /stats  —  Agent activity stats
# =============================================================================
@app.get("/stats")
async def stats():
    """Returns basic agent activity metrics from the database."""
    logs = get_all_logs(limit=10000)

    if not logs:
        return {
            "total_messages": 0,
            "unique_users": 0,
            "active_platforms": [],
            "agent_replies": 0,
        }

    users = set()
    platforms = set()
    agent_replies = 0

    for log in logs:
        users.add(log["user_id"])
        platforms.add(log["channel"])
        if log["role"] == "assistant":
            agent_replies += 1

    return {
        "total_messages": len(logs),
        "unique_users": len(users),
        "active_platforms": sorted(platforms),
        "agent_replies": agent_replies,
    }


# =============================================================================
# GET /logs  —  Recent logs (JSON)
# =============================================================================
@app.get("/logs")
async def recent_logs(limit: int = 50):
    """Returns the most recent N log entries."""
    if limit > 500:
        limit = 500
    logs = get_all_logs(limit=limit)
    return {"count": len(logs), "logs": logs}


# =============================================================================
# POST /webhook/slack  —  Slack Event Subscription
# Slack sends a URL verification challenge on setup, then events after
# =============================================================================
@app.post("/webhook/slack")
async def slack_webhook(request: Request):
    """
    Receives Slack events via Event Subscriptions.
    Handles the URL verification challenge and incoming messages.
    """
    body = await request.json()

    # Slack URL verification challenge (sent once during setup)
    if body.get("type") == "url_verification":
        logger.info("Slack URL verification challenge received")
        return {"challenge": body.get("challenge")}

    # Actual event
    event = body.get("event", {})
    event_type = event.get("type")

    # We only care about messages (not bot messages, not edits)
    if event_type != "message" or event.get("subtype"):
        return {"status": "ignored"}

    user_id = event.get("user", "unknown")
    text = event.get("text", "").strip()
    channel_id = event.get("channel", "unknown")

    if not text:
        return {"status": "empty_message"}

    logger.info("Slack webhook: user=%s channel=%s msg='%s'", user_id, channel_id, text[:80])

    # Build AgentState and invoke the brain
    state: AgentState = {
        "channel": "slack",
        "user_id": user_id,
        "username": user_id,  # Slack doesn't include username in events
        "message": text,
        "history": [],
        "tool_results": [],
        "response": "",
        "metadata": {
            "slack_channel": channel_id,
            "thread_ts": event.get("ts"),
        },
    }

    try:
        result = run_brain(state)
        response_text = result.get("response", "Sorry, I couldn't generate a response.")
    except Exception as e:
        logger.error("Brain error on Slack webhook: %s", e)
        response_text = "⚠️ An error occurred processing your message."

    # NOTE: To actually reply in Slack, we need to POST to Slack's API
    # This will be handled by the Slack adapter (slack_adapter.py)
    # For now, we just return the response
    return {
        "status": "ok",
        "response": response_text,
        "channel": channel_id,
    }


# =============================================================================
# POST /webhook/email  —  Inbound Email Notifications
# Services like SendGrid or Mailgun can forward emails here
# =============================================================================
@app.post("/webhook/email")
async def email_webhook(request: Request):
    """
    Receives inbound email notifications.
    Expected payload: {from, subject, body}
    """
    body = await request.json()

    sender = body.get("from", "unknown@email.com")
    subject = body.get("subject", "No Subject")
    email_body = body.get("body", "").strip()

    if not email_body:
        return {"status": "empty_body"}

    logger.info("Email webhook: from=%s subject='%s'", sender, subject[:50])

    # Combine subject + body as the message
    message = f"[Email Subject: {subject}]\n\n{email_body}"

    state: AgentState = {
        "channel": "email",
        "user_id": sender,
        "username": sender.split("@")[0],
        "message": message,
        "history": [],
        "tool_results": [],
        "response": "",
        "metadata": {
            "email_from": sender,
            "email_subject": subject,
        },
    }

    try:
        result = run_brain(state)
        response_text = result.get("response", "Sorry, I couldn't generate a response.")
    except Exception as e:
        logger.error("Brain error on email webhook: %s", e)
        response_text = "An error occurred processing your email."

    return {
        "status": "ok",
        "response": response_text,
        "reply_to": sender,
    }


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting OmniAgent API on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
