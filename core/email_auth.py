import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import closing
from core.paths import DATA_DIR

def verify_command(sender, subject, body, timestamp, signature):
    secret=os.environ.get("EMAIL_COMMAND_SECRET","")
    if len(secret)<32:
        return False
    try:
        if abs(time.time()-int(timestamp))>300:
            return False
    except (TypeError,ValueError):
        return False
    payload=json.dumps([sender,subject,body,str(timestamp)],ensure_ascii=True,separators=(",",":"))
    expected=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest()
    if not isinstance(signature,str) or not hmac.compare_digest(signature,expected):
        return False
    with closing(sqlite3.connect(DATA_DIR/"email_replay.db")) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS used(signature TEXT PRIMARY KEY, created REAL)")
        conn.execute("DELETE FROM used WHERE created < ?",(time.time()-600,))
        try:
            conn.execute("INSERT INTO used VALUES(?,?)",(signature,time.time()))
        except sqlite3.IntegrityError:
            return False
    return True
