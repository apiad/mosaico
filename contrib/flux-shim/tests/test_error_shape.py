"""All error responses must match {"error": {"message": str, "type": str}}."""
from fastapi.testclient import TestClient

import server


def _client():
    return TestClient(server.app)


def test_missing_messages():
    r = _client().post("/v1/chat/completions", json={"model": "m"})
    assert r.status_code == 400
    body = r.json()
    assert "error" in body
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["type"] == "invalid_request_error"
    assert "messages" in body["error"]["message"]


def test_content_not_list():
    r = _client().post("/v1/chat/completions", json={
        "model": "m",
        "messages": [{"role": "user", "content": "plain string"}],
    })
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"


def test_bad_size():
    r = _client().post("/v1/chat/completions", json={
        "model": "m",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "p"},
        ]}],
        "size": "128x128",
    })
    assert r.status_code == 400
    assert "between 256" in r.json()["error"]["message"]


def test_non_data_url():
    r = _client().post("/v1/chat/completions", json={
        "model": "m",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "p"},
            {"type": "image_url", "image_url": {"url": "https://nope/x.png"}},
        ]}],
    })
    assert r.status_code == 400
    assert "data:" in r.json()["error"]["message"]


def test_non_json_body():
    r = _client().post("/v1/chat/completions", data="not json",
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert "JSON" in r.json()["error"]["message"]
