"""Cropper: verbatim port of cut-glosario."""
import numpy as np
from pathlib import Path
from PIL import Image

from mosaico.cropper import (
    cut_grid,
    find_motif_bbox_in_cell,
    normalize_to_white,
)


def _make_sheet(tmp_path: Path) -> Path:
    """Build a 300x300 white sheet with a colored square in each of 9 cells."""
    arr = np.full((300, 300, 3), 255, dtype=np.uint8)
    for r in range(3):
        for c in range(3):
            cy, cx = r * 100 + 50, c * 100 + 50
            arr[cy - 20:cy + 20, cx - 20:cx + 20] = [50, 50, 50]
    p = tmp_path / "sheet.png"
    Image.fromarray(arr).save(p)
    return p


def test_normalize_to_white_replaces_near_white_background():
    arr = np.full((30, 30, 3), 250, dtype=np.uint8)
    arr[10:20, 10:20] = [40, 40, 40]
    out = normalize_to_white(arr)
    assert (out[0, 0] == [255, 255, 255]).all()
    assert (out[15, 15] == [40, 40, 40]).all()


def test_find_motif_bbox_returns_blob():
    arr = np.full((100, 100, 3), 255, dtype=np.uint8)
    arr[40:60, 40:60] = [30, 30, 30]
    result = find_motif_bbox_in_cell(arr, 0, 0, 100, 100)
    assert result is not None
    (x0, y0, x1, y1), mask = result
    assert 35 <= x0 <= 45
    assert 55 <= x1 <= 65
    assert mask.shape == arr.shape[:2]


def test_cut_grid_default_naming(tmp_path):
    sheet = _make_sheet(tmp_path)
    out_dir = tmp_path / "cells"
    written = cut_grid(sheet, out_dir, grid=(3, 3), cells=None)
    names = sorted(p.stem for p in written)
    assert names == [f"cell-r{r}-c{c}" for r in range(3) for c in range(3)]
    assert all(p.exists() for p in written)


def test_cut_grid_named_cells_with_spans(tmp_path):
    sheet = _make_sheet(tmp_path)
    out_dir = tmp_path / "cells"
    written = cut_grid(sheet, out_dir, grid=(3, 3), cells={
        "alpha":  {"row": 0, "col": 0},
        "beta":   {"row": 1, "col": 1, "rowspan": 2, "colspan": 2},
    })
    names = sorted(p.stem for p in written)
    assert names == ["alpha", "beta"]


def test_cut_grid_skips_empty_cells(tmp_path):
    arr = np.full((300, 300, 3), 255, dtype=np.uint8)
    arr[30:70, 30:70] = [30, 30, 30]
    sheet = tmp_path / "sparse.png"
    Image.fromarray(arr).save(sheet)
    out_dir = tmp_path / "cells"
    written = cut_grid(sheet, out_dir, grid=(3, 3), cells={
        "present": {"row": 0, "col": 0},
        "missing": {"row": 2, "col": 2},
    })
    names = [p.stem for p in written]
    assert "present" in names
    assert "missing" not in names
