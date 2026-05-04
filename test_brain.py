import os
from dotenv import load_dotenv

# 1. Load the environment variables (this reads the GROQ_API_KEY from your .env file)
load_dotenv()

# 2. Import the brain we just built
from core.brain import run_brain

def main():
    print("🧠 Booting up the LangGraph Brain...\n")
    
    # 3. Create a dummy state that mimics what Discord or Slack would send
    dummy_state = {
        "channel": "cli",
        "user_id": "test_user_01",
        "username": "Bilal",
        "message": "What is the latest major news regarding LangChain or LangGraph today? Search the web and give me a brief summary.",
        "history": [],
        "tool_results": [],
        "metadata": {}
    }
    
    print(f"📨 Sending Message from {dummy_state['username']} on channel: {dummy_state['channel']}")
    print(f"> \"{dummy_state['message']}\"")
    print("-" * 50)
    
    # 4. Feed the dummy state into the brain
    try:
        final_state = run_brain(dummy_state)
        
        print("\n🤖 Agent's Final Response:")
        print(final_state.get("response", "Error: No response was generated."))
    except Exception as e:
        print(f"\n❌ Error running brain: {str(e)}")

if __name__ == "__main__":
    main()
