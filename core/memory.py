import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from core.paths import DATA_DIR

DB_PATH = str(DATA_DIR / "logs.db")
MAX_HISTORY = 10

def _get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, user_id TEXT, channel TEXT, role TEXT, content TEXT, timestamp TEXT, platform TEXT)")
    if "platform" not in {row[1] for row in conn.execute("PRAGMA table_info(messages)")}:
        conn.execute("ALTER TABLE messages ADD COLUMN platform TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_channel ON messages(user_id,channel,id)")
    conn.commit()
    return conn

def save_message(user_id, channel, role, content, platform="unknown"):
    with closing(_get_connection()) as conn, conn:
        conn.execute("INSERT INTO messages(user_id,channel,role,content,timestamp,platform) VALUES(?,?,?,?,?,?)",
                     (str(user_id),channel,role,content[:16000],datetime.now(timezone.utc).isoformat(),platform))
        conn.execute("DELETE FROM messages WHERE timestamp < datetime('now', '-7 days')")
        conn.execute("DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 10000)")

def get_history(user_id, channel, limit=MAX_HISTORY):
    with closing(_get_connection()) as conn:
        rows=conn.execute("SELECT role,content FROM messages WHERE user_id=? AND channel=? ORDER BY id DESC LIMIT ?",
                          (str(user_id),channel,max(1,min(limit,50)))).fetchall()
        return [dict(r) for r in reversed(rows)]

def clear_history(user_id, channel):
    with closing(_get_connection()) as conn, conn:
        conn.execute("DELETE FROM messages WHERE user_id=? AND channel=?",(str(user_id),channel))

def get_all_logs(limit=100):
    with closing(_get_connection()) as conn:
        return [dict(r) for r in conn.execute("SELECT user_id,platform AS channel,role,content,timestamp FROM messages ORDER BY id DESC LIMIT ?",(max(1,min(limit,500)),))]
