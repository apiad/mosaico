import pytest
from mosaico.schema import (
    parse_project,
    expand_templates,
    topo_sort,
    SchemaError,
)


def _proj(tmp_path, body: str):
    p = tmp_path / "p.yml"
    p.write_text(body)
    return parse_project(p)


def test_parse_minimal_project(tmp_path):
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
artifacts:
  - id: a
    prompt_template: "hello"
    out: a.jpg
""")
    proj = parse_project(p)
    assert proj.name == "t"
    assert proj.artifacts[0].id == "a"
    assert proj.artifacts[0].out == "a.jpg"


def test_template_expansion():
    s = expand_templates("a {{ templates.x }} b", {"x": "X"})
    assert s == "a X b"


def test_template_expansion_recursive():
    s = expand_templates(
        "{{ templates.outer }}",
        {"outer": "y {{ templates.inner }}", "inner": "Z"},
    )
    assert s == "y Z"


def test_template_expansion_unknown_fails():
    with pytest.raises(SchemaError) as e:
        expand_templates("{{ templates.missing }}", {})
    msg = str(e.value).lower()
    assert "missing" in msg
    assert "tour" in msg or "templates" in msg


def test_parse_missing_id_fails(tmp_path):
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
artifacts:
  - prompt_template: "x"
    out: x.jpg
""")
    with pytest.raises(SchemaError) as e:
        parse_project(p)
    assert "id" in str(e.value).lower()


def test_parse_duplicate_id_fails(tmp_path):
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
artifacts:
  - id: a
    prompt_template: "x"
    out: x.jpg
  - id: a
    prompt_template: "y"
    out: y.jpg
""")
    with pytest.raises(SchemaError) as e:
        parse_project(p)
    assert "duplicate" in str(e.value).lower()
    assert "a" in str(e.value)


def test_description_alias_accepted(tmp_path):
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
artifacts:
  - id: a
    description: "via alias"
    out: a.jpg
""")
    proj = parse_project(p)
    assert proj.artifacts[0].prompt_template == "via alias"


def test_defaults_propagate(tmp_path):
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
defaults:
  model: m1
  seed: 99
  aspect: 4:3
  out_root: refs/
artifacts:
  - id: a
    prompt_template: "x"
    out: a.jpg
""")
    proj = parse_project(p)
    a = proj.artifacts[0]
    assert a.resolved_model == "m1"
    assert a.resolved_seed == 99
    assert a.resolved_aspect == "4:3"


def test_per_artifact_override_wins(tmp_path):
    p = tmp_path / "p.yml"
    p.write_text("""
version: 1
name: t
defaults:
  model: m1
  seed: 99
artifacts:
  - id: a
    prompt_template: "x"
    out: a.jpg
    model: m2
    seed: 7
""")
    proj = parse_project(p)
    a = proj.artifacts[0]
    assert a.resolved_model == "m2"
    assert a.resolved_seed == 7


def test_missing_yaml_path_fails(tmp_path):
    with pytest.raises(SchemaError) as e:
        parse_project(tmp_path / "nope.yml")
    assert "not found" in str(e.value).lower()


def test_unsupported_version_fails(tmp_path):
    p = tmp_path / "p.yml"
    p.write_text("version: 99\nname: t\nartifacts: []\n")
    with pytest.raises(SchemaError) as e:
        parse_project(p)
    assert "version" in str(e.value).lower()


def test_empty_artifacts_fails(tmp_path):
    p = tmp_path / "p.yml"
    p.write_text("version: 1\nname: t\nartifacts: []\n")
    with pytest.raises(SchemaError) as e:
        parse_project(p)
    assert "artifacts" in str(e.value).lower()


def test_topo_sort_linear(tmp_path):
    proj = _proj(tmp_path, """
version: 1
name: t
artifacts:
  - id: a
    prompt_template: "x"
    out: a.jpg
  - id: b
    prompt_template: "y"
    out: b.jpg
    refs:
      - {artifact: a, hint: ""}
""")
    order = [a.id for a in topo_sort(proj)]
    assert order == ["a", "b"]


def test_topo_sort_stable_lex_order(tmp_path):
    proj = _proj(tmp_path, """
version: 1
name: t
artifacts:
  - id: zebra
    prompt_template: "z"
    out: z.jpg
  - id: alpha
    prompt_template: "a"
    out: a.jpg
  - id: monkey
    prompt_template: "m"
    out: m.jpg
""")
    order = [a.id for a in topo_sort(proj)]
    assert order == ["alpha", "monkey", "zebra"]


def test_topo_sort_cycle_fails(tmp_path):
    proj = _proj(tmp_path, """
version: 1
name: t
artifacts:
  - id: a
    prompt_template: "x"
    out: a.jpg
    refs: [{artifact: b, hint: ""}]
  - id: b
    prompt_template: "y"
    out: b.jpg
    refs: [{artifact: a, hint: ""}]
""")
    with pytest.raises(SchemaError) as e:
        topo_sort(proj)
    msg = str(e.value).lower()
    assert "cycle" in msg
    assert "a" in str(e.value) and "b" in str(e.value)


def test_topo_sort_unknown_ref_fails(tmp_path):
    proj = _proj(tmp_path, """
version: 1
name: t
artifacts:
  - id: a
    prompt_template: "x"
    out: a.jpg
    refs: [{artifact: nonexistent, hint: ""}]
""")
    with pytest.raises(SchemaError) as e:
        topo_sort(proj)
    msg = str(e.value)
    assert "nonexistent" in msg
    assert "a" in msg
