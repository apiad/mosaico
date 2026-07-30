"""Cut pieces can land where the consumer needs them, and heal if they vanish.

Pattern A — the cells ARE the deliverable and something downstream reads them
from a fixed path — needs two things the default `<out-stem>/cells/` shape
doesn't give: a configurable destination, and repair. Cutting costs no API
call, so a sheet that is up to date but has lost its pieces is fixable for
free; without that, a stale cache silently ships a build with missing files.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from mosaico.render import _cells_dir, _missing_cells
from mosaico.schema import SchemaError, parse_project


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n")
    return p


def _sheet(path: Path, rows: int = 2, cols: int = 2) -> Path:
    """A white sheet with one dark blob centred in every cell."""
    h, w = rows * 100, cols * 100
    arr = np.full((h, w, 3), 255, dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            cy, cx = r * 100 + 50, c * 100 + 50
            arr[cy - 20:cy + 20, cx - 20:cx + 20] = 30
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(path)
    return path


def _project(tmp_path: Path, cells_out: str | None) -> Path:
    line = f"    cells_out: {cells_out}\n" if cells_out else ""
    return _write(tmp_path / "p.yml", f"""
version: 1
name: p
defaults:
  out_root: .
  state: .mosaico/p.json
artifacts:
  - id: sheet
    prompt_template: "a grid"
    out: img/sheet.jpg
    grid: [2, 2]
    cells:
      alpha: {{row: 0, col: 0}}
      beta: {{row: 0, col: 1}}
      gamma: {{row: 1, col: 0}}
      delta: {{row: 1, col: 1}}
{line}""")


def test_default_cells_dir_is_alongside_the_sheet(tmp_path: Path):
    proj = parse_project(_project(tmp_path, None))
    art = proj.artifacts[0]
    written = proj.out_root / art.out
    assert _cells_dir(art, written, proj) == written.parent / "sheet" / "cells"


def test_cells_out_redirects_the_pieces(tmp_path: Path):
    proj = parse_project(_project(tmp_path, "img/glosario"))
    art = proj.artifacts[0]
    written = proj.out_root / art.out
    assert _cells_dir(art, written, proj) == proj.out_root / "img" / "glosario"


def test_cells_out_is_relative_to_out_root_not_the_sheet(tmp_path: Path):
    """`out:` is out_root-relative; `cells_out:` has to match or it surprises."""
    proj = parse_project(_project(tmp_path, "elsewhere/cut"))
    art = proj.artifacts[0]
    written = proj.out_root / art.out
    resolved = _cells_dir(art, written, proj)
    assert resolved == proj.out_root / "elsewhere" / "cut"
    assert written.parent not in resolved.parents


def test_cells_out_without_grid_is_rejected(tmp_path: Path):
    p = _write(tmp_path / "bad.yml", """
version: 1
name: bad
defaults:
  out_root: .
  state: .mosaico/bad.json
artifacts:
  - id: sheet
    prompt_template: "a grid"
    out: img/sheet.jpg
    cells_out: img/glosario
""")
    with pytest.raises(SchemaError, match="needs `grid:`"):
        parse_project(p)


def test_empty_cells_out_is_rejected(tmp_path: Path):
    with pytest.raises(SchemaError, match="non-empty"):
        parse_project(_project(tmp_path, '"  "'))


def test_missing_cells_reports_every_absent_slug(tmp_path: Path):
    proj = parse_project(_project(tmp_path, "img/glosario"))
    art = proj.artifacts[0]
    written = _sheet(proj.out_root / art.out)
    assert sorted(_missing_cells(art, written, proj)) == [
        "alpha", "beta", "delta", "gamma",
    ]

    cdir = _cells_dir(art, written, proj)
    cdir.mkdir(parents=True)
    for slug in ("alpha", "beta", "gamma"):
        Image.new("RGB", (10, 10)).save(cdir / f"{slug}.jpg")
    assert _missing_cells(art, written, proj) == ["delta"]

    Image.new("RGB", (10, 10)).save(cdir / "delta.jpg")
    assert _missing_cells(art, written, proj) == []


def test_missing_cells_is_empty_without_declared_cells(tmp_path: Path):
    """A grid with no `cells:` gets default names — nothing to check against."""
    p = _write(tmp_path / "g.yml", """
version: 1
name: g
defaults:
  out_root: .
  state: .mosaico/g.json
artifacts:
  - id: sheet
    prompt_template: "a grid"
    out: img/sheet.jpg
    grid: [2, 2]
""")
    proj = parse_project(p)
    art = proj.artifacts[0]
    assert _missing_cells(art, proj.out_root / art.out, proj) == []


def test_recut_writes_the_declared_slugs_at_cells_out(tmp_path: Path):
    """The repair path end to end: cut_grid fills exactly what was missing."""
    from mosaico.cropper import cut_grid

    proj = parse_project(_project(tmp_path, "img/glosario"))
    art = proj.artifacts[0]
    written = _sheet(proj.out_root / art.out)

    cut_grid(written, _cells_dir(art, written, proj), grid=art.grid, cells=art.cells)

    assert _missing_cells(art, written, proj) == []
    assert not (written.parent / "sheet" / "cells").exists()


def _exploding_gen(*a, **kw):
    raise AssertionError("cutting must never trigger an API render")


def test_cache_hit_repairs_missing_cells_without_rendering(
    tmp_path: Path, monkeypatch
):
    """The failure this exists to prevent: sheet cached, pieces gone, build
    breaks on a file the cache swears is up to date."""
    from mosaico import render as render_mod

    monkeypatch.setattr(render_mod, "run_gen", _exploding_gen)
    yml = _project(tmp_path, "img/glosario")
    proj = parse_project(yml)
    art = proj.artifacts[0]
    written = _sheet(proj.out_root / art.out)

    # anchor the existing sheet, which also performs the first cut
    boot = render_mod.run_render(yml, only=None, force=None, dry_run=False,
                                 bootstrap=True)
    assert boot.anchored == ["sheet"]
    assert _missing_cells(art, written, proj) == []

    # lose two pieces, then re-run normally: cache hit, cut restored
    for slug in ("beta", "delta"):
        (_cells_dir(art, written, proj) / f"{slug}.jpg").unlink()

    summary = render_mod.run_render(yml, only=None, force=None, dry_run=False)
    assert summary.skipped == ["sheet"]
    assert summary.recut == ["sheet"]
    assert _missing_cells(art, written, proj) == []


def test_dry_run_never_cuts(tmp_path: Path, monkeypatch):
    from mosaico import render as render_mod

    monkeypatch.setattr(render_mod, "run_gen", _exploding_gen)
    yml = _project(tmp_path, "img/glosario")
    proj = parse_project(yml)
    art = proj.artifacts[0]
    written = _sheet(proj.out_root / art.out)

    render_mod.run_render(yml, only=None, force=None, dry_run=True, bootstrap=True)
    assert len(_missing_cells(art, written, proj)) == 4
