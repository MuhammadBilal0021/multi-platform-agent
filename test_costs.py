import os
import time
import random
from unittest.mock import patch

os.environ["ALLOWED_USERS"] = "cost_test_user," + os.environ.get("ALLOWED_USERS", "")
os.environ["MAX_TASK_USD"] = "100.0"

from core.brain import run_brain
from langchain_core.messages import AIMessage

tasks = [
    "Hello there!",
    "Search for the weather in Tokyo.",
    "What time is it in UTC?",
    "Can you summarize this URL: https://example.com?",
    "Who won the last super bowl?",
    "What is the capital of France?",
    "Tell me a short joke.",
    "Search for Python langgraph examples.",
    "How many letters in the alphabet?",
    "Just checking in, are you working?"
]

def mock_llm_response(*args, **kwargs):
    # Simulate realistic token counts for simple queries
    p_tokens = random.randint(50, 300)
    c_tokens = random.randint(20, 150)
    
    msg = AIMessage(content="Here is a simulated response.")
    msg.usage_metadata = {"input_tokens": p_tokens, "output_tokens": c_tokens}
    return msg

@patch("langchain_openai.ChatOpenAI.invoke", side_effect=mock_llm_response)
def run_tests(mock_invoke):
    costs = []
    for idx, task in enumerate(tasks):
        state = {
            "channel": "cli",
            "user_id": "cost_test_user",
            "username": "TestUser",
            "message": task,
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
        
        res = run_brain(state)
        cost = res.get("cost_usd", 0.0)
        costs.append(cost)
        resp_snippet = (res.get("response") or "")[:50].replace('\n', ' ')
        print(f"Task {idx+1}: {cost:.6f} USD -> {resp_snippet}...")

    if costs:
        print(f"\nCost Range: ${min(costs):.6f} - ${max(costs):.6f}")
        print(f"Total Cost for 10 Tasks: ${sum(costs):.6f}")

if __name__ == "__main__":
    run_tests()
