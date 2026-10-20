"""api="images": run_gen talks to OpenRouter's /api/v1/images endpoint."""
import base64
import json

import httpx
import pytest

from mosaico import gen as gen_mod
from mosaico.render import _input_hash_for, run_render
from mosaico.schema import SchemaError, parse_project


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
JPG_BYTES = b"\xff\xd8\xff" + b"\x00" * 100

_OriginalClient = httpx.Client


def _install_mock(monkeypatch, captured: dict, image: bytes = PNG_BYTES) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.read())
        return httpx.Response(200, json={
            "created": 0,
            "data": [{"b64_json": base64.b64encode(image).decode("ascii"),
                      "media_type": "image/png"}],
            "usage": {"cost": 0.009},
        })

    def fake_client(*args, **kwargs):
        return _OriginalClient(transport=httpx.MockTransport(handler), timeout=180)

    monkeypatch.setattr(httpx, "Client", fake_client)
    monkeypatch.setattr(gen_mod, "load_token", lambda: "T")


def test_images_api_payload(tmp_path, monkeypatch):
    captured: dict = {}
    _install_mock(monkeypatch, captured)
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(JPG_BYTES)

    gen_mod.run_gen(
        prompt="a horse", out=tmp_path / "out.png", refs=[ref], grid=None,
        cells=None, model="black-forest-labs/flux-3-image-klein", seed=42,
        aspect="3:2", api="images", resolution="2K",
    )

    assert captured["url"] == gen_mod.IMAGES_ENDPOINT
    p = captured["payload"]
    assert p["model"] == "black-forest-labs/flux-3-image-klein"
    assert p["prompt"] == "a horse"
    assert p["aspect_ratio"] == "3:2"
    assert p["resolution"] == "2K"
    assert p["input_references"] == [{
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,"
                      + base64.b64encode(JPG_BYTES).decode("ascii")},
    }]
    for absent in ("seed", "size", "messages", "modalities"):
        assert absent not in p


def test_images_api_minimal_payload(tmp_path, monkeypatch):
    captured: dict = {}
    _install_mock(monkeypatch, captured)

    gen_mod.run_gen(
        prompt="a horse", out=tmp_path / "out.png", refs=[], grid=None,
        cells=None, model="m", seed=None, aspect=None, api="images",
    )

    assert captured["payload"] == {"model": "m", "prompt": "a horse"}


def test_images_api_writes_decoded_image(tmp_path, monkeypatch):
    _install_mock(monkeypatch, {}, image=JPG_BYTES)

    written = gen_mod.run_gen(
        prompt="p", out=tmp_path / "out.png", refs=[], grid=None, cells=None,
        model="m", seed=None, aspect=None, api="images",
    )

    assert written == tmp_path / "out.jpg"
    assert written.read_bytes() == JPG_BYTES


def test_chat_api_is_default(tmp_path, monkeypatch):
    captured: dict = {}

    def handler(request):
        captured["url"] = str(request.url)
        b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        return httpx.Response(200, json={"choices": [{"message": {"images": [
            {"image_url": {"url": f"data:image/png;base64,{b64}"}}]}}]})

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _OriginalClient(
        transport=httpx.MockTransport(handler), timeout=180))
    monkeypatch.setattr(gen_mod, "load_token", lambda: "T")

    gen_mod.run_gen(prompt="p", out=tmp_path / "o.png", refs=[], grid=None,
                    cells=None, model="m", seed=None, aspect=None)

    assert captured["url"] == gen_mod.ENDPOINT


def _write_project(tmp_path, defaults: str = "", artifact: str = ""):
    p = tmp_path / "p.yml"
    p.write_text(f"""
version: 1
name: t
defaults:
  out_root: out
  state: state.json
{defaults}
artifacts:
  - id: a
    prompt_template: "hello"
    out: a.jpg
{artifact}
""")
    return p


def test_schema_reads_api_and_resolution_from_defaults(tmp_path):
    proj = parse_project(_write_project(tmp_path, defaults="  api: images\n  resolution: 2K"))
    a = proj.artifacts[0]
    assert (a.resolved_api, a.resolved_resolution) == ("images", "2K")


def test_schema_artifact_overrides_defaults(tmp_path):
    proj = parse_project(_write_project(
        tmp_path, defaults="  api: images", artifact="    api: chat"))
    assert proj.artifacts[0].resolved_api == "chat"


def test_schema_rejects_unknown_api(tmp_path):
    with pytest.raises(SchemaError, match="api"):
        parse_project(_write_project(tmp_path, artifact="    api: video"))


def test_input_hash_unchanged_when_api_unset(tmp_path):
    proj = parse_project(_write_project(tmp_path))
    _, inputs = _input_hash_for(proj.artifacts[0], proj, {"artifacts": {}})
    assert "api" not in inputs and "resolution" not in inputs


def test_input_hash_changes_with_api_and_resolution(tmp_path):
    base = parse_project(_write_project(tmp_path))
    h0, _ = _input_hash_for(base.artifacts[0], base, {"artifacts": {}})
    img = parse_project(_write_project(tmp_path, defaults="  api: images"))
    h1, _ = _input_hash_for(img.artifacts[0], img, {"artifacts": {}})
    img2k = parse_project(_write_project(tmp_path, defaults="  api: images\n  resolution: 2K"))
    h2, _ = _input_hash_for(img2k.artifacts[0], img2k, {"artifacts": {}})
    assert len({h0, h1, h2}) == 3


def test_render_passes_api_and_resolution_to_run_gen(tmp_path, monkeypatch):
    captured: dict = {}

    def capturing_gen(prompt, out, refs, grid, cells, model, seed, aspect, **kw):
        captured.update(kw)
        out_path = out.with_suffix(".jpg")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(JPG_BYTES)
        return out_path

    monkeypatch.setattr("mosaico.render.run_gen", capturing_gen)
    yml = _write_project(tmp_path, defaults="  api: images\n  resolution: 1K")
    run_render(yml, only=None, force=None, dry_run=False)

    assert captured["api"] == "images"
    assert captured["resolution"] == "1K"
