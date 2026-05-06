"""mosaico gen — prompt -> image via OpenRouter (low-level primitive).

Optional --grid + auto-cut. Both Pattern A (cut into pieces) and Pattern B
(keep the whole sheet) are served by this single command.

OpenRouter token discovery (in order):
  1. $OPENROUTER_API_KEY environment variable.
  2. The token file at $MOSAICO_TOKEN_FILE if set.
  3. $CLAUDE_TOOLKIT_WORKSPACE/.claude/openrouter.token (when invoked
     under claude-toolkit, which sets that env var before dispatching).

Discoverability:
    mosaico gen --tour                       # show happy path + failure modes
    mosaico gen "<prompt>"                   # plan-only without --save
    mosaico gen "<prompt>" --save --out path.jpg
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Annotated

import microcli as m

from . import app
from .cropper import cut_grid


def _default_token_file() -> Path | None:
    """Resolve the optional fallback token file path.

    `MOSAICO_TOKEN_FILE` wins; otherwise fall back to
    `$CLAUDE_TOOLKIT_WORKSPACE/.claude/openrouter.token` so claude-toolkit
    can dispatch to mosaico without needing to thread a flag through.
    """
    explicit = os.environ.get("MOSAICO_TOKEN_FILE")
    if explicit:
        return Path(explicit)
    workspace = os.environ.get("CLAUDE_TOOLKIT_WORKSPACE")
    if workspace:
        return Path(workspace) / ".claude" / "openrouter.token"
    return None


TOKEN_FILE = _default_token_file()
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-3.1-flash-image-preview"


def load_token() -> str:
    env_key = os.environ.get("OPENROUTER_API_KEY")
    if env_key:
        return env_key.strip()
    if TOKEN_FILE and TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    m.fail(
        "OpenRouter token not found. Set $OPENROUTER_API_KEY, or point "
        "$MOSAICO_TOKEN_FILE at a key file. "
        "See `mosaico gen --tour` for the full setup."
    )
    return ""  # unreachable


def encode_image(path: Path) -> str:
    if not path.exists():
        m.fail(
            f"reference image not found: {path}. "
            f"Check `--ref` paths are correct relative to your CWD."
        )
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_content(prompt: str, refs: list[Path]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": prompt}]
    for ref in refs:
        content.append({"type": "image_url",
                        "image_url": {"url": encode_image(ref)}})
    return content


def call_openrouter(token: str, model: str, prompt: str, refs: list[Path]) -> dict:
    """HTTP call to OpenRouter. Imported lazily to keep test isolation cheap."""
    import httpx
    # max_tokens cap: OpenRouter reserves credit at the request's token
    # ceiling. Default ~32K can hit "Payment Required" on tight budgets even
    # though image gen is priced per image. 4096 fits a base64 image + caption.
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_content(prompt, refs)}],
        "modalities": ["image", "text"],
        "max_tokens": 4096,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/apiad/workspace",
        "X-Title": "mosaico gen",
    }
    with httpx.Client(timeout=180) as client:
        r = client.post(ENDPOINT, headers=headers, json=payload)
        if r.status_code >= 400:
            m.fail(
                f"OpenRouter HTTP {r.status_code}: {r.text[:500]}. "
                f"Common fixes: check token in {TOKEN_FILE}, retry on 429, "
                f"verify model slug `{model}`. "
                f"Run `mosaico gen --tour` for the full happy path."
            )
        return r.json()


def extract_image(resp: dict) -> bytes:
    msg = resp["choices"][0]["message"]
    for img in (msg.get("images") or []):
        url = img.get("image_url", {}).get("url", "")
        if url.startswith("data:"):
            _, b64 = url.split(",", 1)
            return base64.b64decode(b64)
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if block.get("type") in ("image", "output_image"):
                url = (block.get("image_url", {}).get("url")
                       or block.get("source", {}).get("data"))
                if url and url.startswith("data:"):
                    _, b64 = url.split(",", 1)
                    return base64.b64decode(b64)
                if url:
                    return base64.b64decode(url)
    m.fail(
        f"no image found in OpenRouter response. First 2KB of payload: "
        f"{json.dumps(resp, indent=2)[:2000]}. "
        f"This usually means the model returned an apology instead of an image; "
        f"shorten prompt or change model."
    )
    raise SystemExit(2)


def detect_extension(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    return ".bin"


def run_gen(
    prompt: str,
    out: Path,
    refs: list[Path],
    grid: tuple[int, int] | None,
    cells: dict[str, dict] | None,
    model: str | None,
    seed: int | None,
    aspect: str | None,
) -> Path:
    """Pure function: do the gen. Returns the resolved out path.

    `cells`, when provided with a grid, is the explicit slug -> {row, col,
    rowspan?, colspan?} mapping passed straight to the cropper. When None
    with a grid, the cropper falls back to its default `cell-rR-cC` naming.
    The flat-list ergonomic form (CLI's `--cell-names`) is converted to this
    dict shape at the call site (see `gen()` CLI below).
    """
    # Validate refs eagerly so a missing path fails before the API call.
    for r in refs:
        if not Path(r).exists():
            m.fail(
                f"reference image not found: {r}. "
                f"Check `--ref` paths are correct relative to your CWD."
            )
    token = load_token()
    actual_prompt = prompt
    if aspect:
        actual_prompt = f"{aspect} aspect: {prompt}"
    t0 = time.time()
    resp = call_openrouter(token, model or DEFAULT_MODEL, actual_prompt, refs)
    elapsed = time.time() - t0
    img = extract_image(resp)

    actual_ext = detect_extension(img)
    out_path = out.with_suffix(actual_ext) if out.suffix.lower() != actual_ext else out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img)

    cost = (resp.get("usage") or {}).get("cost")
    print(f"wrote {out_path} ({len(img)} bytes) in {elapsed:.1f}s  cost=${cost}",
          file=sys.stderr)

    if grid is not None:
        cells_dir = out_path.parent / out_path.stem / "cells"
        cut_grid(out_path, cells_dir, grid=grid, cells=cells)

    return out_path


@app.command
def gen(
    prompt: Annotated[str, "Text prompt for the image"],
    out: Annotated[str, "Output file path (extension auto-corrected)"] = "image.jpg",
    ref: Annotated[str, "Reference image path(s), comma-separated"] = "",
    model: Annotated[str, "OpenRouter model slug"] = DEFAULT_MODEL,
    seed: Annotated[int, "Seed (passed through; seedable models only)"] = 0,
    aspect: Annotated[str, "Aspect ratio baked into prompt (16:9, 9:16, 1:1, ...)"] = "",
    grid: Annotated[str, "Grid layout RxC (e.g. 3x3) for sheet + auto-cut"] = "",
    cell_names: Annotated[str, "Comma-separated cell names (default cell-rR-cC)"] = "",
    save: Annotated[bool, "Actually call the API (without --save, only validates)"] = False,
):
    """Generate one image from a prompt via OpenRouter.

    Without --save: validates inputs and prints what would happen.
    With --save: calls the API and writes the file.

    With --grid RxC: generates a sheet AND cuts it into per-cell files at
    <out-stem>/cells/. Both happy paths (Pattern A: care about cells;
    Pattern B: keep whole sheet) are served — `gen` always emits the sheet,
    cells are a side effect.
    """
    refs = [Path(p.strip()) for p in ref.split(",") if p.strip()] if ref else []
    grid_tuple: tuple[int, int] | None = None
    if grid:
        try:
            r, c = grid.lower().split("x")
            grid_tuple = (int(r), int(c))
        except ValueError:
            m.fail(
                f"invalid --grid `{grid}`; expected `RxC` like `3x3`. "
                f"Run `mosaico gen --tour` for examples."
            )
    cell_names_list = (
        [n.strip() for n in cell_names.split(",") if n.strip()]
        if cell_names else None
    )

    cells_map: dict[str, dict] | None = None
    if cell_names_list:
        if grid_tuple is None:
            m.fail(
                "--cell-names requires --grid. "
                "Run `mosaico gen --tour` for examples."
            )
        rows, cols = grid_tuple
        if len(cell_names_list) != rows * cols:
            m.fail(
                f"--cell-names has {len(cell_names_list)} entries but grid "
                f"{rows}x{cols} expects {rows * cols}. "
                f"Either drop --cell-names (defaults to cell-rR-cC) or "
                f"match the count exactly. "
                f"See `mosaico gen --tour`."
            )
        cells_map = {
            name: {"row": i // cols, "col": i % cols}
            for i, name in enumerate(cell_names_list)
        }

    if not save:
        m.info(f"Draft: would generate {grid_tuple or '1 image'} from prompt "
               f"({len(prompt)} chars), {len(refs)} ref(s), model={model}")
        m.info(f"Output -> {out} (ext auto-corrected)")
        m.info(f"Rerun with --save to actually call the API.")
        return

    run_gen(
        prompt=prompt,
        out=Path(out),
        refs=refs,
        grid=grid_tuple,
        cells=cells_map,
        model=model or None,
        seed=seed or None,
        aspect=aspect or None,
    )
    m.ok(f"image generated: {out}")
