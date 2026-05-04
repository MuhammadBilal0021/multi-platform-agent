# =============================================================================
# core/brain.py  —  The LangGraph Agent Brain
# All four platform adapters (Discord, Slack, Twitter, Email) call run_brain()
# =============================================================================

import os
import logging
from typing import Literal
from langgraph.graph import StateGraph, END
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
from dotenv import load_dotenv

load_dotenv()

# Set up structured logging (replaces all the print-based DEBUG statements)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.brain")

# LLM — Google Gemma 4 31B via OpenRouter (free tier, reliable tool calling)
llm = ChatOpenAI(
    model="google/gemma-4-31b-it",
    openai_api_key=os.environ.get("OPENROUTER_API_KEY"),
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0,
)

# Max tool calls per turn — prevents infinite router → tool → router loops
MAX_TOOL_ITERATIONS = 3

# Max retries if the LLM API fails (network error, rate limit, etc.)
MAX_RETRIES = 2


# =============================================================================
# NODE 1: ROUTER
# Decides what to do — answer directly, or call a tool
# Also acts as the re-reasoner after tool results come back
# =============================================================================
def router_node(state: AgentState):
    # Safety guard — if we've already called tools MAX times, force a response
    # This prevents an infinite loop if the LLM keeps issuing tool calls
    tool_results = state.get("tool_results", [])
    if len(tool_results) >= MAX_TOOL_ITERATIONS:
        logger.warning("Hit max tool iterations (%d), forcing response", MAX_TOOL_ITERATIONS)
        new_meta = state.get("metadata", {}).copy()
        new_meta["force_respond"] = True
        return {"metadata": new_meta}

    # Build the message list to send to the LLM
    messages = []

    # 1. System prompt — tells the LLM who it is and where it's talking
    system_prompt = (
        f"You are OmniAgent, a helpful AI assistant operating on {state['channel']}. "
        f"You are talking to {state['username']}. "
        "Keep responses concise and relevant to the platform. "
        "Use your tools when you need current information. "
        "Never make up facts — if unsure, search first. "
        "IMPORTANT: When using a tool, you MUST output ONLY the tool call. "
        "Do not add conversational text like 'I will search the internet' before calling a tool."
    )
    messages.append(SystemMessage(content=system_prompt))

    # 2. Conversation history — so the LLM remembers previous messages
    for msg in state.get("history", []):
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))

    # 3. Current user message
    messages.append(HumanMessage(content=state["message"]))

    # 4. Tool results from previous iteration (if we looped back from tool_executor)
    #    These are proper ToolMessage and AIMessage objects
    for msg in tool_results:
        if isinstance(msg, ToolMessage) or isinstance(msg, AIMessage):
            messages.append(msg)
        else:
            # Fallback: handle old-style string results gracefully
            messages.append(SystemMessage(content=f"Tool result: {msg}"))

    # Log the message sequence being sent to LLM
    logger.info(
        "Router: sending %d messages to LLM (history=%d, tool_results=%d)",
        len(messages),
        len(state.get("history", [])),
        len(tool_results),
    )

    # Bind tools and call the LLM — with retry logic for API failures
    llm_with_tools = llm.bind_tools(available_tools)
    response = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = llm_with_tools.invoke(messages)
            break  # Success — exit retry loop
        except Exception as e:
            logger.error("LLM call failed (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
            if attempt == MAX_RETRIES:
                # All retries exhausted — return a graceful fallback
                logger.error("All LLM retries exhausted, returning fallback response")
                new_meta = state.get("metadata", {}).copy()
                new_meta["latest_ai_message"] = AIMessage(
                    content="I'm having trouble connecting right now. Please try again in a moment."
                )
                new_meta["force_respond"] = True
                return {"metadata": new_meta}

    tool_calls = getattr(response, "tool_calls", None)
    logger.info(
        "Router: LLM responded | has_content=%s | tool_calls=%s",
        bool(response.content),
        len(tool_calls) if tool_calls else 0,
    )

    # Store the LLM response in metadata so other nodes can read it
    new_meta = state.get("metadata", {}).copy()
    new_meta["latest_ai_message"] = response
    new_meta["force_respond"] = False  # reset the flag on each fresh call

    # If the LLM issued tool calls, save this AIMessage to tool_results
    # so the next loop remembers the AI's tool request
    new_tool_results = list(state.get("tool_results", []))
    if tool_calls and len(tool_calls) > 0:
        new_tool_results.append(response)

    return {"metadata": new_meta, "tool_results": new_tool_results}


# =============================================================================
# CONDITIONAL EDGE: SHOULD CONTINUE?
# Decides whether to call tools or go straight to the final response
# =============================================================================
def should_continue(state: AgentState) -> Literal["tool_executor", "responder"]:
    # If we hit the max tool iterations limit, skip to responder immediately
    if state.get("metadata", {}).get("force_respond"):
        return "responder"

    latest_msg = state.get("metadata", {}).get("latest_ai_message")

    # If the LLM issued tool calls, route to tool_executor
    if (
        latest_msg
        and hasattr(latest_msg, "tool_calls")
        and len(latest_msg.tool_calls) > 0
    ):
        return "tool_executor"

    # No tool calls — the LLM has a final answer, go write the response
    return "responder"


# =============================================================================
# NODE 2: TOOL EXECUTOR
# Runs whatever tools the LLM requested, returns results as ToolMessages
# =============================================================================
def tool_executor_node(state: AgentState):
    latest_msg = state.get("metadata", {}).get("latest_ai_message")
    tool_calls = getattr(latest_msg, "tool_calls", [])

    # Build a name → tool lookup map
    tool_map = {t.name: t for t in available_tools}
    results = []

    for tc in tool_calls:
        tool_name    = tc["name"]
        tool_args    = tc["args"]
        tool_call_id = tc.get("id", tool_name)

        if tool_name not in tool_map:
            logger.warning("Unknown tool requested: '%s'", tool_name)
            results.append(
                ToolMessage(
                    content=f"Error: tool '{tool_name}' does not exist.",
                    tool_call_id=tool_call_id,
                )
            )
            continue

        try:
            logger.info("Executing tool: %s(%s)", tool_name, tool_args)
            output = tool_map[tool_name].invoke(tool_args)
            results.append(
                ToolMessage(
                    content=str(output),
                    tool_call_id=tool_call_id,
                )
            )
            logger.info("Tool '%s' succeeded (%d chars)", tool_name, len(str(output)))
        except Exception as e:
            # Tool failed — tell the LLM so it can answer without this result
            logger.error("Tool '%s' failed: %s", tool_name, e)
            results.append(
                ToolMessage(
                    content=f"Tool {tool_name} failed: {str(e)}. Please answer from your own knowledge.",
                    tool_call_id=tool_call_id,
                )
            )

    # Append these ToolMessages to any results from previous iterations
    existing = state.get("tool_results", [])
    return {"tool_results": existing + results}


# =============================================================================
# NODE 3: RESPONDER
# Extracts the final text from the LLM's last message
# This is what Discord, Slack, Twitter, and Email adapters read
# =============================================================================
def responder_node(state: AgentState):
    latest_msg = state.get("metadata", {}).get("latest_ai_message")

    final_text = "I'm sorry, I couldn't generate a response. Please try again."

    if latest_msg and hasattr(latest_msg, "content") and latest_msg.content:
        # .content is a non-empty string — use it
        final_text = latest_msg.content.strip()

    logger.info("Responder: final response is %d chars", len(final_text))

    # Populate the 'response' field — adapters read ONLY this field
    return {"response": final_text}


# =============================================================================
# BUILD THE LANGGRAPH GRAPH
# =============================================================================
workflow = StateGraph(AgentState)

# Register nodes
workflow.add_node("router",        router_node)
workflow.add_node("tool_executor", tool_executor_node)
workflow.add_node("responder",     responder_node)

# Entry point
workflow.set_entry_point("router")

# After router: conditionally go to tool_executor OR responder
workflow.add_conditional_edges("router", should_continue)

# After tool_executor: always loop back to router so LLM can read the results
workflow.add_edge("tool_executor", "router")

# Responder is always the final step
workflow.add_edge("responder", END)

# Compile into a runnable app
brain = workflow.compile()


# =============================================================================
# PUBLIC ENTRY POINT
# This is the ONLY function adapters should call
# =============================================================================
def run_brain(initial_state: AgentState) -> AgentState:
    """
    Main entry point called by all platform adapters.
    Automatically loads conversation history before invoking
    and saves the exchange to SQLite after.
    """
    logger.info(
        "run_brain called: user=%s channel=%s message='%s'",
        initial_state["user_id"],
        initial_state["channel"],
        initial_state["message"][:80],
    )

    # 1. Load this user's conversation history from SQLite
    #    Adapters don't need to pass history — this handles it automatically
    initial_state["history"] = get_history(
        user_id=initial_state["user_id"],
        channel=initial_state["channel"],
    )

    # 2. Run the full LangGraph brain
    result = brain.invoke(initial_state)

    # 3. Persist this turn to SQLite so next message has memory
    save_message(
        user_id=initial_state["user_id"],
        channel=initial_state["channel"],
        role="user",
        content=initial_state["message"],
    )
    save_message(
        user_id=initial_state["user_id"],
        channel=initial_state["channel"],
        role="assistant",
        content=result["response"],
    )

    logger.info("run_brain complete: response=%d chars", len(result["response"]))
    return result