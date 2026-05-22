"""When --aspect is set, the request payload must include 'size': 'WxH'."""
import base64
import json
from pathlib import Path

import httpx
import pytest

from mosaico import gen as gen_mod


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

_OriginalClient = httpx.Client


def _make_mock_transport(captured: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read()
        b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        return httpx.Response(200, json={
            "choices": [{"message": {"images": [
                {"image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]}}],
            "usage": {"cost": 0.0},
        })
    return httpx.MockTransport(handler)


def _install_mock(monkeypatch, captured: dict) -> None:
    transport = _make_mock_transport(captured)

    def fake_client(*args, **kwargs):
        return _OriginalClient(transport=transport, timeout=180)

    monkeypatch.setattr(httpx, "Client", fake_client)
    monkeypatch.setattr(gen_mod, "load_token", lambda: "T")


def test_payload_includes_size_when_aspect_set(tmp_path, monkeypatch):
    captured: dict = {}
    _install_mock(monkeypatch, captured)

    out = tmp_path / "out.png"
    gen_mod.run_gen(
        prompt="hello", out=out, refs=[], grid=None, cells=None,
        model="m", seed=None, aspect="16:9",
    )

    payload = json.loads(captured["payload"])
    assert payload.get("size") == "1376x768", (
        f"payload missing size or wrong value: {payload.get('size')!r}"
    )


def test_payload_omits_size_when_aspect_not_set(tmp_path, monkeypatch):
    captured: dict = {}
    _install_mock(monkeypatch, captured)

    out = tmp_path / "out.png"
    gen_mod.run_gen(
        prompt="hello", out=out, refs=[], grid=None, cells=None,
        model="m", seed=None, aspect=None,
    )

    payload = json.loads(captured["payload"])
    assert "size" not in payload, (
        f"payload should omit size when no aspect, got {payload.get('size')!r}"
    )
