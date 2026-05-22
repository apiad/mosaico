"""POST /v1/chat/completions — endpoint integration (pipeline mocked)."""
import base64
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import server


@pytest.fixture
def client(monkeypatch):
    """Replace the module-level pipeline with a stub that records call kwargs."""
    captured = {}

    def fake_pipe(prompt, image=None, width=1024, height=1024,
                  guidance_scale=1.0, num_inference_steps=4, generator=None):
        captured["prompt"] = prompt
        captured["image"] = image
        captured["width"] = width
        captured["height"] = height
        out = Image.new("RGB", (width, height), color="green")
        result = MagicMock()
        result.images = [out]
        return result

    monkeypatch.setattr(server, "PIPELINE", fake_pipe)
    c = TestClient(server.app)
    c.captured = captured
    return c


def test_text_only_t2i(client):
    r = client.post("/v1/chat/completions", json={
        "model": "flux-2-klein-4b",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "a heron at dawn"},
        ]}],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["images"][0]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert client.captured["prompt"] == "a heron at dawn"
    assert client.captured["image"] is None
    assert (client.captured["width"], client.captured["height"]) == (1024, 1024)


def test_t2i_with_size(client):
    r = client.post("/v1/chat/completions", json={
        "model": "flux-2-klein-4b",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "a heron"},
        ]}],
        "size": "1344x768",
    })
    assert r.status_code == 200
    assert (client.captured["width"], client.captured["height"]) == (1344, 768)


def test_with_one_ref(client):
    img = Image.new("RGB", (300, 400), color="red")
    buf = BytesIO(); img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    r = client.post("/v1/chat/completions", json={
        "model": "flux-2-klein-4b",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "scene"},
            {"type": "image_url", "image_url": {
                "url": f"data:image/png;base64,{b64}"
            }},
        ]}],
        "size": "1024x1024",
    })
    assert r.status_code == 200
    assert client.captured["image"] is not None
    assert len(client.captured["image"]) == 1
    assert client.captured["image"][0].size == (1024, 1024)


def test_with_multiple_refs(client):
    refs = []
    for color in ["red", "green", "blue"]:
        img = Image.new("RGB", (256, 256), color=color)
        buf = BytesIO(); img.save(buf, format="PNG")
        refs.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"}
        })

    r = client.post("/v1/chat/completions", json={
        "model": "flux-2-klein-4b",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "three colors"},
            *refs,
        ]}],
    })
    assert r.status_code == 200
    assert len(client.captured["image"]) == 3


def test_unknown_route_404(client):
    r = client.get("/v1/models")
    assert r.status_code == 404
