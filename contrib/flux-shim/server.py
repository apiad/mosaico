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
