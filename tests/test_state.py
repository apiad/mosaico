from pathlib import Path

from mosaico.state import (
    compute_input_hash,
    file_sha256,
    load_state,
    save_state,
)


def test_file_sha256(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"hello")
    h = file_sha256(p)
    assert h == "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_input_hash_stable_under_key_order():
    inp = {
        "resolved_prompt": "x",
        "model": "m",
        "seed": 1,
        "aspect": "1:1",
        "grid": None,
        "cells_spec": None,
        "ref_hashes": [],
    }
    h1 = compute_input_hash(inp)
    inp2 = dict(reversed(list(inp.items())))
    h2 = compute_input_hash(inp2)
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_input_hash_changes_with_seed():
    base = {"resolved_prompt": "x", "model": "m", "seed": 1, "aspect": "1:1",
            "grid": None, "cells_spec": None, "ref_hashes": []}
    h1 = compute_input_hash(base)
    h2 = compute_input_hash({**base, "seed": 2})
    assert h1 != h2


def test_input_hash_changes_with_ref_hint():
    base = {"resolved_prompt": "x", "model": "m", "seed": 1, "aspect": "1:1",
            "grid": None, "cells_spec": None,
            "ref_hashes": [{"artifact": "a", "hint": "h1", "out_hash": "sha256:zz"}]}
    h1 = compute_input_hash(base)
    h2 = compute_input_hash({**base, "ref_hashes": [
        {"artifact": "a", "hint": "h2", "out_hash": "sha256:zz"},
    ]})
    assert h1 != h2


def test_load_state_missing_returns_empty(tmp_path):
    state = load_state(tmp_path / "no.json")
    assert state == {"artifacts": {}}


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    save_state(p, {"artifacts": {"a": {"input_hash": "sha256:abc"}}})
    loaded = load_state(p)
    assert loaded["artifacts"]["a"]["input_hash"] == "sha256:abc"


def test_save_state_creates_parent_dir(tmp_path):
    p = tmp_path / "deep" / "nested" / "state.json"
    save_state(p, {"artifacts": {}})
    assert p.exists()


def test_load_corrupt_json_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json {{")
    state = load_state(p)
    assert state == {"artifacts": {}}
