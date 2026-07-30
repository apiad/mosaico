"""Imported manifests are referenceable but frozen.

A project can `imports:` another manifest to reuse its artifacts as refs.
Imported artifacts are never render candidates — not directly, and not as
transitive dependencies of a `--only` target. That protects a canonical
image set (character sheets, style references) from being regenerated as a
side effect of rendering something that merely depends on it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mosaico.render import _input_hash_for, _restrict_to_only
from mosaico.schema import SchemaError, parse_project, topo_sort


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n")
    return p


@pytest.fixture
def canon(tmp_path: Path) -> Path:
    """A frozen manifest holding two canonical sheets, both on disk."""
    _write(tmp_path / "canon" / "refs.yml", """
version: 1
name: canon
defaults:
  out_root: .
  state: .mosaico/canon.json
templates:
  style: soft watercolor
artifacts:
  - id: style-reference
    prompt_template: "palette board. {{ templates.style }}"
    out: style-reference.jpg
  - id: hermanas-sheet
    prompt_template: "two sisters. {{ templates.style }}"
    refs:
      - artifact: style-reference
    out: hermanas-sheet.jpg
""")
    (tmp_path / "canon" / "style-reference.jpg").write_bytes(b"STYLE-BYTES")
    (tmp_path / "canon" / "hermanas-sheet.jpg").write_bytes(b"HERMANAS-BYTES")
    return tmp_path / "canon" / "refs.yml"


@pytest.fixture
def chapter(tmp_path: Path, canon: Path) -> Path:
    """A chapter manifest importing the canon."""
    return _write(tmp_path / "chapter" / "cap.yml", """
version: 1
name: cap
imports:
  - ../canon/refs.yml
defaults:
  out_root: .
  state: .mosaico/cap.json
artifacts:
  - id: cap-cover
    prompt_template: "the cover"
    refs:
      - artifact: style-reference
      - artifact: hermanas-sheet
    out: cover.jpg
  - id: cap-scene-1
    prompt_template: "first scene"
    refs:
      - artifact: hermanas-sheet
      - artifact: cap-cover
    out: 01-scene.jpg
""")


class TestImportResolution:
    def test_imported_artifacts_resolve_as_refs(self, chapter: Path):
        """A ref to an imported id must not raise 'unknown artifact'."""
        proj = parse_project(chapter)
        cover = next(a for a in proj.artifacts if a.id == "cap-cover")
        assert [r.artifact for r in cover.refs] == [
            "style-reference", "hermanas-sheet",
        ]

    def test_imported_artifacts_are_not_own_artifacts(self, chapter: Path):
        """`artifacts` holds only what this manifest owns."""
        proj = parse_project(chapter)
        assert sorted(a.id for a in proj.artifacts) == ["cap-cover", "cap-scene-1"]

    def test_imported_ids_are_exposed_as_frozen(self, chapter: Path):
        proj = parse_project(chapter)
        assert sorted(proj.imported) == ["hermanas-sheet", "style-reference"]

    def test_unknown_ref_still_fails(self, tmp_path: Path, canon: Path):
        """Validation of refs lives in topo_sort, not parse_project."""
        bad = _write(tmp_path / "bad" / "bad.yml", """
version: 1
name: bad
imports:
  - ../canon/refs.yml
artifacts:
  - id: x
    prompt_template: "x"
    refs:
      - artifact: does-not-exist
    out: x.jpg
""")
        with pytest.raises(SchemaError, match="does-not-exist"):
            topo_sort(parse_project(bad))

    def test_missing_import_file_fails_clearly(self, tmp_path: Path):
        bad = _write(tmp_path / "bad" / "bad.yml", """
version: 1
name: bad
imports:
  - ../nope/missing.yml
artifacts:
  - id: x
    prompt_template: "x"
    out: x.jpg
""")
        with pytest.raises(SchemaError, match="missing.yml"):
            parse_project(bad)


class TestFrozenFromRender:
    def test_topo_sort_excludes_imported(self, chapter: Path):
        proj = parse_project(chapter)
        ordered = topo_sort(proj)
        assert [a.id for a in ordered] == ["cap-cover", "cap-scene-1"]

    def test_only_does_not_pull_imported_deps(self, chapter: Path):
        """The regression this feature exists for.

        `--only cap-scene-1` must render the scene and its *own* dep
        (cap-cover), and must never reach into the imported canon.
        """
        proj = parse_project(chapter)
        ordered = topo_sort(proj)
        by_id = {a.id: a for a in ordered}
        got = _restrict_to_only(ordered, ["cap-scene-1"], by_id, proj.imported)
        assert [a.id for a in got] == ["cap-cover", "cap-scene-1"]

    def test_only_rejects_an_imported_id(self, chapter: Path):
        """Naming a frozen artifact in --only is a mistake worth catching."""
        proj = parse_project(chapter)
        ordered = topo_sort(proj)
        by_id = {a.id: a for a in ordered}
        with pytest.raises(SystemExit):
            _restrict_to_only(ordered, ["hermanas-sheet"], by_id, proj.imported)


class TestFrozenHashing:
    def test_imported_ref_hashes_the_file_not_the_recipe(self, chapter: Path):
        """Frozen refs hash output bytes, like `path:` refs already do.

        This is what makes editing the canon's prompts harmless: only a
        change to the produced *file* can invalidate a dependent.
        """
        proj = parse_project(chapter)
        cover = next(a for a in proj.artifacts if a.id == "cap-cover")
        _, inputs = _input_hash_for(cover, proj, {"artifacts": {}})
        frozen = [r for r in inputs["ref_hashes"] if r.get("kind") == "frozen"]
        assert len(frozen) == 2
        expected = "sha256:" + hashlib.sha256(b"HERMANAS-BYTES").hexdigest()
        assert any(r["file_hash"] == expected for r in frozen)

    def test_editing_canon_prompt_does_not_change_dependent_hash(
        self, chapter: Path, canon: Path
    ):
        proj = parse_project(chapter)
        cover = next(a for a in proj.artifacts if a.id == "cap-cover")
        before, _ = _input_hash_for(cover, proj, {"artifacts": {}})

        canon.write_text(canon.read_text().replace(
            "two sisters.", "two sisters, revised wording."
        ))
        proj2 = parse_project(chapter)
        cover2 = next(a for a in proj2.artifacts if a.id == "cap-cover")
        after, _ = _input_hash_for(cover2, proj2, {"artifacts": {}})

        assert before == after

    def test_replacing_canon_file_does_change_dependent_hash(
        self, chapter: Path, tmp_path: Path
    ):
        proj = parse_project(chapter)
        cover = next(a for a in proj.artifacts if a.id == "cap-cover")
        before, _ = _input_hash_for(cover, proj, {"artifacts": {}})

        (tmp_path / "canon" / "hermanas-sheet.jpg").write_bytes(b"REDRAWN")
        after, _ = _input_hash_for(cover, proj, {"artifacts": {}})

        assert before != after

    def test_missing_frozen_output_fails_naming_its_manifest(
        self, chapter: Path, tmp_path: Path
    ):
        (tmp_path / "canon" / "hermanas-sheet.jpg").unlink()
        proj = parse_project(chapter)
        cover = next(a for a in proj.artifacts if a.id == "cap-cover")
        with pytest.raises(SystemExit):
            _input_hash_for(cover, proj, {"artifacts": {}})


class TestImportedTemplates:
    """Chapter manifests reuse the canon's shared prompt vocabulary."""

    def test_imported_templates_are_available(self, tmp_path: Path, canon: Path):
        cap = _write(tmp_path / "c" / "c.yml", """
version: 1
name: c
imports:
  - ../canon/refs.yml
artifacts:
  - id: scene
    prompt_template: "a scene. {{ templates.style }}"
    out: scene.jpg
""")
        proj = parse_project(cap)
        assert proj.templates["style"] == "soft watercolor"

    def test_local_template_may_not_shadow_an_imported_one(
        self, tmp_path: Path, canon: Path
    ):
        cap = _write(tmp_path / "c" / "c.yml", """
version: 1
name: c
imports:
  - ../canon/refs.yml
templates:
  style: something else
artifacts:
  - id: scene
    prompt_template: "a scene. {{ templates.style }}"
    out: scene.jpg
""")
        with pytest.raises(SchemaError, match="style"):
            parse_project(cap)

    def test_local_templates_coexist_with_imported(
        self, tmp_path: Path, canon: Path
    ):
        cap = _write(tmp_path / "c" / "c.yml", """
version: 1
name: c
imports:
  - ../canon/refs.yml
templates:
  guide_canon: a specific guide
artifacts:
  - id: scene
    prompt_template: "{{ templates.guide_canon }} {{ templates.style }}"
    out: scene.jpg
""")
        proj = parse_project(cap)
        scene = proj.artifacts[0]
        from mosaico.schema import expand_templates
        resolved = expand_templates(scene.prompt_template, proj.templates)
        assert "a specific guide" in resolved
        assert "soft watercolor" in resolved
