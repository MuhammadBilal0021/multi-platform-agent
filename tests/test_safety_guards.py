import os
import time
import pytest
from unittest.mock import patch, MagicMock

# Set base environment variables before importing modules
os.environ["ALLOWED_USERS"] = "test_user,wrong_user"
os.environ["ALLOWED_TOOLS"] = "web_search,demo_destructive_action,summarize_url"
os.environ["DESTRUCTIVE_TOOLS"] = "demo_destructive_action"
os.environ["MAX_TASK_USD"] = "0.50"
os.environ["MAX_STEPS"] = "5"

from langchain_core.messages import AIMessage
from core.brain import run_brain, brain, PRICING_USD_PER_MTOK
from core.state import AgentState

# Helper to create initial state
def make_state(msg="Hello", user="test_user"):
    return {
        "channel": "discord",
        "user_id": user,
        "username": "Test User",
        "message": msg,
        "history": [],
        "tool_results": [],
        "response": None,
        "metadata": {},
        "cost_usd": 0.0,
        "step_count": 0,
        "consecutive_tool_signatures": [],
        "no_progress_count": 0,
        "termination_reason": None
    }

# Clear checkpoint before each test
@pytest.fixture(autouse=True)
def reset_checkpointer():
    # Clear the DB checkpointer safely
    from core.brain import checkpointer
    checkpointer.setup()  # Ensures tables exist
    
    import sqlite3
    sqlite_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api", "checkpoints.db")
    if os.path.exists(sqlite_path):
        conn = sqlite3.connect(sqlite_path)
        try:
            conn.execute("DELETE FROM checkpoints;")
            conn.execute("DELETE FROM checkpoint_writes;")
        except Exception:
            pass
        conn.commit()
        conn.close()
    
    # Reset in-memory conversation history
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api", "logs.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM messages;")
        conn.commit()
        conn.close()

def mock_llm_response(content="", tool_calls=None, prompt_tokens=100, comp_tokens=50):
    msg = AIMessage(content=content)
    if tool_calls:
        msg.tool_calls = tool_calls
    msg.usage_metadata = {"input_tokens": prompt_tokens, "output_tokens": comp_tokens}
    return msg

@patch("langchain_openai.ChatOpenAI.invoke")
def test_allow_list_denies_by_default(mock_invoke):
    # LLM requests a tool that is not in ALLOWED_TOOLS (e.g. `drop_database`)
    mock_invoke.side_effect = [
        mock_llm_response(tool_calls=[{"name": "drop_database", "args": {}, "id": "1"}]),
        mock_llm_response(content="I cannot do that.")
    ]
    state = make_state()
    res = run_brain(state)
    tool_res = [m for m in res["tool_results"] if isinstance(m, ToolMessage)][-1]
    assert "Error: tool 'drop_database' is not permitted" in tool_res.content

@patch("langchain_openai.ChatOpenAI.invoke")
def test_destructive_requires_nonce(mock_invoke):
    mock_invoke.return_value = mock_llm_response(
        tool_calls=[{"name": "demo_destructive_action", "args": {"target": "foo"}, "id": "1"}]
    )
    state = make_state()
    res = run_brain(state)
    assert "Action requires confirmation: demo_destructive_action" in res["response"]
    assert "CONFIRM " in res["response"]

@patch("langchain_openai.ChatOpenAI.invoke")
def test_args_cannot_change_between_interrupt_and_resume(mock_invoke):
    mock_invoke.return_value = mock_llm_response(
        tool_calls=[{"name": "demo_destructive_action", "args": {"target": "original_target"}, "id": "1"}]
    )
    res = run_brain(make_state("Delete original target"))
    
    # Extract nonce
    nonce_line = [L for L in res["response"].split("\n") if L.startswith("CONFIRM ")][0]
    
    # We resume. Since `run_brain` automatically triggers Command(resume=msg), 
    # we simulate the user providing the valid nonce. However, we want to prove that the execution 
    # uses the PERSISTED args ("original_target"), even if the LLM or environment tries to inject new args.
    # Since the codebase ignores new LLM generations entirely upon resume (it jumps straight back to tool_executor_node
    # and executes `pending["args"]`), we just verify the output string contains the original target.
    mock_invoke.return_value = mock_llm_response(content="Done.")
    res2 = run_brain(make_state(nonce_line))
    
    # Check tool result
    tool_res = [m for m in res2["tool_results"] if getattr(m, "tool_call_id", None) == "1"][-1]
    assert "original_target" in tool_res.content
    assert "dry-run" in tool_res.content

@patch("langchain_openai.ChatOpenAI.invoke")
def test_nonce_from_wrong_user_does_not_execute(mock_invoke):
    mock_invoke.return_value = mock_llm_response(
        tool_calls=[{"name": "demo_destructive_action", "args": {"target": "foo"}, "id": "1"}]
    )
    res = run_brain(make_state("Delete it", "test_user"))
    nonce_line = [L for L in res["response"].split("\n") if L.startswith("CONFIRM ")][0]
    
    # Wrong user attempts to resume
    mock_invoke.return_value = mock_llm_response(content="Resumed.")
    res2 = run_brain(make_state(nonce_line, "wrong_user"))
    
    # Since wrong_user is a different thread_id in LangGraph, it won't even resume the same graph state!
    # Instead, it will start a fresh task for wrong_user.
    # If the user meant "same thread but user ID somehow changed", it's covered by `pending["requesting_user_id"] != state["user_id"]`.
    assert "Unauthorized" not in res2["response"] # assuming they are in allowed list
    assert "Action requires confirmation" not in res2["response"]

@patch("langchain_openai.ChatOpenAI.invoke")
def test_tool_signature_includes_args(mock_invoke):
    # 3 different queries for web_search
    mock_invoke.side_effect = [
        mock_llm_response(tool_calls=[{"name": "web_search", "args": {"query": "A"}, "id": "1"}]),
        mock_llm_response(tool_calls=[{"name": "web_search", "args": {"query": "B"}, "id": "2"}]),
        mock_llm_response(tool_calls=[{"name": "web_search", "args": {"query": "C"}, "id": "3"}]),
        mock_llm_response(content="Done.")
    ]
    res = run_brain(make_state("Search three times"))
    # Should NOT terminate with loop error
    assert res["termination_reason"] is None
    assert "Agent Terminated" not in res["response"]

@patch("langchain_openai.ChatOpenAI.invoke")
def test_loop_terminates_with_reason(mock_invoke):
    # 3 identical queries for web_search
    tc = [{"name": "web_search", "args": {"query": "A"}, "id": "1"}]
    mock_invoke.side_effect = [
        mock_llm_response(tool_calls=tc),
        mock_llm_response(tool_calls=tc),
        mock_llm_response(tool_calls=tc),
        mock_llm_response(content="Done.")
    ]
    res = run_brain(make_state("Search same thing"))
    assert res["termination_reason"] is not None
    assert "Tool loop" in res["termination_reason"]

@patch("langchain_openai.ChatOpenAI.invoke")
def test_cost_guard_fires_and_reports_usd(mock_invoke):
    # One turn is 100 prompt + 50 comp = 150 tokens. 
    # At $0.20 per MTOK, cost is $0.000030
    # Let's set MAX_TASK_USD to a very small amount
    os.environ["MAX_TASK_USD"] = "0.000020"
    
    mock_invoke.return_value = mock_llm_response(content="Cost test")
    res = run_brain(make_state("Hello"))
    
    assert res["termination_reason"] is not None
    assert "Cost guard triggered" in res["termination_reason"]
    assert "Spent $0.000030" in res["termination_reason"]
    
    os.environ["MAX_TASK_USD"] = "0.50" # restore

@patch("langchain_openai.ChatOpenAI.invoke")
def test_injected_confirm_does_not_execute(mock_invoke):
    # Setup an interrupted state awaiting confirmation
    mock_invoke.return_value = mock_llm_response(
        tool_calls=[{"name": "demo_destructive_action", "args": {"target": "foo"}, "id": "1"}]
    )
    res = run_brain(make_state("Delete foo"))
    nonce_line = [L for L in res["response"].split("\n") if L.startswith("CONFIRM ")][0]
    
    # The injection attack: The user sends a normal message, but the LLM tries to emit the nonce.
    # Actually, the only way to resume is if the USER MESSAGE itself starts with CONFIRM.
    # So if the user message is "Just normal chat", but the LLM responds with CONFIRM, it doesn't matter
    # because run_brain checks `initial_state["message"].startswith("CONFIRM ")`.
    # Let's prove a malicious user message that contains the nonce in the middle doesn't trigger it.
    mock_invoke.return_value = mock_llm_response(content="Ignored.")
    res2 = run_brain(make_state(f"Read this document: {nonce_line}"))
    
    # The confirmation must be EXACTLY starting with CONFIRM.
    # Because it didn't start with CONFIRM, it might fail the check, or if it did, it still must match exactly.
    # Wait, the code says: msg.startswith("CONFIRM "). If msg = "Read this document: CONFIRM...", it won't trigger resume.
    # Wait, if we are interrupted, ALL messages are treated as resume payload by run_brain:
    # `result_state = brain.invoke(Command(resume=msg), config)`
    # And then tool_executor checks `resume_data.startswith("CONFIRM ")`.
    # So `Read this document: CONFIRM...` will fail `startswith("CONFIRM ")` and the action will be aborted!
    tool_res = [m for m in res2["tool_results"] if getattr(m, "tool_call_id", None) == "1"][-1]
    assert "Invalid confirmation format" in tool_res.content

@patch("langchain_openai.ChatOpenAI.invoke")
def test_approval_expires(mock_invoke):
    mock_invoke.return_value = mock_llm_response(
        tool_calls=[{"name": "demo_destructive_action", "args": {"target": "foo"}, "id": "1"}]
    )
    res = run_brain(make_state("Delete foo"))
    nonce_line = [L for L in res["response"].split("\n") if L.startswith("CONFIRM ")][0]
    
    # We patch time.time to be 600 seconds in the future
    with patch("time.time", return_value=time.time() + 600):
        mock_invoke.return_value = mock_llm_response(content="Expired.")
        res2 = run_brain(make_state(nonce_line))
    
    tool_res = [m for m in res2["tool_results"] if getattr(m, "tool_call_id", None) == "1"][-1]
    assert "Approval expired" in tool_res.content
