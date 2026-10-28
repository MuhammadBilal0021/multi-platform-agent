import sqlite3
import time
from contextlib import closing
from core.paths import DATA_DIR

def deliver_once(key,send):
    # Reserve before sending: a crash after delivery must not cause an automatic duplicate.
    # Failed/uncertain delivery needs operator reconciliation, not blind retries.
    with closing(sqlite3.connect(DATA_DIR/"delivery.db")) as conn,conn:
        conn.execute("CREATE TABLE IF NOT EXISTS deliveries(key TEXT PRIMARY KEY,status TEXT,created REAL)")
        try:
            conn.execute("INSERT INTO deliveries VALUES(?,?,?)",(key,"pending",time.time()))
        except sqlite3.IntegrityError:
            return {"status":"duplicate_or_uncertain"}
    try:
        result=send()
        status="sent" if result.get("status")=="ok" else "failed"
    except Exception:
        result={"status":"error"};status="uncertain"
    with closing(sqlite3.connect(DATA_DIR/"delivery.db")) as conn,conn:
        conn.execute("UPDATE deliveries SET status=? WHERE key=?",(status,key))
    return result
