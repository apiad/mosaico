"""mosaico figure — draw a posed human silhouette as a template sheet.

The output is meant to be passed as a ref image to `mosaico gen` / `render`
so the generated character lands in the same pose. No API calls: the figure
is computed locally and drawn with tesserax.

Model:
- Every length is a fraction of stature (H = 1), taken from the means of
  ANSUR II (US Army anthropometric survey, 2012; 4,082 men and 1,986 women;
  tools.openlab.psu.edu/publicData). Head height (vertex to chin, 0.130 H)
  comes from Drillis & Contini (1966), which ANSUR II does not measure.
- Limb widths are circumference / pi: the diameter of a round limb.
- The arm segments are scaled so the T-pose reaches the measured arm span;
  summed end to end they overshoot it by about 12%.
- A pose is a set of limb angles. Each limb is a chain of segments; the
  first angle is measured from straight down, the rest are relative bends
  of each segment against its parent. Positive angles point away from the
  body's midline, so one pose value works for both sides.
- The figure faces the viewer. Coordinates are SVG-style: y grows downward,
  the top of the head is y = 0 and the soles are y = 1.
- The whole body is one flat colour, so the image model reads it as a shape
  and copies only the pose.

Discoverability:
    mosaico figure --tour
    mosaico figure --list-poses
    mosaico figure --out t-pose.png
    mosaico figure --pose t --body female --out t-pose.svg --size 1536
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated

import microcli as m

from . import app

HEAD_HEIGHT = 0.130  # Drillis & Contini (1966), vertex to chin

# ANSUR II means as fractions of stature. Heights are above the floor.
BODIES: dict[str, dict[str, float]] = {
    "male": {
        "cervicale_height": 0.864,
        "acromial_height": 0.820,
        "axilla_height": 0.757,
        "waist_height": 0.602,
        "trochanter_height": 0.513,
        "crotch_height": 0.482,
        "knee_height": 0.280,  # lateral femoral epicondyle
        "ankle_height": 0.042,  # lateral malleolus
        "head_breadth": 0.088,
        "neck_width": 0.072,
        "biacromial_breadth": 0.237,
        "chest_breadth": 0.165,
        "waist_breadth": 0.186,
        "hip_breadth": 0.197,
        "span": 1.033,
        "upper_arm": 0.191,  # acromion to radiale
        "forearm": 0.153,  # radiale to stylion
        "hand": 0.110,
        "hand_breadth": 0.050,
        "foot_breadth": 0.058,
        "biceps_width": 0.065,
        "forearm_width": 0.056,
        "wrist_width": 0.032,
        "knee_width": 0.074,  # lower thigh
        "calf_width": 0.071,
        "ankle_width": 0.042,
    },
    "female": {
        "cervicale_height": 0.857,
        "acromial_height": 0.820,
        "axilla_height": 0.761,
        "waist_height": 0.602,
        "trochanter_height": 0.519,
        "crotch_height": 0.480,
        "knee_height": 0.286,
        "ankle_height": 0.039,
        "head_breadth": 0.091,
        "neck_width": 0.065,
        "biacromial_breadth": 0.224,
        "chest_breadth": 0.165,
        "waist_breadth": 0.184,
        "hip_breadth": 0.217,
        "span": 1.020,
        "upper_arm": 0.191,
        "forearm": 0.148,
        "hand": 0.111,
        "hand_breadth": 0.048,
        "foot_breadth": 0.057,
        "biceps_width": 0.060,
        "forearm_width": 0.052,
        "wrist_width": 0.030,
        "knee_width": 0.078,
        "calf_width": 0.073,
        "ankle_width": 0.042,
    },
}

POSES: dict[str, dict[str, tuple[float, ...]]] = {
    "t": {
        "arm_l": (90, 0, 0),
        "arm_r": (90, 0, 0),
        "leg_l": (3, -3, 0),
        "leg_r": (3, -3, 0),
    },
}

UNIT = 1000.0  # SVG units per stature
BACKGROUND = "#ffffff"
FILL = "#000000"


def _chains(b: dict[str, float]) -> dict[str, list[tuple[str, float, list]]]:
    """Limb chains: (segment, length, width profile) from the root joint out.

    A width profile is a list of (t, width) with t in [0, 1] along the
    segment, so a limb can taper or bulge.
    """
    reach = b["span"] / 2 - b["biacromial_breadth"] / 2
    k = reach / (b["upper_arm"] + b["forearm"] + b["hand"])
    hip_y, knee_y, ankle_y = (
        1 - b["trochanter_height"],
        1 - b["knee_height"],
        1 - b["ankle_height"],
    )
    return {
        "arm": [
            ("upper_arm", k * b["upper_arm"],
             [(0, b["biceps_width"]), (1, b["forearm_width"])]),
            ("forearm", k * b["forearm"],
             [(0, b["forearm_width"]), (1, b["wrist_width"])]),
            ("hand", k * b["hand"],
             [(0, b["hand_breadth"]), (1, b["hand_breadth"])]),
        ],
        "leg": [
            ("thigh", knee_y - hip_y,
             [(0, b["hip_breadth"] / 2), (1, b["knee_width"])]),
            ("shin", ankle_y - knee_y,
             [(0, b["knee_width"]), (0.3, b["calf_width"]), (1, b["ankle_width"])]),
            ("foot", 1 - ankle_y,
             [(0, b["ankle_width"]), (1, b["foot_breadth"])]),
        ],
    }


def _roots(b: dict[str, float]) -> dict[str, tuple[float, float]]:
    """Root joint of each limb on the figure's left side (x > 0)."""
    return {
        # Top edge of the arm level with the acromion.
        "arm": (b["biacromial_breadth"] / 2,
                1 - b["acromial_height"] + b["biceps_width"] / 2),
        # Thighs fill the hip breadth side by side.
        "leg": (b["hip_breadth"] / 4, 1 - b["trochanter_height"]),
    }


def skeleton(pose: dict[str, tuple[float, ...]], body: str = "male") -> list[dict]:
    """Forward kinematics: pose angles -> limb segments with endpoints.

    Returns one dict per segment with `name`, `side` (+1 = figure's left,
    drawn on the viewer's right), `start`, `end` (in stature units) and
    `profile`. Torso and head are fixed; only the limbs move.
    """
    b = BODIES[body]
    chains, roots = _chains(b), _roots(b)
    segments = []
    for limb, chain in chains.items():
        for side, suffix in ((+1, "l"), (-1, "r")):
            angles = pose[f"{limb}_{suffix}"]
            if len(angles) != len(chain):
                raise ValueError(
                    f"{limb}_{suffix} needs {len(chain)} angles, got {len(angles)}"
                )
            rx, y = roots[limb]
            x, theta = side * rx, 0.0
            for (name, length, profile), angle in zip(chain, angles):
                theta += angle
                rad = math.radians(theta)
                nx = x + side * length * math.sin(rad)
                ny = y + length * math.cos(rad)
                segments.append(
                    {"name": name, "side": side, "start": (x, y),
                     "end": (nx, ny), "profile": profile}
                )
                x, y = nx, ny
    return segments


def _limb_outline(seg: dict) -> list[tuple[float, float]]:
    """Polygon around a segment, following its width profile."""
    (ax, ay), (bx, by) = seg["start"], seg["end"]
    length = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / length, (by - ay) / length
    nx, ny = -uy, ux
    left, right = [], []
    for t, w in seg["profile"]:
        cx, cy = ax + ux * length * t, ay + uy * length * t
        left.append((cx + nx * w / 2, cy + ny * w / 2))
        right.append((cx - nx * w / 2, cy - ny * w / 2))
    return left + right[::-1]


def _torso_outline(b: dict[str, float]) -> list[tuple[float, float]]:
    """Neck base, shoulders, armpits, waist, hips, crotch; mirrored."""
    half = [
        (b["neck_width"] / 2, 1 - b["cervicale_height"]),
        (b["biacromial_breadth"] / 2, 1 - b["acromial_height"]),
        (b["chest_breadth"] / 2, 1 - b["axilla_height"]),
        (b["waist_breadth"] / 2, 1 - b["waist_height"]),
        (b["hip_breadth"] / 2, 1 - b["trochanter_height"]),
        (b["hip_breadth"] / 2, 1 - b["crotch_height"]),
        (0.0, 1 - b["crotch_height"]),
    ]
    return half + [(-x, y) for x, y in reversed(half[:-1])]


def silhouette(pose_name: str, body: str = "male") -> dict:
    """All shapes of the figure, in stature units.

    Returns `polygons` (lists of points), `circles` ((x, y, r) joint caps
    that round off the limb ends) and `ellipses` ((x, y, rx, ry), the head).
    """
    b = BODIES[body]
    segments = skeleton(POSES[pose_name], body)
    neck_top = HEAD_HEIGHT * 0.8
    neck = [
        (-b["neck_width"] / 2, neck_top),
        (b["neck_width"] / 2, neck_top),
        (b["neck_width"] / 2, 1 - b["cervicale_height"] + 0.01),
        (-b["neck_width"] / 2, 1 - b["cervicale_height"] + 0.01),
    ]
    polygons = [_torso_outline(b), neck] + [_limb_outline(s) for s in segments]
    circles = []
    for s in segments:
        if s["name"] in ("upper_arm", "forearm", "hand", "shin", "foot"):
            circles.append((*s["start"], s["profile"][0][1] / 2))
    head = (0.0, HEAD_HEIGHT / 2, b["head_breadth"] / 2, HEAD_HEIGHT / 2)
    return {"polygons": polygons, "circles": circles, "ellipses": [head]}


def build_canvas(pose_name: str, size: int, body: str = "male", margin: float = 0.05):
    """Draw the posed silhouette centred on a square `size`×`size` canvas."""
    from tesserax import Canvas, Circle, Ellipse, Path as TPath, Point, Rect
    from tesserax.color import hex
    from tesserax.core import Bounds

    shapes = silhouette(pose_name, body)
    xs = [x for poly in shapes["polygons"] for x, _ in poly]
    ys = [y for poly in shapes["polygons"] for _, y in poly] + [0.0]
    xs += [x + s * r for x, _, r in shapes["circles"] for s in (-1, 1)]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    side_len = max(x1 - x0, y1 - y0) * (1 + 2 * margin)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    view = Bounds(
        (cx - side_len / 2) * UNIT, (cy - side_len / 2) * UNIT,
        side_len * UNIT, side_len * UNIT,
    )
    fill = hex(FILL)

    canvas = Canvas(size, size)
    with canvas:
        Rect(view.width, view.height, fill=hex(BACKGROUND), stroke=hex(BACKGROUND)).move_to(
            Point(view.x + view.width / 2, view.y + view.height / 2)
        )
        for poly in shapes["polygons"]:
            path = TPath(fill=fill, stroke=fill).jump_to(poly[0][0] * UNIT, poly[0][1] * UNIT)
            for x, y in poly[1:]:
                path.line_to(x * UNIT, y * UNIT)
            path.close()
        for x, y, r in shapes["circles"]:
            Circle(r * UNIT, fill=fill, stroke=fill).move_to(Point(x * UNIT, y * UNIT))
        for x, y, rx, ry in shapes["ellipses"]:
            Ellipse(rx * UNIT, ry * UNIT, fill=fill, stroke=fill).move_to(Point(x * UNIT, y * UNIT))
    canvas.fit(bounds=view, crop=False)
    return canvas


@app.command
def figure(
    pose: Annotated[str, "Pose name (see --list-poses)"] = "t",
    body: Annotated[str, "Body proportions: male or female (ANSUR II means)"] = "male",
    out: Annotated[str, "Output path (.png or .svg)"] = "figure.png",
    size: Annotated[int, "Square canvas side in pixels"] = 1024,
    list_poses: Annotated[bool, "Print the available poses and exit"] = False,
):
    """Draw a human silhouette in a given pose, as a template sheet.

    Builds the figure from measured adult proportions (ANSUR II means), poses
    it by forward kinematics, and writes one flat black shape on a white
    square. Pass the result as a ref to `mosaico gen` to get a character in
    that pose. Local only: no API call, no --save needed.
    """
    if list_poses:
        for name in POSES:
            print(name)
        return
    if pose not in POSES:
        m.fail(f"unknown pose {pose!r}; available: {', '.join(POSES)}")
    if body not in BODIES:
        m.fail(f"unknown body {body!r}; available: {', '.join(BODIES)}")
    if Path(out).suffix.lower() not in (".png", ".svg"):
        m.fail(f"--out must end in .png or .svg, got {out!r}")

    canvas = build_canvas(pose, size, body)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print(f"wrote {out} ({size}×{size}, pose {pose}, body {body})")
