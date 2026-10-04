"""mosaico figure: T-pose silhouette geometry and the CLI writing an image."""
import math
import subprocess
import sys

import pytest

from mosaico.figure import BODIES, HEAD_HEIGHT, POSES, PROPORTIONS, dims, skeleton

pytest.importorskip("tesserax")


def _by(segments, name, side):
    return next(s for s in segments if s["name"] == name and s["side"] == side)


@pytest.mark.parametrize("body", list(BODIES))
def test_t_pose_reaches_measured_span_at_shoulder_height(body):
    segs = skeleton(POSES["t"], body)
    for side in (+1, -1):
        upper, hand = _by(segs, "upper_arm", side), _by(segs, "hand", side)
        assert hand["end"][1] == pytest.approx(upper["start"][1])
        assert abs(hand["end"][0]) == pytest.approx(BODIES[body]["span"] / 2)


@pytest.mark.parametrize("body", list(BODIES))
def test_feet_stand_on_the_floor(body):
    segs = skeleton(POSES["t"], body)
    for side in (+1, -1):
        assert _by(segs, "foot", side)["end"][1] == pytest.approx(1.0, abs=1e-3)


def test_t_pose_is_mirror_symmetric():
    segs = skeleton(POSES["t"])
    for s in segs:
        if s["side"] == +1:
            twin = _by(segs, s["name"], -1)
            assert s["end"][0] == pytest.approx(-twin["end"][0])
            assert s["end"][1] == pytest.approx(twin["end"][1])


def test_segments_are_chained():
    segs = skeleton(POSES["t"])
    for a, b in zip(segs, segs[1:]):
        if a["side"] == b["side"] and b["name"] not in ("upper_arm", "thigh"):
            assert a["end"] == pytest.approx(b["start"])
    for s in segs:
        (ax, ay), (bx, by) = s["start"], s["end"]
        assert math.hypot(bx - ax, by - ay) > 0


def test_wrong_angle_count_is_rejected():
    pose = dict(POSES["t"], arm_l=(90, 0))
    with pytest.raises(ValueError, match="arm_l needs 3 angles"):
        skeleton(pose)


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "mosaico.cli", "figure", *args],
        capture_output=True, text=True,
    )


def test_cli_writes_flat_silhouette_of_requested_size(tmp_path):
    from PIL import Image

    out = tmp_path / "t.png"
    result = _run("--out", str(out), "--size", "512")
    assert result.returncode == 0, result.stderr
    img = Image.open(out).convert("RGB")
    assert img.size == (512, 512)
    assert img.getpixel((2, 2)) == (255, 255, 255)
    assert img.getpixel((256, 200)) == (0, 0, 0)  # the chest


@pytest.mark.parametrize("flag,value,msg", [
    ("--pose", "nope", "unknown pose"),
    ("--body", "nope", "unknown body"),
])
def test_cli_rejects_unknown_names(tmp_path, flag, value, msg):
    result = _run(flag, value, "--out", str(tmp_path / "x.png"))
    assert result.returncode != 0
    assert msg in result.stdout + result.stderr


@pytest.mark.parametrize("body", list(BODIES))
def test_real_preset_keeps_measured_heights(body):
    d = dims(body, "real")
    for key, value in BODIES[body].items():
        if key.endswith("_height") or key.endswith("_breadth") or key.endswith("_width"):
            assert d[key] == pytest.approx(value), key
    assert d["head_height"] == pytest.approx(HEAD_HEIGHT)


@pytest.mark.parametrize("preset", [p for p in PROPORTIONS if p != "real"])
@pytest.mark.parametrize("body", list(BODIES))
def test_presets_hit_their_head_count_and_stand_on_the_floor(preset, body):
    style = PROPORTIONS[preset][body]
    assert 1 / dims(body, preset)["head_height"] == pytest.approx(style["heads"])
    segs = skeleton(POSES["t"], body, preset)
    assert _by(segs, "foot", +1)["end"][1] == pytest.approx(1.0, abs=1e-3)


def test_disney_widens_men_and_narrows_women_waists():
    assert dims("male", "disney")["bideltoid_breadth"] > dims("male", "real")["bideltoid_breadth"]
    assert dims("female", "disney")["waist_breadth"] < dims("female", "real")["waist_breadth"]


def test_cli_sheet_has_one_cell_per_body_and_preset(tmp_path):
    from PIL import Image

    out = tmp_path / "sheet.png"
    result = _run("--proportions", "real,chibi", "--body", "all", "--labels",
                  "--size", "200", "--out", str(out))
    assert result.returncode == 0, result.stderr
    w, h = Image.open(out).size
    assert w == pytest.approx(400, abs=2)
    assert h > 400  # two rows plus label strips
