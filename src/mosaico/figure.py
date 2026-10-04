"""mosaico figure — draw a posed humanoid mannequin as a template sheet.

The output is meant to be passed as a ref image to `mosaico gen` / `render`
so the generated character lands in the same pose. No API calls: the figure
is computed locally and drawn with tesserax.

Model:
- Every length is in head units (H = head height), adult canon of 7.5 heads.
- A pose is a set of limb angles. Each limb is a chain of segments; the
  first angle is measured from straight down, the rest are relative bends
  of each segment against its parent. Positive angles point away from the
  body's midline, so one pose value works for both sides.
- The figure faces the viewer: its left side is drawn on the viewer's right.
- Coordinates are SVG-style, y grows downward, origin at the top of the head.

Discoverability:
    mosaico figure --tour
    mosaico figure --list-poses
    mosaico figure --out t-pose.png
    mosaico figure --pose t --out t-pose.svg --size 1536
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated

import microcli as m

from . import app

# Lengths along the body axis and joint offsets, in head units.
HEAD_W, HEAD_H = 0.75, 1.0
NECK_TOP, SHOULDER_Y = 1.0, 1.35
SHOULDER_X = 0.95
CHEST = (1.25, 2.8, 1.55)  # top, bottom, width
PELVIS = (2.8, 3.85, 1.5)
HIP_X, HIP_Y = 0.45, 3.6

# Limb chains: (segment name, length, width) from the root joint outward.
ARM = [("upper_arm", 1.45, 0.32), ("forearm", 1.2, 0.27), ("hand", 0.7, 0.3)]
LEG = [("thigh", 1.95, 0.55), ("shin", 1.75, 0.4), ("foot", 0.2, 0.35)]

# Joint ball radii, keyed by the segment that starts at the joint.
JOINT_R = {
    "upper_arm": 0.2,
    "forearm": 0.15,
    "hand": 0.12,
    "thigh": 0.24,
    "shin": 0.19,
    "foot": 0.14,
}

POSES: dict[str, dict[str, tuple[float, ...]]] = {
    "t": {
        "arm_l": (90, 0, 0),
        "arm_r": (90, 0, 0),
        "leg_l": (4, -4, 0),
        "leg_r": (4, -4, 0),
    },
}

UNIT = 100.0  # SVG units per head; keeps tesserax's 1-unit strokes thin.
BACKGROUND = "#ffffff"
TORSO = "#9ca3af"
SIDE_COLOR = {+1: "#c4c9d1", -1: "#6b7280"}  # figure's left light, right dark
JOINT = "#374151"
OUTLINE = "#1f2937"


def skeleton(pose: dict[str, tuple[float, ...]]) -> list[dict]:
    """Forward kinematics: pose angles -> limb segments with endpoints.

    Returns one dict per segment with `name`, `side` (+1 = figure's left,
    drawn on the viewer's right), `start`, `end` (in head units) and
    `width`. Torso and head are fixed; only the limbs move.
    """
    segments = []
    for limb, chain, root_y, root_x in (
        ("arm", ARM, SHOULDER_Y, SHOULDER_X),
        ("leg", LEG, HIP_Y, HIP_X),
    ):
        for side, suffix in ((+1, "l"), (-1, "r")):
            angles = pose[f"{limb}_{suffix}"]
            if len(angles) != len(chain):
                raise ValueError(
                    f"{limb}_{suffix} needs {len(chain)} angles, got {len(angles)}"
                )
            x, y, theta = side * root_x, root_y, 0.0
            for (name, length, width), angle in zip(chain, angles):
                theta += angle
                rad = math.radians(theta)
                nx = x + side * length * math.sin(rad)
                ny = y + length * math.cos(rad)
                segments.append(
                    {
                        "name": name,
                        "side": side,
                        "start": (x, y),
                        "end": (nx, ny),
                        "width": width,
                    }
                )
                x, y = nx, ny
    return segments


def build_canvas(pose_name: str, size: int, margin: float = 0.06):
    """Draw the posed figure centred on a square `size`×`size` canvas."""
    from tesserax import Canvas, Circle, Ellipse, Rect, Point
    from tesserax.color import hex
    from tesserax.core import Bounds

    segments = skeleton(POSES[pose_name])

    def p(x: float, y: float) -> Point:
        return Point(x * UNIT, y * UNIT)

    # Extent from every endpoint plus the widest half-thickness, then a
    # square viewBox around it so the figure is centred whatever the pose.
    pad = 0.4
    xs = [c for s in segments for c in (s["start"][0], s["end"][0])]
    ys = [c for s in segments for c in (s["start"][1], s["end"][1])] + [0.0]
    xs += [-CHEST[2] / 2, CHEST[2] / 2]
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    side_len = max(x1 - x0, y1 - y0) * (1 + 2 * margin)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    view = Bounds(
        (cx - side_len / 2) * UNIT,
        (cy - side_len / 2) * UNIT,
        side_len * UNIT,
        side_len * UNIT,
    )

    def bar(seg: dict, color: str) -> None:
        (ax, ay), (bx, by) = seg["start"], seg["end"]
        length = math.hypot(bx - ax, by - ay)
        # A Rect is vertical at rotation 0; turn it onto the segment.
        angle = math.atan2(-(bx - ax), by - ay)
        Rect(
            seg["width"] * UNIT,
            length * UNIT,
            fill=hex(color),
            stroke=hex(OUTLINE),
        ).rotated(angle).move_to(p((ax + bx) / 2, (ay + by) / 2))

    def ball(x: float, y: float, r: float, color: str = JOINT) -> None:
        Circle(r * UNIT, fill=hex(color), stroke=hex(OUTLINE)).move_to(p(x, y))

    canvas = Canvas(size, size)
    with canvas:
        Rect(view.width, view.height, fill=hex(BACKGROUND), stroke=hex(BACKGROUND)).move_to(
            Point(view.x + view.width / 2, view.y + view.height / 2)
        )
        legs = [s for s in segments if s["name"] in ("thigh", "shin", "foot")]
        arms = [s for s in segments if s not in legs]
        for seg in legs:
            bar(seg, SIDE_COLOR[seg["side"]])
        for top, bottom, width in (PELVIS, CHEST):
            Rect(
                width * UNIT, (bottom - top) * UNIT, fill=hex(TORSO), stroke=hex(OUTLINE)
            ).move_to(p(0, (top + bottom) / 2))
        Rect(0.35 * UNIT, (SHOULDER_Y - NECK_TOP + 0.1) * UNIT, fill=hex(TORSO), stroke=hex(OUTLINE)).move_to(
            p(0, (NECK_TOP + SHOULDER_Y) / 2)
        )
        for seg in arms:
            bar(seg, SIDE_COLOR[seg["side"]])
        Ellipse(HEAD_W / 2 * UNIT, HEAD_H / 2 * UNIT, fill=hex(TORSO), stroke=hex(OUTLINE)).move_to(
            p(0, HEAD_H / 2)
        )
        for seg in segments:
            ball(*seg["start"], JOINT_R[seg["name"]])
    canvas.fit(bounds=view, crop=False)
    return canvas


@app.command
def figure(
    pose: Annotated[str, "Pose name (see --list-poses)"] = "t",
    out: Annotated[str, "Output path (.png or .svg)"] = "figure.png",
    size: Annotated[int, "Square canvas side in pixels"] = 1024,
    list_poses: Annotated[bool, "Print the available poses and exit"] = False,
):
    """Draw a humanoid mannequin in a given pose, as a template sheet.

    Builds a figure from balls (joints, head) and rectangles (limbs, torso)
    with adult proportions of 7.5 heads, poses it by forward kinematics, and
    writes a square image on a white background. The figure's left limbs are
    light grey and its right limbs dark grey, so a model can tell the sides
    apart. Pass the result as a ref to `mosaico gen` to get a character in
    that pose. Local only: no API call, no --save needed.
    """
    if list_poses:
        for name in POSES:
            print(name)
        return
    if pose not in POSES:
        m.fail(f"unknown pose {pose!r}; available: {', '.join(POSES)}")
    if Path(out).suffix.lower() not in (".png", ".svg"):
        m.fail(f"--out must end in .png or .svg, got {out!r}")

    canvas = build_canvas(pose, size)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print(f"wrote {out} ({size}×{size}, pose {pose})")
