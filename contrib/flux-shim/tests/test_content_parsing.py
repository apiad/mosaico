"""parse_content: list of OpenAI content blocks -> (prompt, refs)."""
import base64
from io import BytesIO

import pytest
from PIL import Image

from server import parse_content, ContentError


def _data_url(img: Image.Image, fmt: str = "PNG") -> str:
    buf = BytesIO()
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def test_text_only():
    prompt, refs = parse_content([{"type": "text", "text": "a heron"}])
    assert prompt == "a heron"
    assert refs == []


def test_multiple_text_blocks_concatenated():
    prompt, refs = parse_content([
        {"type": "text", "text": "first part"},
        {"type": "text", "text": "second part"},
    ])
    assert prompt == "first part second part"
    assert refs == []


def test_text_with_one_ref():
    img = Image.new("RGB", (256, 256), color="red")
    blocks = [
        {"type": "text", "text": "scene"},
        {"type": "image_url", "image_url": {"url": _data_url(img)}},
    ]
    prompt, refs = parse_content(blocks)
    assert prompt == "scene"
    assert len(refs) == 1
    assert refs[0].size == (256, 256)
    assert refs[0].mode == "RGB"


def test_text_with_multiple_refs_in_order():
    img1 = Image.new("RGB", (128, 128), color="red")
    img2 = Image.new("RGB", (256, 256), color="green")
    img3 = Image.new("RGB", (64, 64), color="blue")
    blocks = [
        {"type": "text", "text": "p"},
        {"type": "image_url", "image_url": {"url": _data_url(img1)}},
        {"type": "image_url", "image_url": {"url": _data_url(img2)}},
        {"type": "image_url", "image_url": {"url": _data_url(img3)}},
    ]
    prompt, refs = parse_content(blocks)
    assert prompt == "p"
    assert [r.size for r in refs] == [(128, 128), (256, 256), (64, 64)]


def test_rejects_non_data_url():
    blocks = [
        {"type": "text", "text": "p"},
        {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}},
    ]
    with pytest.raises(ContentError, match="data:"):
        parse_content(blocks)


def test_rejects_unparseable_image():
    blocks = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,!!!not-base64!!!"}},
    ]
    with pytest.raises(ContentError, match="base64"):
        parse_content(blocks)


def test_rejects_unknown_block_type_silently_ignored_when_strict_false():
    # Unknown types are ignored, not errors.
    blocks = [
        {"type": "text", "text": "hi"},
        {"type": "fancy", "fancy_data": "blah"},
    ]
    prompt, refs = parse_content(blocks)
    assert prompt == "hi"
    assert refs == []
