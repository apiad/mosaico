"""image-gen: low-level prompt -> image (with mockable OpenRouter call)."""
import base64
from pathlib import Path

import pytest

from mosaico import gen as gen_mod


JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 100
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _fake_openrouter(image: bytes):
    def _impl(token, model, prompt, refs):
        b64 = base64.b64encode(image).decode("ascii")
        return {
            "choices": [{"message": {"images": [
                {"image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]}}],
            "usage": {"cost": 0.07},
        }
    return _impl


def test_gen_writes_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(gen_mod, "call_openrouter", _fake_openrouter(JPEG_BYTES))
    monkeypatch.setattr(gen_mod, "load_token", lambda: "T")
    out = tmp_path / "out.png"
    written = gen_mod.run_gen(prompt="hello", out=out, refs=[], grid=None,
                              cells=None, model="m", seed=None,
                              aspect=None)
    assert written.suffix == ".jpg"
    assert written.exists()
    assert written.read_bytes() == JPEG_BYTES


def test_gen_extension_correction_to_png(tmp_path, monkeypatch):
    monkeypatch.setattr(gen_mod, "call_openrouter", _fake_openrouter(PNG_BYTES))
    monkeypatch.setattr(gen_mod, "load_token", lambda: "T")
    out = tmp_path / "out.jpg"
    written = gen_mod.run_gen(prompt="x", out=out, refs=[], grid=None,
                              cells=None, model="m", seed=None,
                              aspect=None)
    assert written.suffix == ".png"


def test_gen_with_grid_writes_cells(tmp_path, monkeypatch):
    monkeypatch.setattr(gen_mod, "call_openrouter", _fake_openrouter(JPEG_BYTES))
    monkeypatch.setattr(gen_mod, "load_token", lambda: "T")

    cells_written = []
    def fake_cut_grid(sheet, out_dir, grid, cells, pad_px=12):
        cells_written.append((sheet, out_dir, grid, cells))
        out_dir.mkdir(parents=True, exist_ok=True)
        names = list(cells.keys()) if cells else ["cell-r0-c0"]
        paths = []
        for n in names:
            p = out_dir / f"{n}.jpg"
            p.write_bytes(b"x")
            paths.append(p)
        return paths

    monkeypatch.setattr(gen_mod, "cut_grid", fake_cut_grid)

    out = tmp_path / "sheet.jpg"
    written = gen_mod.run_gen(prompt="x", out=out, refs=[], grid=(3, 3),
                              cells=None, model="m", seed=None,
                              aspect=None)
    assert written == out.with_suffix(".jpg")
    assert cells_written[0][1] == out.parent / "sheet" / "cells"


def test_run_gen_passes_cells_dict_through(tmp_path, monkeypatch):
    """Regression: render.py passes artifact.cells through to run_gen, which
    must hand it to cut_grid unmodified so cells land at the declared slugs.
    """
    monkeypatch.setattr(gen_mod, "call_openrouter", _fake_openrouter(JPEG_BYTES))
    monkeypatch.setattr(gen_mod, "load_token", lambda: "T")
    captured = {}
    def fake_cut_grid(sheet, out_dir, grid, cells, pad_px=12):
        captured["cells"] = cells
        out_dir.mkdir(parents=True, exist_ok=True)
        return []
    monkeypatch.setattr(gen_mod, "cut_grid", fake_cut_grid)
    declared = {
        "alpha": {"row": 0, "col": 0},
        "beta":  {"row": 0, "col": 1},
        "gamma": {"row": 1, "col": 0},
        "delta": {"row": 1, "col": 1},
    }
    gen_mod.run_gen(prompt="x", out=tmp_path / "sheet.jpg", refs=[],
                    grid=(2, 2), cells=declared,
                    model="m", seed=None, aspect=None)
    assert captured["cells"] == declared


def test_gen_missing_token_fails_with_actionable_message(tmp_path, monkeypatch):
    # Both env-key and token file paths absent: load_token must fail loudly.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(gen_mod, "TOKEN_FILE",
                        Path("/no/such/path/openrouter.token"))
    out = tmp_path / "out.jpg"
    with pytest.raises(SystemExit):
        gen_mod.run_gen(prompt="x", out=out, refs=[], grid=None,
                        cells=None, model="m", seed=None, aspect=None)


def test_gen_missing_ref_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(gen_mod, "load_token", lambda: "T")
    monkeypatch.setattr(gen_mod, "call_openrouter", _fake_openrouter(JPEG_BYTES))
    with pytest.raises(SystemExit):
        gen_mod.run_gen(prompt="x", out=tmp_path / "o.jpg",
                        refs=[tmp_path / "missing.jpg"],
                        grid=None, cells=None,
                        model="m", seed=None, aspect=None)
