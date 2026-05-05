"""mosaico explain — read-only graph + prompt inspection."""
from pathlib import Path

import pytest

from mosaico import explain as explain_mod
from mosaico import render as render_mod


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


def test_explain_prints_topo_order_with_resolved_prompts(
        project_yaml, capsys
):
    explain_mod.explain(project=str(project_yaml), only="")
    captured = capsys.readouterr().out
    assert "# t — 2 artifact(s)" in captured
    a_pos = captured.index("┌─ a  [")
    b_pos = captured.index("┌─ b  [")
    assert a_pos < b_pos, "topo order: a precedes b"
    assert "first ALPHA" in captured, "template should be expanded"
    assert "Reference 1 (a):" in captured, "ref hint block present in b"
    assert "use as backdrop" in captured


def test_explain_status_render_when_state_empty(project_yaml, capsys):
    explain_mod.explain(project=str(project_yaml), only="")
    out = capsys.readouterr().out
    assert "[render]" in out
    assert "[ready]" not in out


def test_explain_status_ready_after_render(project_yaml, monkeypatch, capsys):
    import hashlib

    def mock_gen(prompt, out, refs, grid, cell_names, model, seed, aspect):
        h = hashlib.sha256(f"{prompt}|{seed}".encode()).digest()
        out_path = out.with_suffix(".jpg")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\xff\xd8\xff" + h)
        return out_path

    monkeypatch.setattr(render_mod, "run_gen", mock_gen)
    render_mod.run_render(
        project_yaml, only=None, force=None, dry_run=False
    )
    explain_mod.explain(project=str(project_yaml), only="")
    out = capsys.readouterr().out
    assert "[ready]" in out
    assert "matches state" in out


def test_explain_only_subset(project_yaml, capsys):
    """--only restricts but transitively pulls deps (same as render)."""
    explain_mod.explain(project=str(project_yaml), only="b")
    out = capsys.readouterr().out
    assert "┌─ a  [" in out, "transitive dep should appear"
    assert "┌─ b  [" in out


def test_explain_path_ref_shown(tmp_path, capsys):
    """External path refs render with their path and hint."""
    ext = tmp_path / "ext.jpg"
    ext.write_bytes(b"\xff\xd8\xff" + b"X" * 50)
    p = tmp_path / "p.yml"
    p.write_text(f"""
version: 1
name: t
defaults:
  out_root: out
artifacts:
  - id: a
    prompt_template: "x"
    refs:
      - {{path: ext.jpg, hint: "external anchor"}}
    out: a.jpg
""")
    explain_mod.explain(project=str(p), only="")
    out = capsys.readouterr().out
    assert "path ext.jpg" in out
    assert "external anchor" in out
