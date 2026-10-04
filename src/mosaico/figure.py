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
    mosaico figure --proportions disney --body female --out princess.png
    mosaico figure --proportions all --body all --labels --out sheet.png
"""

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
        "bideltoid_breadth": 0.291,
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
        "bideltoid_breadth": 0.277,
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

# Stylised proportion presets, applied on top of the measured body. Widths
# are in head heights, as figure-drawing canons give them. A missing key
# keeps the measured value, so "real" is the identity.
#   heads       total height in head heights
#   crotch      crotch height as a fraction of stature
#   shoulders   outer shoulder width (bideltoid), in heads
#   waist, hips breadths, in heads
#   limbs       limb and neck thickness, times the measured one
#   head_ratio  head width / head height
#   extremities hand and foot size, times the measured one
#   reach       hanging fingertips, as a fraction down the leg from the
#               crotch (measured: about 0.19; negative is above the crotch)
# Head counts follow published canons (Loomis's 8-head ideal, 8.5-9 heroic,
# 9-10 fashion, 7-8 anime, 2-3 chibi, about 6 heads at six years and 4-5 for
# a toddler). Widths outside "real" and the disney column are estimates.
_KIDS = {"shoulders": 1.7, "waist": 1.3, "hips": 1.3, "limbs": 1.05,
         "head_ratio": 0.82, "heads": 6.0, "crotch": 0.44}
PROPORTIONS: dict[str, dict[str, dict[str, float]]] = {
    "real": {"male": {}, "female": {}},
    "heroic": {
        "male": {"heads": 8.5, "crotch": 0.50, "shoulders": 2.8, "waist": 1.25,
                 "hips": 1.5, "limbs": 1.15, "head_ratio": 0.70, "extremities": 1.05},
        "female": {"heads": 8.5, "crotch": 0.50, "shoulders": 2.1, "waist": 1.0,
                   "hips": 1.75, "limbs": 0.95, "head_ratio": 0.70},
    },
    "disney": {
        "male": {"heads": 7.0, "crotch": 0.48, "shoulders": 3.0, "waist": 1.6,
                 "hips": 1.5, "limbs": 1.1, "head_ratio": 0.80, "extremities": 1.1},
        "female": {"heads": 6.5, "crotch": 0.48, "shoulders": 1.9, "waist": 0.85,
                   "hips": 1.7, "limbs": 0.8, "head_ratio": 0.80, "extremities": 0.8},
    },
    "anime": {
        "male": {"heads": 7.5, "crotch": 0.52, "shoulders": 2.2, "waist": 1.2,
                 "hips": 1.4, "limbs": 0.8, "head_ratio": 0.78, "extremities": 0.9},
        "female": {"heads": 7.5, "crotch": 0.52, "shoulders": 1.8, "waist": 0.95,
                   "hips": 1.6, "limbs": 0.75, "head_ratio": 0.78, "extremities": 0.85},
    },
    "fashion": {
        "male": {"heads": 9.0, "crotch": 0.54, "shoulders": 2.3, "waist": 1.2,
                 "hips": 1.4, "limbs": 0.8, "head_ratio": 0.68},
        "female": {"heads": 9.0, "crotch": 0.54, "shoulders": 1.9, "waist": 1.0,
                   "hips": 1.5, "limbs": 0.75, "head_ratio": 0.68, "extremities": 0.9},
    },
    "child": {"male": _KIDS, "female": _KIDS},
    "toddler": {
        sex: {"heads": 4.5, "crotch": 0.38, "shoulders": 1.5, "waist": 1.3,
              "hips": 1.25, "limbs": 1.4, "head_ratio": 0.88, "extremities": 1.1,
              "reach": 0.0}
        for sex in ("male", "female")
    },
    "chibi": {
        sex: {"heads": 2.5, "crotch": 0.30, "shoulders": 1.3, "waist": 1.1,
              "hips": 1.1, "limbs": 1.8, "head_ratio": 0.95, "extremities": 1.2,
              "reach": -0.15}
        for sex in ("male", "female")
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

_TORSO_HEIGHTS = ("cervicale_height", "acromial_height", "axilla_height",
                  "waist_height", "trochanter_height")
_LEG_HEIGHTS = ("knee_height", "ankle_height")
_LIMB_WIDTHS = ("neck_width", "biceps_width", "forearm_width", "wrist_width",
                "knee_width", "calf_width", "ankle_width")


def dims(body: str = "male", proportions: str = "real") -> dict[str, float]:
    """Body dimensions in stature units, re-proportioned by a style preset.

    Heights between chin and crotch are stretched linearly to fit the new
    torso, heights below the crotch to fit the new legs. Arms are resized so
    the hanging fingertips sit at the same fraction of the leg as measured.
    """
    b = dict(BODIES[body], head_height=HEAD_HEIGHT)
    # Arms reach the measured span in the T-pose; summed end to end the
    # segments overshoot it by about 11%.
    reach = b["span"] / 2 - b["biacromial_breadth"] / 2
    k = reach / (b["upper_arm"] + b["forearm"] + b["hand"])
    for seg in ("upper_arm", "forearm", "hand"):
        b[seg] *= k

    arm0 = b["upper_arm"] + b["forearm"] + b["hand"]
    root0 = 1 - b["acromial_height"] + b["biceps_width"] / 2
    leg0 = b["crotch_height"]
    fingertip = (root0 + arm0 - (1 - leg0)) / leg0  # fraction down the leg

    s = PROPORTIONS[proportions][body]
    h0, h = HEAD_HEIGHT, 1 / s.get("heads", 1 / HEAD_HEIGHT)
    c0, c = b["crotch_height"], s.get("crotch", b["crotch_height"])
    torso = ((1 - c) - h) / ((1 - c0) - h0)
    for key in _TORSO_HEIGHTS:
        b[key] = 1 - (h + ((1 - b[key]) - h0) * torso)
    for key in _LEG_HEIGHTS:
        b[key] *= c / c0
    b["crotch_height"], b["head_height"] = c, h

    ratio = s.get("head_ratio", b["head_breadth"] / h0)
    b["head_breadth"] = ratio * h
    if "shoulders" in s:
        widen = s["shoulders"] * h / b["bideltoid_breadth"]
        for key in ("biacromial_breadth", "bideltoid_breadth", "chest_breadth"):
            b[key] *= widen
    if "waist" in s:
        b["waist_breadth"] = s["waist"] * h
    if "hips" in s:
        b["hip_breadth"] = s["hips"] * h
    for key in _LIMB_WIDTHS:
        b[key] *= s.get("limbs", 1.0)
    root = 1 - b["acromial_height"] + b["biceps_width"] / 2
    arm = (1 - c) + s.get("reach", fingertip) * c - root
    for seg in ("upper_arm", "forearm", "hand"):
        b[seg] *= arm / arm0
    extremities = s.get("extremities", 1.0)
    b["hand"] *= extremities
    for key in ("hand_breadth", "foot_breadth"):
        b[key] *= extremities
    return b


def _chains(b: dict[str, float]) -> dict[str, list[tuple[str, float, list]]]:
    """Limb chains: (segment, length, width profile) from the root joint out.

    A width profile is a list of (t, width) with t in [0, 1] along the
    segment, so a limb can taper or bulge.
    """
    hip_y, knee_y, ankle_y = (
        1 - b["trochanter_height"],
        1 - b["knee_height"],
        1 - b["ankle_height"],
    )
    return {
        "arm": [
            ("upper_arm", b["upper_arm"],
             [(0, b["biceps_width"]), (1, b["forearm_width"])]),
            ("forearm", b["forearm"],
             [(0, b["forearm_width"]), (1, b["wrist_width"])]),
            ("hand", b["hand"],
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


def skeleton(
    pose: dict[str, tuple[float, ...]], body: str = "male", proportions: str = "real"
) -> list[dict]:
    """Forward kinematics: pose angles -> limb segments with endpoints.

    Returns one dict per segment with `name`, `side` (+1 = figure's left,
    drawn on the viewer's right), `start`, `end` (in stature units) and
    `profile`. Torso and head are fixed; only the limbs move.
    """
    b = dims(body, proportions)
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


def silhouette(pose_name: str, body: str = "male", proportions: str = "real") -> dict:
    """All shapes of the figure, in stature units.

    Returns `polygons` (lists of points), `circles` ((x, y, r) joint caps
    that round off the limb ends) and `ellipses` ((x, y, rx, ry), the head).
    """
    b = dims(body, proportions)
    segments = skeleton(POSES[pose_name], body, proportions)
    h = b["head_height"]
    neck_bottom = 1 - b["cervicale_height"] + 0.01
    neck = [
        (-b["neck_width"] / 2, h * 0.8),
        (b["neck_width"] / 2, h * 0.8),
        (b["neck_width"] / 2, neck_bottom),
        (-b["neck_width"] / 2, neck_bottom),
    ]
    polygons = [_torso_outline(b), neck] + [_limb_outline(s) for s in segments]
    circles = []
    for s in segments:
        if s["name"] in ("upper_arm", "forearm", "hand", "shin", "foot"):
            circles.append((*s["start"], s["profile"][0][1] / 2))
    head = (0.0, h / 2, b["head_breadth"] / 2, h / 2)
    return {"polygons": polygons, "circles": circles, "ellipses": [head]}


def _extent(shapes: dict) -> tuple[float, float, float, float]:
    xs = [x for poly in shapes["polygons"] for x, _ in poly]
    ys = [y for poly in shapes["polygons"] for _, y in poly] + [0.0]
    xs += [x + s * r for x, _, r in shapes["circles"] for s in (-1, 1)]
    xs += [x + s * rx for x, _, rx, _ in shapes["ellipses"] for s in (-1, 1)]
    return min(xs), max(xs), min(ys), max(ys)


def build_sheet(
    figures: list[tuple[str, str, str]],
    columns: int,
    size: int,
    labels: bool = False,
    margin: float = 0.05,
):
    """Draw (pose, body, proportions) figures on a grid, one per cell.

    Every figure has the same stature, so the sheet compares proportions.
    With one figure and no labels this is a single centred template. The
    canvas is `size` pixels per cell side.
    """
    from tesserax import Canvas, Circle, Ellipse, Path as TPath, Point, Rect, Text
    from tesserax.color import hex
    from tesserax.core import Bounds

    all_shapes = [silhouette(pose, body, prop) for pose, body, prop in figures]
    extents = [_extent(s) for s in all_shapes]
    label_h = 0.12 if labels else 0.0
    cell = max(max(x1 - x0, y1 - y0) for x0, x1, y0, y1 in extents) * (1 + 2 * margin)
    cell_h = cell + label_h
    rows = -(-len(figures) // columns)
    width, height = columns * cell, rows * cell_h
    fill = hex(FILL)

    scale = size / cell
    canvas = Canvas(width * scale, height * scale)
    with canvas:
        Rect(width * UNIT, height * UNIT, fill=hex(BACKGROUND), stroke=hex(BACKGROUND)).move_to(
            Point(width * UNIT / 2, height * UNIT / 2)
        )
        for i, (shapes, (x0, x1, y0, y1)) in enumerate(zip(all_shapes, extents)):
            row, col = divmod(i, columns)
            dx = col * cell + cell / 2 - (x0 + x1) / 2
            dy = row * cell_h + cell / 2 - (y0 + y1) / 2

            def pt(x: float, y: float) -> Point:
                return Point((x + dx) * UNIT, (y + dy) * UNIT)

            for poly in shapes["polygons"]:
                start = pt(*poly[0])
                path = TPath(fill=fill, stroke=fill).jump_to(start.x, start.y)
                for x, y in poly[1:]:
                    q = pt(x, y)
                    path.line_to(q.x, q.y)
                path.close()
            for x, y, r in shapes["circles"]:
                Circle(r * UNIT, fill=fill, stroke=fill).move_to(pt(x, y))
            for x, y, rx, ry in shapes["ellipses"]:
                Ellipse(rx * UNIT, ry * UNIT, fill=fill, stroke=fill).move_to(pt(x, y))
            if labels:
                pose, body, prop = figures[i]
                heads = 1 / dims(body, prop)["head_height"]
                Text(
                    f"{prop} · {body} · {heads:.1f} heads",
                    size=0.045 * UNIT, fill=hex("#374151"),
                ).move_to(Point((col * cell + cell / 2) * UNIT,
                                (row * cell_h + cell + label_h / 3) * UNIT))
    canvas.fit(bounds=Bounds(0, 0, width * UNIT, height * UNIT), crop=False)
    return canvas


def _names(value: str, table: dict, what: str) -> list[str]:
    names = list(table) if value == "all" else [v.strip() for v in value.split(",")]
    for name in names:
        if name not in table:
            m.fail(f"unknown {what} {name!r}; available: {', '.join(table)}, all")
    return names


@app.command
def figure(
    pose: Annotated[str, "Pose name (see --list-poses)"] = "t",
    body: Annotated[str, "male, female, a comma list, or all"] = "male",
    proportions: Annotated[
        str, "real, heroic, disney, anime, fashion, child, toddler, chibi; a comma list, or all"
    ] = "real",
    out: Annotated[str, "Output path (.png or .svg)"] = "figure.png",
    size: Annotated[int, "Pixels per figure cell side"] = 1024,
    labels: Annotated[bool, "Write the preset, body and head count under each figure"] = False,
    list_poses: Annotated[bool, "Print the available poses and exit"] = False,
):
    """Draw human silhouettes in a pose, as a template sheet.

    Builds each figure from measured adult proportions (ANSUR II means),
    re-proportions it with a style preset, poses it by forward kinematics,
    and writes flat black shapes on white. One body and one preset give a
    single square template; lists give a grid with one row per body and one
    column per preset, all at the same stature. Pass a single figure as a
    ref to `mosaico gen` to get a character in that pose. Local only: no API
    call, no --save needed.
    """
    if list_poses:
        for name in POSES:
            print(name)
        return
    if pose not in POSES:
        m.fail(f"unknown pose {pose!r}; available: {', '.join(POSES)}")
    bodies = _names(body, BODIES, "body")
    presets = _names(proportions, PROPORTIONS, "proportions")
    if Path(out).suffix.lower() not in (".png", ".svg"):
        m.fail(f"--out must end in .png or .svg, got {out!r}")

    figures = [(pose, b, p) for b in bodies for p in presets]
    canvas = build_sheet(figures, columns=len(presets), size=size, labels=labels)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print(f"wrote {out} ({int(canvas.width)}×{int(canvas.height)}, {len(figures)} figure(s))")
