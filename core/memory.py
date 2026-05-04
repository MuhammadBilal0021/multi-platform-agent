# =============================================================================
# core/memory.py  —  Conversation Memory via SQLite
# Stores and retrieves per-user, per-channel message history
# brain.py calls get_history() before each turn and save_message() after
# =============================================================================

import sqlite3
import os
from datetime import datetime
from typing import List, Dict

# -----------------------------------------------------------------------------
# Database path — lives in the api/ folder next to logs.db
# Created automatically on first run, no setup needed
# -----------------------------------------------------------------------------
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "logs.db",
)

# How many past messages to load per user per channel
# 10 gives good context without blowing up the LLM token limit
MAX_HISTORY = 10


# =============================================================================
# INTERNAL — DATABASE SETUP
# =============================================================================
def _get_connection() -> sqlite3.Connection:
    """
    Opens a connection to the SQLite database.
    Creates the database file and table if they don't exist yet.
    """
    # Make sure the api/ directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts

    # Create the messages table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT    NOT NULL,
            channel   TEXT    NOT NULL,
            role      TEXT    NOT NULL,
            content   TEXT    NOT NULL,
            timestamp TEXT    NOT NULL
        )
    """)

    # Index so history lookups are fast even with millions of rows
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_channel
        ON messages (user_id, channel, id DESC)
    """)

    conn.commit()
    return conn


# =============================================================================
# PUBLIC — SAVE A MESSAGE
# Called by run_brain() after every turn, twice:
# once for the user message, once for the assistant response
# =============================================================================
def save_message(
    user_id: str,
    channel: str,
    role: str,     # "user" or "assistant"
    content: str,
) -> None:
    """
    Saves a single message to the database.
    user_id + channel together form the memory key —
    the same user on Discord and Slack has separate memory.
    """
    try:
        conn = _get_connection()
        conn.execute(
            """
            INSERT INTO messages (user_id, channel, role, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(user_id),
                str(channel),
                str(role),
                str(content),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    except Exception as e:
        # Never crash the bot because of a memory write failure
        print(f"  [memory] WARNING: failed to save message: {e}")
    finally:
        conn.close()


# =============================================================================
# PUBLIC — LOAD HISTORY
# Called by run_brain() before every turn
# Returns a list of {"role": ..., "content": ...} dicts
# brain.py converts these into LangChain HumanMessage / AIMessage objects
# =============================================================================
def get_history(
    user_id: str,
    channel: str,
    limit: int = MAX_HISTORY,
) -> List[Dict]:
    """
    Returns the last `limit` messages for this user on this channel,
    ordered oldest-first so the LLM reads them in chronological order.
    """
    try:
        conn = _get_connection()

        # Fetch the most recent N rows (DESC), then reverse to chronological order
        rows = conn.execute(
            """
            SELECT role, content FROM messages
            WHERE user_id = ? AND channel = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(user_id), str(channel), limit),
        ).fetchall()

        # Reverse so oldest message comes first (chronological order)
        return [
            {"role": row["role"], "content": row["content"]}
            for row in reversed(rows)
        ]

    except Exception as e:
        # If memory fails to load, return empty — bot still works, just no context
        print(f"  [memory] WARNING: failed to load history: {e}")
        return []
    finally:
        conn.close()


# =============================================================================
# PUBLIC — CLEAR A USER'S HISTORY
# Useful for a /reset or /forget slash command in Discord or Slack
# =============================================================================
def clear_history(user_id: str, channel: str) -> None:
    """
    Wipes all memory for a specific user on a specific channel.
    Call this from a /reset slash command so users can start fresh.
    """
    try:
        conn = _get_connection()
        conn.execute(
            "DELETE FROM messages WHERE user_id = ? AND channel = ?",
            (str(user_id), str(channel)),
        )
        conn.commit()
        print(f"  [memory] Cleared history for {user_id} on {channel}")
    except Exception as e:
        print(f"  [memory] WARNING: failed to clear history: {e}")
    finally:
        conn.close()


# =============================================================================
# PUBLIC — GET ALL LOGS (for Streamlit dashboard)
# Returns recent messages across ALL users and channels
# =============================================================================
def get_all_logs(limit: int = 100) -> List[Dict]:
    """
    Returns the most recent messages across all users and channels.
    Used by the Streamlit dashboard to display live activity.
    """
    try:
        conn = _get_connection()
        rows = conn.execute(
            """
            SELECT user_id, channel, role, content, timestamp
            FROM messages
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"  [memory] WARNING: failed to get logs: {e}")
        return []
    finally:
        conn.close()