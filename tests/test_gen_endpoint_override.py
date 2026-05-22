"""ENDPOINT must be overridable via MOSAICO_ENDPOINT env var."""
import importlib

from mosaico import gen as gen_mod


def test_endpoint_default(monkeypatch):
    monkeypatch.delenv("MOSAICO_ENDPOINT", raising=False)
    importlib.reload(gen_mod)
    assert gen_mod.ENDPOINT == "https://openrouter.ai/api/v1/chat/completions"


def test_endpoint_override(monkeypatch):
    monkeypatch.setenv("MOSAICO_ENDPOINT", "http://100.64.0.4:8000/v1/chat/completions")
    importlib.reload(gen_mod)
    assert gen_mod.ENDPOINT == "http://100.64.0.4:8000/v1/chat/completions"
    monkeypatch.delenv("MOSAICO_ENDPOINT", raising=False)
    importlib.reload(gen_mod)
