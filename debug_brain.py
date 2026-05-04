import os
import sys
from dotenv import load_dotenv

# Ensure core is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.brain import run_brain
from core.state import AgentState

load_dotenv()

def test():
    state: AgentState = {
        "channel": "cli",
        "user_id": "test_user",
        "username": "tester",
        "message": "What is the weather in Islamabad today?",
        "history": [],
        "tool_results": [],
        "metadata": {}
    }
    
    print("Sending message...")
    try:
        final_state = run_brain(state)
        print("\n=== FINAL STATE ===")
        print("Response:", final_state.get("response"))
        print("Force Respond:", final_state.get("metadata", {}).get("force_respond"))
        print("Tool Results Count:", len(final_state.get("tool_results", [])))
        
        for idx, res in enumerate(final_state.get("tool_results", [])):
            print(f"\nTool Result {idx}:")
            if hasattr(res, "content"):
                print("Content:", res.content[:200])
            if hasattr(res, "tool_calls"):
                print("Tool Calls:", res.tool_calls)
    except Exception as e:
        print("EXCEPTION:", str(e))

if __name__ == "__main__":
    test()
