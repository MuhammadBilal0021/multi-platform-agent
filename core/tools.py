# =============================================================================
# core/tools.py  —  Tools available to the LangGraph Brain
# Add new tools here and they become available to ALL platform adapters
# =============================================================================

import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from langchain_core.tools import tool
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("omniagent.tools")

# Tavily client for web search
tavily_client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))


# -----------------------------------------------------------------------------
# TOOL 1: WEB SEARCH
# -----------------------------------------------------------------------------
@tool
def web_search(query: str) -> str:
    """
    Search the internet for real-time information, news, weather, or facts.
    Always use this tool if you are asked about recent events or things you don't know.
    """
    try:
        response = tavily_client.search(query=query, search_depth="basic")
        results = response.get("results", [])
        if not results:
            return "No internet results found for that query."

        formatted_results = "\n".join(
            [f"- {res['title']}: {res['content']}" for res in results]
        )
        logger.info(f"web_search: '{query}' returned {len(results)} results")
        return formatted_results

    except Exception as e:
        logger.error(f"web_search failed: {e}")
        return f"Error executing web search: {str(e)}"


# -----------------------------------------------------------------------------
# TOOL 2: GET CURRENT TIME
# -----------------------------------------------------------------------------
@tool
def get_time(timezone: str = "UTC") -> str:
    """
    Get the current date and time. Use this when someone asks what time it is,
    what today's date is, or anything related to the current moment.
    Common timezones: 'UTC', 'US/Eastern', 'US/Pacific', 'Europe/London', 'Asia/Karachi'.
    """
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        result = now.strftime(f"%A, %B %d, %Y at %I:%M %p ({timezone})")
        logger.info(f"get_time: {timezone} → {result}")
        return result
    except Exception as e:
        logger.error(f"get_time failed for timezone '{timezone}': {e}")
        return f"Could not get time for timezone '{timezone}': {str(e)}. Try 'UTC' or 'Asia/Karachi'."


# -----------------------------------------------------------------------------
# TOOL 3: SUMMARIZE URL
# -----------------------------------------------------------------------------
@tool
def summarize_url(url: str) -> str:
    """
    Fetch the text content of a webpage and return a summary.
    Use this when someone shares a link and asks you to read or summarize it.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; OmniAgent/1.0)"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        # Extract text — strip HTML tags with a simple approach
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text_parts = []
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "nav", "footer", "header"):
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in ("script", "style", "nav", "footer", "header"):
                    self._skip = False

            def handle_data(self, data):
                if not self._skip:
                    cleaned = data.strip()
                    if cleaned:
                        self.text_parts.append(cleaned)

        extractor = TextExtractor()
        extractor.feed(resp.text)
        full_text = " ".join(extractor.text_parts)

        # Truncate to ~3000 chars so it fits in the LLM context
        if len(full_text) > 3000:
            full_text = full_text[:3000] + "... [truncated]"

        logger.info(f"summarize_url: fetched {len(full_text)} chars from {url}")
        return f"Content from {url}:\n\n{full_text}"

    except Exception as e:
        logger.error(f"summarize_url failed for '{url}': {e}")
        return f"Error fetching URL: {str(e)}"


# =============================================================================
# TOOL REGISTRY — add new tools to this list to make them available
# =============================================================================
available_tools = [web_search, get_time, summarize_url]
