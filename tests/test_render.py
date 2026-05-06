"""image-render: orchestrate a project YAML."""
import hashlib
from pathlib import Path

import pytest

from mosaico import render as render_mod


def _mock_generator(prompt, out, refs, grid, cells, model, seed, aspect):
    """Deterministic mock: writes prompt+seed sha256 as JPEG-magic bytes."""
    h = hashlib.sha256(f"{prompt}|{seed}".encode()).digest()
    out_path = out.with_suffix(".jpg")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"\xff\xd8\xff" + h + b"\x00" * 100)
    return out_path


@pytest.fixture
def project_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
defaults:
  out_root: out
  state: state.json
artifacts:
  - id: a
    prompt_template: "first {{ templates.x }}"
    out: a.jpg
  - id: b
    prompt_template: "second"
    refs:
      - artifact: a
        hint: "use as backdrop"
    out: b.jpg
templates:
  x: "ALPHA"
""")
    return p


def test_render_first_run_renders_all(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    summary = render_mod.run_render(project_yaml, only=None, force=None,
                                    dry_run=False)
    assert summary.rendered == ["a", "b"]
    assert summary.skipped == []
    assert (project_yaml.parent / "out" / "a.jpg").exists()
    assert (project_yaml.parent / "out" / "b.jpg").exists()


def test_render_second_run_caches(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    render_mod.run_render(project_yaml, only=None, force=None, dry_run=False)
    summary = render_mod.run_render(project_yaml, only=None, force=None,
                                    dry_run=False)
    assert summary.rendered == []
    assert sorted(summary.skipped) == ["a", "b"]


def test_render_force_one_re_renders_only_that_one(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    render_mod.run_render(project_yaml, only=None, force=None, dry_run=False)
    summary = render_mod.run_render(project_yaml, only=None, force=["a"],
                                    dry_run=False)
    assert summary.rendered == ["a"]
    assert summary.skipped == ["b"]


def test_render_force_upstream_cascades_when_output_changes(
        project_yaml, monkeypatch):
    counter = {"n": 0}

    def changing_generator(prompt, out, refs, grid, cells, model, seed, aspect):
        counter["n"] += 1
        out_path = out.with_suffix(".jpg")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\xff\xd8\xff" + str(counter["n"]).encode())
        return out_path

    monkeypatch.setattr(render_mod, "run_gen", changing_generator)
    render_mod.run_render(project_yaml, only=None, force=None, dry_run=False)
    summary = render_mod.run_render(project_yaml, only=None, force=["a"],
                                    dry_run=False)
    assert sorted(summary.rendered) == ["a", "b"]


def test_render_only_subset(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    summary = render_mod.run_render(project_yaml, only=["b"], force=None,
                                    dry_run=False)
    assert sorted(summary.rendered) == ["a", "b"]


def test_render_dry_run(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    summary = render_mod.run_render(project_yaml, only=None, force=None,
                                    dry_run=True)
    assert summary.rendered == []
    assert summary.planned == ["a", "b"]
    assert not (project_yaml.parent / "out" / "a.jpg").exists()


def test_render_unknown_only_id_fails(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    with pytest.raises(SystemExit):
        render_mod.run_render(project_yaml, only=["zzz"], force=None,
                              dry_run=False)


def test_render_unknown_force_id_fails(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    with pytest.raises(SystemExit):
        render_mod.run_render(project_yaml, only=None, force=["nope"],
                              dry_run=False)


def test_render_force_all_wipes_state(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    render_mod.run_render(project_yaml, only=None, force=None, dry_run=False)
    summary = render_mod.run_render(project_yaml, only=None, force=["all"],
                                    dry_run=False)
    assert sorted(summary.rendered) == ["a", "b"]


def test_render_template_change_invalidates(project_yaml, monkeypatch):
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    render_mod.run_render(project_yaml, only=None, force=None, dry_run=False)
    text = project_yaml.read_text().replace('x: "ALPHA"', 'x: "BETA"')
    project_yaml.write_text(text)
    summary = render_mod.run_render(project_yaml, only=None, force=None,
                                    dry_run=False)
    assert "a" in summary.rendered


def test_bootstrap_anchors_existing_files_without_api(project_yaml, monkeypatch):
    """Pre-existing on-disk outputs are anchored to current manifest hashes;
    run_gen is never called."""
    out_dir = project_yaml.parent / "out"
    out_dir.mkdir(parents=True)
    (out_dir / "a.jpg").write_bytes(b"\xff\xd8\xff" + b"AAA" * 50)
    (out_dir / "b.jpg").write_bytes(b"\xff\xd8\xff" + b"BBB" * 50)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_gen must not be called during --bootstrap")

    monkeypatch.setattr(render_mod, "run_gen", fail_if_called)
    summary = render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False, bootstrap=True
    )
    assert sorted(summary.anchored) == ["a", "b"]
    assert summary.pending == []
    assert summary.rendered == []

    # Subsequent regular render is fully cached.
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    summary2 = render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False
    )
    assert summary2.rendered == []
    assert sorted(summary2.skipped) == ["a", "b"]


def test_bootstrap_partial_existence_marks_missing_as_pending(
        project_yaml, monkeypatch):
    """When some outputs exist and others don't, the existing ones get
    anchored and the missing ones land in pending."""
    out_dir = project_yaml.parent / "out"
    out_dir.mkdir(parents=True)
    (out_dir / "a.jpg").write_bytes(b"\xff\xd8\xff" + b"AAA" * 50)
    # b.jpg is intentionally missing.

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_gen must not be called during --bootstrap")

    monkeypatch.setattr(render_mod, "run_gen", fail_if_called)
    summary = render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False, bootstrap=True
    )
    assert summary.anchored == ["a"]
    assert summary.pending == ["b"]

    # After bootstrap, a regular render should render only b.
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    summary2 = render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False
    )
    assert summary2.rendered == ["b"]
    assert summary2.skipped == ["a"]


def test_bootstrap_is_idempotent_and_preserves_rendered_at(
        project_yaml, monkeypatch):
    """Re-running bootstrap on an already-anchored state preserves
    rendered_at when the output_hash hasn't changed."""
    import json
    out_dir = project_yaml.parent / "out"
    out_dir.mkdir(parents=True)
    (out_dir / "a.jpg").write_bytes(b"\xff\xd8\xff" + b"AAA" * 50)
    (out_dir / "b.jpg").write_bytes(b"\xff\xd8\xff" + b"BBB" * 50)

    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False, bootstrap=True
    )
    state_path = project_yaml.parent / "state.json"
    first = json.loads(state_path.read_text())
    first_a_at = first["artifacts"]["a"]["rendered_at"]

    render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False, bootstrap=True
    )
    second = json.loads(state_path.read_text())
    assert second["artifacts"]["a"]["rendered_at"] == first_a_at
    assert second["artifacts"]["a"]["input_hash"] == first["artifacts"]["a"]["input_hash"]


def test_bootstrap_dry_run_does_not_write_state(project_yaml, monkeypatch):
    out_dir = project_yaml.parent / "out"
    out_dir.mkdir(parents=True)
    (out_dir / "a.jpg").write_bytes(b"\xff\xd8\xff" + b"AAA" * 50)
    (out_dir / "b.jpg").write_bytes(b"\xff\xd8\xff" + b"BBB" * 50)

    summary = render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=True, bootstrap=True
    )
    assert sorted(summary.anchored) == ["a", "b"]
    state_path = project_yaml.parent / "state.json"
    assert not state_path.exists()


def test_bootstrap_with_force_fails(project_yaml, monkeypatch):
    out_dir = project_yaml.parent / "out"
    out_dir.mkdir(parents=True)
    (out_dir / "a.jpg").write_bytes(b"\xff\xd8\xff" + b"AAA" * 50)
    with pytest.raises(SystemExit):
        render_mod.run_render(
            project_yaml, only=None, force=["a"], dry_run=False, bootstrap=True
        )


def test_bootstrap_re_anchors_after_prompt_refactor(project_yaml, monkeypatch):
    """Editing a template after bootstrap then re-bootstrapping anchors the
    existing file to the new prompt's hash — no re-render needed."""
    import json
    out_dir = project_yaml.parent / "out"
    out_dir.mkdir(parents=True)
    (out_dir / "a.jpg").write_bytes(b"\xff\xd8\xff" + b"AAA" * 50)
    (out_dir / "b.jpg").write_bytes(b"\xff\xd8\xff" + b"BBB" * 50)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_gen must not be called during --bootstrap")

    monkeypatch.setattr(render_mod, "run_gen", fail_if_called)
    render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False, bootstrap=True
    )
    state_path = project_yaml.parent / "state.json"
    first_hash = json.loads(state_path.read_text())["artifacts"]["a"]["input_hash"]

    text = project_yaml.read_text().replace('x: "ALPHA"', 'x: "OMEGA"')
    project_yaml.write_text(text)

    render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False, bootstrap=True
    )
    second_hash = json.loads(state_path.read_text())["artifacts"]["a"]["input_hash"]
    assert first_hash != second_hash, "input_hash should reflect new template"

    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    summary = render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False
    )
    assert summary.rendered == []
    assert sorted(summary.skipped) == ["a", "b"]


def test_render_propagates_cells_to_run_gen(tmp_path, monkeypatch):
    """Regression for the cells: propagation bug. When an artifact declares
    `grid:` + `cells:`, render.py must pass that cells dict through to
    run_gen so the cropper writes per-slug filenames (not generic
    `cell-rR-cC` defaults)."""
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
defaults:
  out_root: out
  state: state.json
artifacts:
  - id: sheet
    prompt_template: "a sheet"
    out: sheet.jpg
    grid: [2, 2]
    cells:
      alpha: {row: 0, col: 0}
      beta:  {row: 0, col: 1}
      gamma: {row: 1, col: 0}
      delta: {row: 1, col: 1}
""")

    captured = {}

    def capturing_gen(prompt, out, refs, grid, cells, model, seed, aspect):
        captured["grid"] = grid
        captured["cells"] = cells
        out_path = out.with_suffix(".jpg")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        return out_path

    monkeypatch.setattr(render_mod, "run_gen", capturing_gen)
    summary = render_mod.run_render(p, only=None, force=None, dry_run=False)

    assert summary.rendered == ["sheet"]
    assert captured["grid"] == (2, 2)
    assert captured["cells"] == {
        "alpha": {"row": 0, "col": 0},
        "beta":  {"row": 0, "col": 1},
        "gamma": {"row": 1, "col": 0},
        "delta": {"row": 1, "col": 1},
    }


def test_render_external_path_ref_missing_fails(tmp_path, monkeypatch):
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
defaults:
  out_root: out
artifacts:
  - id: a
    prompt_template: "x"
    refs:
      - {path: not-here.jpg, hint: "ext"}
    out: a.jpg
""")
    monkeypatch.setattr(render_mod, "run_gen", _mock_generator)
    with pytest.raises(SystemExit):
        render_mod.run_render(p, only=None, force=None, dry_run=False)
