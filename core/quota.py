import os
import sqlite3
import time
from contextlib import closing
from core.paths import DATA_DIR

def consume(user,platform):
    with closing(sqlite3.connect(DATA_DIR/"quota.db",timeout=10)) as conn,conn:
        conn.execute("CREATE TABLE IF NOT EXISTS requests(user TEXT,platform TEXT,created REAL)")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM requests WHERE created < ?",(time.time()-3600,))
        count=conn.execute("SELECT count(*) FROM requests WHERE user=? AND platform=?",(user,platform)).fetchone()[0]
        if count>=int(os.environ.get("MAX_REQUESTS_PER_HOUR","60")):
            return False
        conn.execute("INSERT INTO requests VALUES(?,?,?)",(user,platform,time.time()))
        return True
