import os
import secrets
from fastapi import FastAPI, Header, HTTPException, Depends, Query
from core.memory import get_all_logs

app=FastAPI(title="OmniAgent monitoring")

def authorize(authorization: str = Header(default="")):
    token=os.environ.get("OMNI_ADMIN_TOKEN","")
    if len(token)<32 or not secrets.compare_digest(authorization.encode(), ("Bearer "+token).encode()):
        raise HTTPException(401,"Authentication required")

@app.get("/health")
def health():
    return {"status":"ok","scope":"monitoring API only"}

@app.get("/logs", dependencies=[Depends(authorize)])
def logs(limit: int=Query(50,ge=1,le=500)):
    rows=get_all_logs(limit)
    return {"count":len(rows),"logs":rows}

@app.get("/stats", dependencies=[Depends(authorize)])
def stats():
    rows=get_all_logs(500)
    return {"messages_in_recent_sample":len(rows),"unique_users_in_recent_sample":len({r["user_id"] for r in rows})}

@app.post("/webhook/slack")
@app.post("/webhook/email")
def retired_webhook():
    raise HTTPException(410,"Unsigned webhooks removed. Use the Slack Bolt adapter or signed email commands.")

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="127.0.0.1",port=8000)
