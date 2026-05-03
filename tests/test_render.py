"""image-render: orchestrate a project YAML."""
import hashlib
from pathlib import Path

import pytest

from mosaico import render as render_mod


def _mock_generator(prompt, out, refs, grid, cell_names, model, seed, aspect):
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

    def changing_generator(prompt, out, refs, grid, cell_names, model, seed, aspect):
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
