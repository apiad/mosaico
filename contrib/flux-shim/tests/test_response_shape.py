"""build_response: PIL.Image -> OpenAI chat-completion-shaped dict."""
import base64
from io import BytesIO

from PIL import Image

from server import build_response


def test_response_top_level_keys():
    img = Image.new("RGB", (64, 64), color="red")
    r = build_response(img, model="flux-2-klein-4b")
    assert r["object"] == "chat.completion"
    assert r["model"] == "flux-2-klein-4b"
    assert "id" in r
    assert "created" in r
    assert isinstance(r["created"], int)
    assert r["usage"] == {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0, "cost": 0.0}


def test_response_choice_structure():
    img = Image.new("RGB", (64, 64), color="red")
    r = build_response(img, model="flux-2-klein-4b")
    assert len(r["choices"]) == 1
    choice = r["choices"][0]
    assert choice["index"] == 0
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == ""


def test_response_image_url_is_data_png():
    img = Image.new("RGB", (64, 64), color="red")
    r = build_response(img, model="m")
    images = r["choices"][0]["message"]["images"]
    assert len(images) == 1
    assert images[0]["type"] == "image_url"
    url = images[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


def test_response_image_roundtrips():
    img = Image.new("RGB", (32, 32), color=(123, 45, 67))
    r = build_response(img, model="m")
    url = r["choices"][0]["message"]["images"][0]["image_url"]["url"]
    b64 = url.split(",", 1)[1]
    decoded = base64.b64decode(b64)
    roundtrip = Image.open(BytesIO(decoded))
    assert roundtrip.size == (32, 32)
    px = roundtrip.convert("RGB").getpixel((0, 0))
    assert px == (123, 45, 67)
