# =============================================================================
# adapters/email_adapter.py  —  Email Platform Adapter
# Polls Gmail inbox for new emails, processes them through the brain,
# and sends AI-generated replies via yagmail
# =============================================================================

import os
import sys
import time
import email
import imaplib
import logging
from email.header import decode_header

from dotenv import load_dotenv
import yagmail

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
logger = logging.getLogger("omniagent.email")

# Email credentials
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
    print("ERROR: GMAIL_ADDRESS or GMAIL_APP_PASSWORD is missing in .env")
    exit(1)

# How often to poll for new emails (in seconds)
POLL_INTERVAL = 30

# Initialize yagmail for sending
yag = yagmail.SMTP(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)


# =============================================================================
# HELPER — DECODE EMAIL HEADER
# =============================================================================
def decode_header_value(value: str) -> str:
    """Decode an email header value (handles encoded subjects, etc.)."""
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = ""
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(charset or "utf-8", errors="replace")
        else:
            result += part
    return result


# =============================================================================
# HELPER — EXTRACT PLAIN TEXT FROM EMAIL
# =============================================================================
def extract_body(msg) -> str:
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception:
                    return part.get_payload(decode=True).decode("latin-1", errors="replace")
    else:
        try:
            return msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            return msg.get_payload(decode=True).decode("latin-1", errors="replace")
    return ""


# =============================================================================
# HELPER — INVOKE THE BRAIN
# =============================================================================
def invoke_brain(sender: str, subject: str, body: str) -> str:
    """Build AgentState and call run_brain(), return response text."""
    # Combine subject + body as the message
    message = f"[Email Subject: {subject}]\n\n{body}"

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
    result = run_brain(state)
    return result.get("response", "Sorry, I couldn't process your email.")


# =============================================================================
# HELPER — SEND REPLY
# =============================================================================
def send_reply(to: str, subject: str, body: str):
    """Send an email reply using yagmail."""
    try:
        reply_subject = f"Re: {subject}" if not subject.startswith("Re:") else subject
        yag.send(
            to=to,
            subject=reply_subject,
            contents=body,
        )
        logger.info("Reply sent to %s (subject: '%s')", to, reply_subject[:50])
    except Exception as e:
        logger.error("Failed to send reply to %s: %s", to, e)


# =============================================================================
# PUBLIC — SEND AN EMAIL (for workflows)
# =============================================================================
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email. Used by workflows like daily_digest."""
    try:
        yag.send(to=to, subject=subject, contents=body)
        logger.info("Email sent to %s (subject: '%s')", to, subject[:50])
        return {"status": "ok"}
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return {"status": "error", "error": str(e)}


# =============================================================================
# MAIN LOOP — POLL GMAIL FOR NEW EMAILS
# =============================================================================
def poll_inbox():
    """
    Continuously poll Gmail for unread emails, process them through
    the brain, and send AI-generated replies.
    """
    logger.info("Starting email polling (every %ds)...", POLL_INTERVAL)

    while True:
        try:
            # Connect to Gmail IMAP
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            mail.select("inbox")

            # Search for unread emails
            status, message_ids = mail.search(None, "UNSEEN")

            if status != "OK" or not message_ids[0]:
                mail.logout()
                time.sleep(POLL_INTERVAL)
                continue

            ids = message_ids[0].split()
            
            # Safeguard: only process up to 3 emails at a time to prevent spam
            if len(ids) > 3:
                logger.warning("Found %d unread emails, but only processing the 3 newest to prevent spam.", len(ids))
                ids = ids[-3:]
            else:
                logger.info("Found %d unread email(s)", len(ids))

            for msg_id in ids:
                try:
                    # Fetch the email
                    status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Extract fields
                    sender = msg.get("From", "unknown@email.com")
                    subject = decode_header_value(msg.get("Subject", "No Subject"))
                    body = extract_body(msg).strip()

                    # Extract just the email address from "Name <email@domain.com>"
                    if "<" in sender and ">" in sender:
                        sender_email = sender[sender.index("<") + 1 : sender.index(">")]
                    else:
                        sender_email = sender

                    # Skip our own emails (avoid infinite reply loops)
                    if sender_email.lower() == GMAIL_ADDRESS.lower():
                        continue
                        
                    # Safeguard: Only respond to emails that explicitly mention the bot in the subject
                    if "@omniagent" not in subject.lower():
                        logger.debug("Skipping email from %s (Subject doesn't contain @OmniAgent)", sender_email)
                        continue

                    logger.info(
                        "[Email] From: %s | Subject: '%s' | Body: %d chars",
                        sender_email,
                        subject[:50],
                        len(body),
                    )

                    if not body:
                        logger.info("Empty body, skipping")
                        continue

                    # Get the brain's response
                    response_text = invoke_brain(sender_email, subject, body)

                    # Send the reply
                    send_reply(sender_email, subject, response_text)

                except Exception as e:
                    logger.error("Error processing email %s: %s", msg_id, e)

            mail.logout()

        except Exception as e:
            logger.error("Error connecting to Gmail: %s", e)

        # Wait before polling again
        time.sleep(POLL_INTERVAL)


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    logger.info("Booting Email adapter for %s...", GMAIL_ADDRESS)
    poll_inbox()
