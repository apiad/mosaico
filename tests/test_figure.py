"""mosaico figure: T-pose skeleton geometry and the CLI writing an image."""
import math
import subprocess
import sys

import pytest

from mosaico.figure import ARM, LEG, POSES, SHOULDER_X, SHOULDER_Y, skeleton

pytest.importorskip("tesserax")


def _by(segments, name, side):
    return next(s for s in segments if s["name"] == name and s["side"] == side)


def test_t_pose_arms_are_horizontal_and_full_length():
    segs = skeleton(POSES["t"])
    reach = sum(length for _, length, _ in ARM)
    for side in (+1, -1):
        hand = _by(segs, "hand", side)
        assert hand["end"][1] == pytest.approx(SHOULDER_Y)
        assert hand["end"][0] == pytest.approx(side * (SHOULDER_X + reach))


def test_t_pose_is_mirror_symmetric():
    segs = skeleton(POSES["t"])
    for name, _, _ in ARM + LEG:
        left, right = _by(segs, name, +1), _by(segs, name, -1)
        assert left["end"][0] == pytest.approx(-right["end"][0])
        assert left["end"][1] == pytest.approx(right["end"][1])


def test_segments_keep_their_lengths():
    segs = skeleton(POSES["t"])
    lengths = {name: length for name, length, _ in ARM + LEG}
    for s in segs:
        (ax, ay), (bx, by) = s["start"], s["end"]
        assert math.hypot(bx - ax, by - ay) == pytest.approx(lengths[s["name"]])


def test_wrong_angle_count_is_rejected():
    pose = dict(POSES["t"], arm_l=(90, 0))
    with pytest.raises(ValueError, match="arm_l needs 3 angles"):
        skeleton(pose)


def test_cli_writes_png_of_requested_size(tmp_path):
    from PIL import Image

    out = tmp_path / "t.png"
    result = subprocess.run(
        [sys.executable, "-m", "mosaico.cli", "figure", "--out", str(out), "--size", "512"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    img = Image.open(out)
    assert img.size == (512, 512)
    # White corners, non-white centre: the figure is drawn and framed.
    assert img.convert("RGB").getpixel((2, 2)) == (255, 255, 255)
    assert img.convert("RGB").getpixel((256, 200)) != (255, 255, 255)


def test_cli_rejects_unknown_pose(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mosaico.cli", "figure", "--pose", "nope",
         "--out", str(tmp_path / "x.png")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "unknown pose" in result.stdout + result.stderr
