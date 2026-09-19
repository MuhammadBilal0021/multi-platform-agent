# =============================================================================
# core/brain.py  —  The LangGraph Agent Brain
# =============================================================================

import os
import logging
import sqlite3
import time
from typing import Literal
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    AIMessage,
    ToolMessage,
)

from core.state import AgentState
from core.tools import available_tools
from core.memory import get_history, save_message
from core.security import (
    is_user_allowed,
    is_tool_allowed,
    is_tool_destructive,
    generate_nonce,
    get_tool_signature,
    hash_tool_args,
    canonical_json
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.brain")

llm = ChatOpenAI(
    model="google/gemma-4-31b-it",
    openai_api_key=os.environ.get("OPENROUTER_API_KEY", "dummy"),
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0,
)

# Cost guard metrics (reused from rag-assistant)
PRICING_USD_PER_MTOK = {
    "google/gemma-4-31b-it": {"prompt": 0.20, "completion": 0.20},
    "default": {"prompt": 0.20, "completion": 0.20}
}

MAX_RETRIES = 2

# Bind-time filtering for clarity/efficiency (Execution-time check remains in tool_executor_node)
bound_tools = [t for t in available_tools if is_tool_allowed(t.name)]
llm_with_tools = llm.bind_tools(bound_tools)

# -----------------------------------------------------------------------------
# NODE 1: ROUTER
# -----------------------------------------------------------------------------
def router_node(state: AgentState):
    meta = state.get("metadata", {}).copy()
    step_count = state.get("step_count", 0) + 1
    
    # 1. Loop Breakers
    MAX_STEPS = int(os.environ.get("MAX_STEPS", "15"))
    if step_count > MAX_STEPS:
        return {"step_count": step_count, "termination_reason": f"MAX_STEPS ({MAX_STEPS}) exceeded."}
        
    consec_sigs = state.get("consecutive_tool_signatures", [])
    if len(consec_sigs) >= 3 and len(set(consec_sigs[-3:])) == 1:
        return {"step_count": step_count, "termination_reason": f"Tool loop: repeated signature '{consec_sigs[-1]}' 3 times."}
        
    no_prog = state.get("no_progress_count", 0)
    if no_prog >= 4:
        return {"step_count": step_count, "termination_reason": "No progress count exceeded limit (4)."}

    # Build messages
    messages = []
    system_prompt = (
        f"You are OmniAgent, a helpful AI assistant operating on {state['channel']}. "
        f"You are talking to {state['username']}. "
        "Keep responses concise and relevant to the platform. "
        "Use your tools when you need current information. "
        "IMPORTANT: When using a tool, you MUST output ONLY the tool call."
    )
    messages.append(SystemMessage(content=system_prompt))

    for msg in state.get("history", []):
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=state["message"]))

    tool_results = state.get("tool_results", [])
    for msg in tool_results:
        if isinstance(msg, (ToolMessage, AIMessage)):
            messages.append(msg)
        else:
            messages.append(SystemMessage(content=f"Tool result: {msg}"))

    response = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = llm_with_tools.invoke(messages)
            break
        except Exception as e:
            logger.error(f"LLM call failed (attempt {attempt}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES:
                return {"step_count": step_count, "termination_reason": "LLM API failures exhausted retries."}

    # 2. Cost Guard
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = 0
    comp_tokens = 0
    if usage:
        prompt_tokens = usage.get("input_tokens", 0)
        comp_tokens = usage.get("output_tokens", 0)
    else:
        # Fallback for some langchain versions
        rm = getattr(response, "response_metadata", {})
        tu = rm.get("token_usage", {})
        prompt_tokens = tu.get("prompt_tokens", 0)
        comp_tokens = tu.get("completion_tokens", 0)

    model_name = "google/gemma-4-31b-it"
    pricing = PRICING_USD_PER_MTOK.get(model_name, PRICING_USD_PER_MTOK["default"])
    turn_cost = (prompt_tokens / 1_000_000) * pricing["prompt"] + (comp_tokens / 1_000_000) * pricing["completion"]
    cost_usd = state.get("cost_usd", 0.0) + turn_cost
    max_task_usd_str = os.environ.get("MAX_TASK_USD")
    if max_task_usd_str:
        MAX_TASK_USD = float(max_task_usd_str)
        if cost_usd > MAX_TASK_USD:
            return {"step_count": step_count, "cost_usd": cost_usd, "termination_reason": f"Cost guard triggered. Spent ${cost_usd:.6f} > MAX_TASK_USD (${MAX_TASK_USD:.6f})."}

    # 3. No progress tracking
    tool_calls = getattr(response, "tool_calls", [])
    has_content = bool(response.content)
    
    new_sigs = [get_tool_signature(tc["name"], tc["args"]) for tc in tool_calls]
    has_new_sig = any(sig not in consec_sigs for sig in new_sigs)
    
    if has_content or has_new_sig:
        no_prog = 0
    else:
        no_prog += 1
        
    consec_sigs_copy = list(consec_sigs)
    if new_sigs:
        consec_sigs_copy.extend(new_sigs)

    meta["latest_ai_message"] = response
    
    pending_actions = meta.get("pending_actions", {})
    for tc in tool_calls:
        if is_tool_destructive(tc["name"]):
            if tc["id"] not in pending_actions:
                pending_actions[tc["id"]] = {
                    "tool_name": tc["name"],
                    "args": tc["args"],
                    "nonce": generate_nonce(),
                    "digest": hash_tool_args(tc["args"]),
                    "expires_at": time.time() + 300,
                    "requesting_user_id": state.get("user_id")
                }
    meta["pending_actions"] = pending_actions

    new_tool_results = list(tool_results)
    if tool_calls:
        new_tool_results.append(response)

    return {
        "metadata": meta,
        "tool_results": new_tool_results,
        "step_count": step_count,
        "cost_usd": cost_usd,
        "consecutive_tool_signatures": consec_sigs_copy,
        "no_progress_count": no_prog
    }

# -----------------------------------------------------------------------------
# CONDITIONAL EDGE
# -----------------------------------------------------------------------------
def should_continue(state: AgentState) -> Literal["tool_executor", "responder"]:
    if state.get("termination_reason"):
        return "responder"

    latest_msg = state.get("metadata", {}).get("latest_ai_message")
    if latest_msg and hasattr(latest_msg, "tool_calls") and latest_msg.tool_calls:
        return "tool_executor"

    return "responder"

# -----------------------------------------------------------------------------
# NODE 2: TOOL EXECUTOR
# -----------------------------------------------------------------------------
def tool_executor_node(state: AgentState):
    latest_msg = state.get("metadata", {}).get("latest_ai_message")
    tool_calls = getattr(latest_msg, "tool_calls", [])
    
    tool_map = {t.name: t for t in available_tools}
    results = []

    for tc in tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_call_id = tc.get("id", tool_name)

        # 1. Default-Deny Allow-List (Execution time boundary)
        if not is_tool_allowed(tool_name):
            logger.warning(f"Tool {tool_name} rejected by allow-list.")
            results.append(ToolMessage(
                content=f"Error: tool '{tool_name}' is not permitted by policy.",
                tool_call_id=tool_call_id,
            ))
            continue

        if tool_name not in tool_map:
            results.append(ToolMessage(
                content=f"Error: tool '{tool_name}' does not exist.",
                tool_call_id=tool_call_id,
            ))
            continue

        # 2. Destructive Actions Gate (Nonce + Interrupt)
        if is_tool_destructive(tool_name):
            pending = state.get("metadata", {}).get("pending_actions", {}).get(tool_call_id)
            if not pending:
                results.append(ToolMessage(content="Execution aborted: Pending action not found.", tool_call_id=tool_call_id))
                continue
            
            # Persist to Checkpointer by interrupting
            resume_data = interrupt(pending)
            
            # Resumed Execution
            if not isinstance(resume_data, str) or not resume_data.startswith("CONFIRM "):
                results.append(ToolMessage(
                    content="Execution aborted: Invalid confirmation format.",
                    tool_call_id=tool_call_id
                ))
                continue
                
            provided_nonce = resume_data.split(" ", 1)[1].strip()
            if provided_nonce != pending["nonce"]:
                results.append(ToolMessage(
                    content="Execution aborted: Invalid nonce.",
                    tool_call_id=tool_call_id
                ))
                continue
                
            if time.time() > pending["expires_at"]:
                results.append(ToolMessage(
                    content="Execution aborted: Approval expired.",
                    tool_call_id=tool_call_id
                ))
                continue
                
            if pending["requesting_user_id"] != state["user_id"]:
                results.append(ToolMessage(
                    content="Execution aborted: User ID mismatch.",
                    tool_call_id=tool_call_id
                ))
                continue
                
            recomputed_digest = hash_tool_args(pending["args"])
            if recomputed_digest != pending["digest"]:
                results.append(ToolMessage(
                    content="Execution aborted: Integrity check failed.",
                    tool_call_id=tool_call_id
                ))
                continue
            
            # Use PERSISTED args
            tool_args = pending["args"]

        # Execute
        try:
            logger.info(f"Executing {tool_name}")
            output = tool_map[tool_name].invoke(tool_args)
            results.append(ToolMessage(content=str(output), tool_call_id=tool_call_id))
        except Exception as e:
            logger.error(f"Tool '{tool_name}' failed: {e}")
            results.append(ToolMessage(
                content=f"Tool {tool_name} failed: {str(e)}",
                tool_call_id=tool_call_id,
            ))

    existing = state.get("tool_results", [])
    return {"tool_results": existing + results}

# -----------------------------------------------------------------------------
# NODE 3: RESPONDER
# -----------------------------------------------------------------------------
def responder_node(state: AgentState):
    term = state.get("termination_reason")
    cost = state.get("cost_usd", 0.0)
    
    if term:
        final_text = f"Agent Terminated: {term}\nTotal Cost: ${cost:.6f}"
    else:
        latest_msg = state.get("metadata", {}).get("latest_ai_message")
        final_text = "I'm sorry, I couldn't generate a response."
        if latest_msg and hasattr(latest_msg, "content") and latest_msg.content:
            final_text = latest_msg.content.strip()

    return {"response": final_text}

# -----------------------------------------------------------------------------
# GRAPH SETUP
# -----------------------------------------------------------------------------
workflow = StateGraph(AgentState)
workflow.add_node("router", router_node)
workflow.add_node("tool_executor", tool_executor_node)
workflow.add_node("responder", responder_node)

workflow.set_entry_point("router")
workflow.add_conditional_edges("router", should_continue)
workflow.add_edge("tool_executor", "router")
workflow.add_edge("responder", END)

# Create SqliteSaver Checkpointer
sqlite_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api", "checkpoints.db")
os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
conn = sqlite3.connect(sqlite_path, check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()

brain = workflow.compile(checkpointer=checkpointer)

# -----------------------------------------------------------------------------
# PUBLIC ENTRY POINT
# -----------------------------------------------------------------------------
def run_brain(initial_state: AgentState) -> dict:
    if not is_user_allowed(initial_state["user_id"]):
        initial_state["response"] = "Unauthorized. You are not on the ALLOWED_USERS list."
        return initial_state

    thread_id = f"{initial_state['channel']}_{initial_state['user_id']}"
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = brain.get_state(config)
    is_resuming = False
    
    if snapshot.tasks and any(t.interrupts for t in snapshot.tasks):
        msg = initial_state["message"].strip()
        # Resume the graph with the message
        result_state = brain.invoke(Command(resume=msg), config)
        is_resuming = True
    else:
        initial_state["history"] = get_history(initial_state["user_id"], initial_state["channel"])
        result_state = brain.invoke(initial_state, config)

    new_snapshot = brain.get_state(config)
    if new_snapshot.tasks and any(t.interrupts for t in new_snapshot.tasks):
        pending = new_snapshot.tasks[0].interrupts[0].value
        response_text = f"Action requires confirmation: {pending['tool_name']}. Reply exactly:\nCONFIRM {pending['nonce']}"
        result_state = new_snapshot.values.copy()
        result_state["response"] = response_text
    
    if not is_resuming:
        save_message(initial_state["user_id"], initial_state["channel"], "user", initial_state["message"])
    else:
        save_message(initial_state["user_id"], initial_state["channel"], "user", initial_state["message"])

    save_message(initial_state["user_id"], initial_state["channel"], "assistant", result_state["response"])
    return result_state