import hashlib
import hmac
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
import pytest
from langchain_core.messages import AIMessage
import core.brain as b
from core.urls import clean_url
from core.fetch import public_addresses,fetch_html
from core.email_auth import verify_command

@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("ALLOWED_USERS","test_user")
    monkeypatch.setenv("ALLOWED_TOOLS","get_time,demo_destructive_action")
    monkeypatch.setenv("DESTRUCTIVE_TOOLS","demo_destructive_action")
    monkeypatch.setenv("MAX_STEPS","15")
    b.conn.execute("DELETE FROM checkpoints");b.conn.execute("DELETE FROM writes");b.conn.commit()

def state(message="hello",room="private"):
    return dict(channel="discord",user_id="test_user",username="test",message=message,
        history=[],tool_results=[],response="",metadata={"channel_id":room})

def test_new_messages_do_not_inherit_termination(monkeypatch):
    monkeypatch.setenv("MAX_STEPS","1")
    with patch("langchain_openai.ChatOpenAI.invoke",return_value=AIMessage(content="hello")):
        for _ in range(4):
            result=b.run_brain(state())
            assert result["status"]=="ok" and result["step_count"]==1

def test_public_and_private_history_are_separate():
    with patch("langchain_openai.ChatOpenAI.invoke",return_value=AIMessage(content="hello")) as llm:
        b.run_brain(state("private secret"))
        b.run_brain(state("public question","public"))
        messages=llm.call_args.args[0]
        assert all("private secret" not in m.content for m in messages)

def test_reset_removes_pending_action():
    tc={"name":"demo_destructive_action","args":{"target":"example"},"id":"reset"}
    with patch("langchain_openai.ChatOpenAI.invoke",return_value=AIMessage(content="",tool_calls=[tc])):
        result=b.run_brain(state())
    assert result["status"]=="pending" and '"target":"example"' in result["response"]
    assert b.reset_conversation(state())
    assert not b.brain.get_state({"configurable":{"thread_id":b.conversation_scope(state())}}).tasks

def test_tool_before_interrupt_not_reexecuted():
    calls=[]
    tool=SimpleNamespace(name="get_time",invoke=lambda args:calls.append(args) or "now")
    action=SimpleNamespace(name="demo_destructive_action",invoke=lambda args:"done")
    response=AIMessage(content="",tool_calls=[
        {"name":"get_time","args":{},"id":"a"},
        {"name":"demo_destructive_action","args":{"target":"x"},"id":"b"}])
    with patch.object(b,"available_tools",[tool,action]):
        with patch("langchain_openai.ChatOpenAI.invoke",return_value=response):
            first=b.run_brain(state())
        nonce=next(line for line in first["response"].splitlines() if line.startswith("CONFIRM "))
        with patch("langchain_openai.ChatOpenAI.invoke",return_value=AIMessage(content="done")):
            assert b.run_brain(state(nonce))["status"]=="ok"
    assert len(calls)==1

def test_cancel_does_not_invoke_model_or_tool():
    tc={"name":"demo_destructive_action","args":{"target":"example"},"id":"cancel"}
    with patch("langchain_openai.ChatOpenAI.invoke",return_value=AIMessage(content="",tool_calls=[tc])):
        assert b.run_brain(state())["status"]=="pending"
    with patch("langchain_openai.ChatOpenAI.invoke") as llm:
        assert b.run_brain(state("CANCEL"))["status"]=="cancelled"
        llm.assert_not_called()

@pytest.mark.parametrize("url",["http://127.0.0.1","http://169.254.169.254","http://[::1]","file:///etc/passwd","https://user:pass@example.com","http://example.com:1234"])
def test_unsafe_url_rejected(url):
    with pytest.raises(ValueError): clean_url(url)

def test_mixed_dns_rejected():
    answers=[(2,1,6,"",("93.184.216.34",80)),(2,1,6,"",("127.0.0.1",80))]
    with patch("socket.getaddrinfo",return_value=answers),pytest.raises(ValueError):
        public_addresses("example.com",80)

def test_redirect_is_revalidated():
    response=MagicMock(status=302,headers={"Location":"http://127.0.0.1/"})
    pool=MagicMock();pool.urlopen.return_value=response
    with patch("core.fetch.public_addresses",return_value=["93.184.216.34"]),patch("urllib3.HTTPConnectionPool",return_value=pool),pytest.raises(ValueError):
        fetch_html("http://example.com")
    pool.close.assert_called()

def test_signed_email_and_replay(monkeypatch):
    secret="s"*40;monkeypatch.setenv("EMAIL_COMMAND_SECRET",secret)
    stamp=str(int(time.time()))
    payload=json.dumps(["a@example.com","@omniagent","hello",stamp],separators=(",",":"))
    sig=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).hexdigest()
    assert verify_command("a@example.com","@omniagent","hello",stamp,sig)
    assert not verify_command("a@example.com","@omniagent","hello",stamp,sig)
    assert not verify_command("a@example.com","@omniagent","modified",stamp,sig)

def test_monitoring_requires_auth(monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app
    monkeypatch.setenv("OMNI_ADMIN_TOKEN","t"*40)
    with TestClient(app) as client:
        assert client.get("/logs").status_code==401
        assert client.get("/logs?limit=-1",headers={"Authorization":"Bearer "+"t"*40}).status_code==422
        assert client.get("/logs",headers={"Authorization":"Bearer "+"t"*40}).status_code==200
        assert client.post("/webhook/slack",json={"event":{"user":"test_user"}}).status_code==410


def test_workflow_does_not_publish_errors():
    import workflows.daily_digest as digest
    with patch.object(digest,"run_brain",return_value={"status":"unauthorized","response":"Unauthorized"}):
        assert digest.generate_digest("news")==""


def test_delivery_not_repeated():
    from core.delivery import deliver_once
    import uuid
    calls=[]
    key=str(uuid.uuid4())
    assert deliver_once(key,lambda:calls.append(1) or {"status":"ok"})["status"]=="ok"
    assert deliver_once(key,lambda:calls.append(1) or {"status":"ok"})["status"]=="duplicate_or_uncertain"
    assert calls==[1]

def test_tweet_draft_and_authenticated_send(monkeypatch):
    from adapters.twitter_adapter import post_tweet
    monkeypatch.setenv("ENABLE_PUBLISHING","false")
    with patch("requests.post") as send:
        assert post_tweet("draft")["status"]=="draft"
        send.assert_not_called()
    monkeypatch.setenv("ENABLE_PUBLISHING","true")
    for name in ["TWITTER_API_KEY","TWITTER_API_SECRET","TWITTER_ACCESS_TOKEN","TWITTER_ACCESS_TOKEN_SECRET"]:
        monkeypatch.setenv(name,"test-value")
    response=MagicMock();response.json.return_value={"data":{"id":"123"}}
    with patch("requests.post",return_value=response) as send:
        assert post_tweet("approved text")["tweet_id"]=="123"
        assert send.call_args.args[0]=="https://api.x.com/2/tweets"
        import requests
        prepared=requests.Request("POST",send.call_args.args[0],auth=send.call_args.kwargs["auth"],json={"text":"test"}).prepare()
        assert b"oauth_signature" in prepared.headers["Authorization"]
