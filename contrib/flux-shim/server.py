"""flux-shim: OpenAI-compatible chat-completions server for FLUX.2 klein-4B.

Implements POST /v1/chat/completions only. Other endpoints return 404.

Spec: vault/Atlas/Architecture/2026-05-22-flux-shim-for-mosaico-design.md
"""
from __future__ import annotations

import os
import sys
import time
import uuid
import asyncio
import base64
from io import BytesIO
from typing import Literal

from PIL import Image


# -------------------------------------------------------------------- size

class SizeError(ValueError):
    """Raised when a 'size' field is malformed or out of range."""


DEFAULT_SIZE: tuple[int, int] = (1024, 1024)
DIM_STRIDE = 32
DIM_MIN = 256
DIM_MAX = 2048
MAX_PIXELS = 2_097_152  # ~2M px


def parse_size(size: str | None) -> tuple[int, int]:
    """Parse 'WxH' size string. Returns (width, height) or raises SizeError.

    Defaults to (1024, 1024) when size is None.
    """
    if size is None:
        return DEFAULT_SIZE
    if not isinstance(size, str) or "x" not in size:
        raise SizeError(f"size must be 'WxH', got {size!r}")
    parts = size.split("x")
    if len(parts) != 2:
        raise SizeError(f"size must be 'WxH', got {size!r}")
    try:
        w = int(parts[0])
        h = int(parts[1])
    except ValueError as e:
        raise SizeError(f"size must be 'WxH' with integer dimensions, got {size!r}") from e
    if w % DIM_STRIDE != 0 or h % DIM_STRIDE != 0:
        raise SizeError(f"size dimensions must be multiples of 32, got {w}x{h}")
    if w < DIM_MIN or h < DIM_MIN:
        raise SizeError(f"size must be between {DIM_MIN} and {DIM_MAX}, got {w}x{h}")
    if w > DIM_MAX or h > DIM_MAX:
        raise SizeError(f"size must be between {DIM_MIN} and {DIM_MAX}, got {w}x{h}")
    if w * h > MAX_PIXELS:
        raise SizeError(f"total pixels {w * h} exceeds 2M ({MAX_PIXELS})")
    return (w, h)


# ----------------------------------------------------------------- content

class ContentError(ValueError):
    """Raised when a content block is malformed or unsupported."""


def _decode_data_url(url: str) -> bytes:
    if not url.startswith("data:"):
        raise ContentError(f"only data: image URLs supported, got {url[:40]!r}")
    try:
        _header, b64 = url.split(",", 1)
    except ValueError as e:
        raise ContentError(f"data URL missing comma separator: {url[:40]!r}") from e
    try:
        return base64.b64decode(b64, validate=True)
    except Exception as e:
        raise ContentError(f"image_url payload could not be decoded as base64: {e}") from e


def parse_content(blocks: list[dict]) -> tuple[str, list[Image.Image]]:
    """Flatten OpenAI-style content blocks into (prompt, refs).

    - Text blocks are joined with single spaces, in order.
    - image_url blocks are decoded as PIL.Image (must be data: URLs).
    - Unknown block types are silently ignored (forward-compat).
    """
    if not isinstance(blocks, list):
        raise ContentError(f"content must be a list of blocks, got {type(blocks).__name__}")

    texts: list[str] = []
    refs: list[Image.Image] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            texts.append(str(block.get("text", "")))
        elif btype == "image_url":
            url = block.get("image_url", {}).get("url", "")
            data = _decode_data_url(url)
            try:
                img = Image.open(BytesIO(data))
                img.load()
            except Exception as e:
                raise ContentError(f"reference image not a recognized format: {e}") from e
            refs.append(img.convert("RGB"))
        # else: ignore (forward-compat)

    prompt = " ".join(t for t in texts if t)
    return (prompt, refs)


# ---------------------------------------------------------------- response

def _png_data_url(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_response(img: Image.Image, model: str) -> dict:
    """Wrap a PIL image into mosaico's expected chat-completion response shape."""
    return {
        "id": f"flux-shim-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "",
                "images": [{
                    "type": "image_url",
                    "image_url": {"url": _png_data_url(img)},
                }],
            },
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
        },
    }


# ----------------------------------------------------------------- fastapi

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# PIPELINE is a callable: (prompt, image, width, height, guidance_scale,
# num_inference_steps, generator) -> object with .images attribute.
# At import time we set this to None; the __main__ block below loads the
# real Flux2KleinPipeline. Tests overwrite this via monkeypatch.
PIPELINE = None

_pipeline_lock = asyncio.Lock()

app = FastAPI(title="flux-shim", version="0.1.0")


def _error_json(status: int, message: str, kind: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "error": {"message": message, "type": kind},
    })


@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        return _error_json(400, f"request body must be valid JSON: {e}")

    if not isinstance(body, dict):
        return _error_json(400, "request body must be a JSON object")

    model = body.get("model", "flux-2-klein-4b")
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        return _error_json(400, "messages required")

    content = messages[0].get("content")
    if not isinstance(content, list):
        return _error_json(400, "messages[0].content must be a list of blocks")

    try:
        prompt, refs = parse_content(content)
    except ContentError as e:
        return _error_json(400, str(e))

    try:
        width, height = parse_size(body.get("size"))
    except SizeError as e:
        return _error_json(400, str(e))

    pipeline = PIPELINE
    if pipeline is None:
        return _error_json(503, "pipeline not loaded; check server startup logs",
                           kind="server_error")

    refs_resized = [r.resize((width, height), Image.LANCZOS) for r in refs] if refs else None

    try:
        async with _pipeline_lock:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pipeline(
                    prompt=prompt,
                    image=refs_resized,
                    width=width,
                    height=height,
                    guidance_scale=1.0,
                    num_inference_steps=4,
                    generator=None,
                ),
            )
    except Exception as e:
        ename = type(e).__name__
        if "OutOfMemory" in ename:
            return _error_json(503, "GPU OOM — try smaller size or unload other models",
                               kind="server_error")
        print(f"[flux-shim] pipeline error: {ename}: {e}", file=sys.stderr)
        return _error_json(500, f"pipeline error: {ename}", kind="server_error")

    out_img = result.images[0]
    return build_response(out_img, model=model)
