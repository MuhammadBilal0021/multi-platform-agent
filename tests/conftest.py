import os
import tempfile
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.update(OMNI_DATA_DIR=tempfile.mkdtemp(prefix="omni-tests-"),
    OPENROUTER_API_KEY="test-not-a-key",TAVILY_API_KEY="test-not-a-key",
    MAX_REQUESTS_PER_HOUR="10000", PYTHON_DOTENV_DISABLED="1")
import pytest
@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    import tavily
    import httpx
    import requests
    monkeypatch.setattr(tavily.TavilyClient,"search",lambda *a,**k:{"results":[]})
    def blocked(*a,**k): raise AssertionError("Unexpected network request in offline test")
    monkeypatch.setattr(httpx.HTTPTransport,"handle_request",blocked)
    monkeypatch.setattr(requests.sessions.Session,"request",blocked)
