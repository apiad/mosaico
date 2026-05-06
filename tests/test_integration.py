"""End-to-end: parse -> topo -> render -> cache -> invalidate cascade.

Three artifacts forming a chain (style-sheet -> elizabeth -> cover-01)
plus a fan-in (cover-01 also refs style-sheet directly). Verifies:

1. First run renders all three.
2. Second run skips all three (state cache hit).
3. Editing a shared template cascades and re-renders everything.
"""
import hashlib
from pathlib import Path

import pytest

from mosaico import render as render_mod


@pytest.fixture
def big_project(tmp_path: Path) -> Path:
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: enciclopedia-test
defaults:
  out_root: out
  state: state.json
templates:
  watercolor: "soft watercolor with paper texture"
  scene: "single scene, no grid. {{ templates.watercolor }}"
artifacts:
  - id: style-sheet
    prompt_template: "style sheet. {{ templates.watercolor }}"
    out: style.jpg
  - id: elizabeth
    prompt_template: "Elizabeth, 9-year-old. {{ templates.watercolor }}"
    refs:
      - {artifact: style-sheet, hint: "palette only"}
    out: chars/elizabeth.jpg
  - id: cover-01
    prompt_template: "Chapter 1 cover. {{ templates.scene }}"
    refs:
      - {artifact: elizabeth, hint: "main character"}
      - {artifact: style-sheet, hint: "palette"}
    out: chapters/01.jpg
""")
    return p


def _gen(prompt, out, refs, grid, cells, model, seed, aspect):
    """Deterministic mock generator: writes prompt-sha256 as JPEG bytes."""
    h = hashlib.sha256(prompt.encode()).digest()
    out_path = out.with_suffix(".jpg")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"\xff\xd8\xff" + h + b"\x00" * 100)
    return out_path


def test_full_cascade(big_project, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _gen)

    # First render — everything new.
    s1 = render_mod.run_render(big_project, only=None, force=None, dry_run=False)
    assert sorted(s1.rendered) == ["cover-01", "elizabeth", "style-sheet"]
    assert s1.skipped == []

    # Second render — everything cached.
    s2 = render_mod.run_render(big_project, only=None, force=None, dry_run=False)
    assert s2.rendered == []
    assert sorted(s2.skipped) == ["cover-01", "elizabeth", "style-sheet"]

    # Edit the shared watercolor template — every artifact's resolved
    # prompt changes, so the entire chain cascades.
    text = big_project.read_text().replace(
        "soft watercolor with paper texture",
        "vivid acrylic with thick brush",
    )
    big_project.write_text(text)
    s3 = render_mod.run_render(big_project, only=None, force=None, dry_run=False)
    assert sorted(s3.rendered) == ["cover-01", "elizabeth", "style-sheet"]
    assert s3.skipped == []
