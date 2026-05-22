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
