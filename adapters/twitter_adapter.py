"""X API v2 posting using OAuth 1.0a user context."""
import os
import sys
from pathlib import Path
import requests
from requests_oauthlib import OAuth1
from dotenv import load_dotenv
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
load_dotenv()

def truncate_for_twitter(text):
    return text if len(text)<=280 else text[:277]+"..."

def post_tweet(text):
    if os.environ.get("ENABLE_PUBLISHING","").lower()!="true":
        return {"status":"draft","text":text}
    names=["TWITTER_API_KEY","TWITTER_API_SECRET","TWITTER_ACCESS_TOKEN","TWITTER_ACCESS_TOKEN_SECRET"]
    keys=[os.environ.get(name) for name in names]
    if not all(keys):
        return {"status":"error","error":"Twitter credentials are not configured"}
    try:
        response=requests.post("https://api.x.com/2/tweets",
            auth=OAuth1(*keys),json={"text":truncate_for_twitter(text)},timeout=15)
        response.raise_for_status()
        return {"status":"ok","tweet_id":response.json()["data"]["id"]}
    except (requests.RequestException,KeyError,ValueError):
        return {"status":"error","error":"Tweet delivery failed; inspect destination before retrying"}

def invoke_brain_for_tweet(prompt):
    from core.brain import run_brain
    result=run_brain({"channel":"twitter","user_id":"system","username":"OmniAgent",
        "message":prompt,"metadata":{"workflow":"tweet"},"history":[],"tool_results":[],"response":""})
    return result.get("response","") if result.get("status")=="ok" else ""

def post_ai_tweet(topic):
    text=invoke_brain_for_tweet("Write one tweet under 270 characters about: "+topic)
    return post_tweet(text) if text else {"status":"skipped"}

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--text",required=True,help="Preview, or publish with ENABLE_PUBLISHING=true")
    print(post_tweet(parser.parse_args().text))
