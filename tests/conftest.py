# tests/conftest.py
import pytest


@pytest.fixture(autouse=True)
def _isolate_cloud_env(monkeypatch):
    """Tests never reach real Gemini/Vertex, even on Cloud Build where credentials exist."""
    for var in ("GOOGLE_CLOUD_PROJECT", "GEMINI_BACKEND", "GEMINI_API_KEY", "GEMINI_MODEL", "FOG_API_KEY"):
        monkeypatch.delenv(var, raising=False)
