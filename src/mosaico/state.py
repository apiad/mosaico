"""Content-addressed cache state for image-render.

`input_hash` is sha256 of canonical JSON of:
    {
      "resolved_prompt": "...",
      "model": "...", "seed": int, "aspect": "4:3",
      "grid": [r,c] or null, "cells_spec": {...} or null,
      "ref_hashes": [{"artifact": id, "hint": str, "out_hash": str}, ...]
                                                or
                    [{"path": str, "hint": str, "file_hash": str}, ...]
    }

Two artifacts with identical prose but different ref hints hash differently
and re-render independently. An upstream re-render changes its
`output_hash`, which changes downstream `input_hash`, cascading correctly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    """Return `sha256:<hex>` of the file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def compute_input_hash(inputs: dict[str, Any]) -> str:
    """sha256 of `inputs` serialized as canonical JSON (sort_keys, no spaces)."""
    payload = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{h}"


def load_state(path: Path) -> dict[str, Any]:
    """Load state file; return `{"artifacts": {}}` if missing or corrupt."""
    if not path.exists():
        return {"artifacts": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"artifacts": {}}
    if "artifacts" not in data:
        data["artifacts"] = {}
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Write state atomically (parent dirs created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)
