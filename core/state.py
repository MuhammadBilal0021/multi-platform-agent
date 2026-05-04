from typing import TypedDict, List, Dict, Any, Optional

class AgentState(TypedDict):
    """
    The universal data structure passed between all nodes in the LangGraph brain.
    No matter what platform (Discord, Slack, Twitter) a message comes from, 
    it is translated into this format by the adapter before hitting the brain.
    """
    channel:      str                   # E.g., 'discord', 'slack', 'twitter', 'email', 'cli'
    user_id:      str                   # Unique user identifier (e.g., Discord ID, email address)
    username:     str                   # Human-readable name
    message:      str                   # The raw incoming text from the user
    history:      List[Dict[str, Any]]  # List of past messages for context [{role: 'user', content: '...'}]
    tool_results: List[Any]             # Results from any tools called during the reasoning cycle
    response:     Optional[str]         # The final string the agent wants to send back
    metadata:     Dict[str, Any]        # Any extra platform-specific data (e.g., thread_ts for Slack)
