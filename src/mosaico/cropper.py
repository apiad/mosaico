"""Content-aware grid sheet -> per-cell thumbnails.

Verbatim port of repos/enciclopedia/bin/cut-glosario (functions
`normalize_to_white`, `find_motif_bbox_in_cell`, and the per-cell crop
loop). The PIL-floodfill-RGB-not-L gotcha is preserved with its inline
comment.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def normalize_to_white(img_array: np.ndarray, bg_threshold: int = 18) -> np.ndarray:
    """Replace near-background pixels with pure white.

    Samples the average color of the four corners (10x10 patches) as the
    putative background, then replaces every pixel within Manhattan distance
    `bg_threshold` of that color with [255, 255, 255]. Watercolor edges of
    motifs stay intact; surrounding paper texture flattens to white.
    """
    h, w = img_array.shape[:2]
    corners = np.concatenate([
        img_array[0:10, 0:10].reshape(-1, 3),
        img_array[0:10, w - 10:w].reshape(-1, 3),
        img_array[h - 10:h, 0:10].reshape(-1, 3),
        img_array[h - 10:h, w - 10:w].reshape(-1, 3),
    ])
    bg = corners.mean(axis=0).astype(int)
    diff = np.abs(img_array.astype(int) - bg).max(axis=2)
    mask = diff < bg_threshold
    out = img_array.copy()
    out[mask] = [255, 255, 255]
    return out


def find_motif_bbox_in_cell(
    img_array: np.ndarray,
    cell_x0: int,
    cell_y0: int,
    cell_x1: int,
    cell_y1: int,
    content_threshold: int = 240,
    min_blob_pct: float = 2.0,
) -> tuple[tuple[int, int, int, int], np.ndarray] | None:
    """Find bbox + pixel mask of significant connected blobs in this cell.

    A motif may consist of more than one disjoint blob. The script:
      1. Builds a binary content mask.
      2. Iterates over content pixels INSIDE the nominal cell, and for each
         unvisited content pixel, runs a flood-fill from there to extract
         the entire connected blob.
      3. Keeps blobs whose area exceeds `min_blob_pct` of the cell area AND
         whose geometric center is inside the inner 80% of the cell.
      4. Returns the bbox of the union of the surviving blobs PLUS a boolean
         mask of those blob pixels.
    """
    h, w = img_array.shape[:2]
    is_content = (img_array < content_threshold).any(axis=2)
    if not is_content.any():
        return None

    # Build a binary mask as RGB (PIL's ImageDraw.floodfill silently no-ops
    # on mode 'L' images, so we work in RGB). 0 = content, 255 = background.
    mask = np.where(is_content, 0, 255).astype(np.uint8)
    rgb = np.stack([mask, mask, mask], axis=-1)
    img = Image.fromarray(rgb, mode="RGB")

    cell_area = max(1, (cell_x1 - cell_x0) * (cell_y1 - cell_y0))
    min_area = cell_area * min_blob_pct / 100.0

    margin_x = (cell_x1 - cell_x0) * 0.10
    margin_y = (cell_y1 - cell_y0) * 0.10
    inner_x0 = cell_x0 + margin_x
    inner_y0 = cell_y0 + margin_y
    inner_x1 = cell_x1 - margin_x
    inner_y1 = cell_y1 - margin_y

    blob_bboxes: list[tuple[int, int, int, int]] = []
    kept_markers: list[tuple[int, int]] = []
    marker_id = 0

    for y in range(max(0, cell_y0), min(h, cell_y1)):
        for x in range(max(0, cell_x0), min(w, cell_x1)):
            current = img.getpixel((x, y))
            if current != (0, 0, 0):
                continue
            marker_id += 1
            marker = (255, marker_id & 0xFF, (marker_id >> 8) & 0xFF)
            ImageDraw.floodfill(img, (x, y), marker, thresh=0)
            arr_after = np.array(img)
            blob_mask = (
                (arr_after[:, :, 0] == 255)
                & (arr_after[:, :, 1] == marker[1])
                & (arr_after[:, :, 2] == marker[2])
            )
            area = blob_mask.sum()
            if area < min_area:
                continue
            rows = np.any(blob_mask, axis=1)
            cols = np.any(blob_mask, axis=0)
            rmin, rmax = np.where(rows)[0][[0, -1]]
            cmin, cmax = np.where(cols)[0][[0, -1]]
            blob_cx = (cmin + cmax) / 2.0
            blob_cy = (rmin + rmax) / 2.0
            if not (inner_x0 <= blob_cx < inner_x1 and inner_y0 <= blob_cy < inner_y1):
                continue
            blob_bboxes.append((int(cmin), int(rmin), int(cmax) + 1, int(rmax) + 1))
            kept_markers.append((marker[1], marker[2]))

    if not blob_bboxes:
        return None

    x0 = min(b[0] for b in blob_bboxes)
    y0 = min(b[1] for b in blob_bboxes)
    x1 = max(b[2] for b in blob_bboxes)
    y1 = max(b[3] for b in blob_bboxes)

    arr_final = np.array(img)
    keep_mask = np.zeros((h, w), dtype=bool)
    for mg, mb in kept_markers:
        keep_mask |= (
            (arr_final[:, :, 0] == 255)
            & (arr_final[:, :, 1] == mg)
            & (arr_final[:, :, 2] == mb)
        )

    return (x0, y0, x1, y1), keep_mask


def cut_grid(
    sheet_path: Path,
    out_dir: Path,
    grid: tuple[int, int],
    cells: dict[str, dict] | None = None,
    pad_px: int = 12,
) -> list[Path]:
    """Cut a sheet into per-cell thumbnails. Returns list of written paths.

    `cells` shape:
        {slug: {row: int, col: int, rowspan: int = 1, colspan: int = 1}}
    If `cells is None`, defaults to `cell-rN-cM` for every grid cell.

    Cells with no detected content are skipped with a warning (returned list
    omits them).
    """
    rows, cols = grid
    img = Image.open(sheet_path).convert("RGB")
    arr = np.array(img)
    arr = normalize_to_white(arr)

    H, W = arr.shape[:2]
    cell_w = W / cols
    cell_h = H / rows

    out_dir.mkdir(parents=True, exist_ok=True)

    if cells is None:
        cells = {
            f"cell-r{r}-c{c}": {"row": r, "col": c}
            for r in range(rows) for c in range(cols)
        }

    written: list[Path] = []
    for slug, info in cells.items():
        r = info["row"]
        c = info["col"]
        rspan = info.get("rowspan", 1)
        cspan = info.get("colspan", 1)

        nominal_x0 = int(round(c * cell_w))
        nominal_y0 = int(round(r * cell_h))
        nominal_x1 = int(round((c + cspan) * cell_w))
        nominal_y1 = int(round((r + rspan) * cell_h))

        result = find_motif_bbox_in_cell(
            arr, nominal_x0, nominal_y0, nominal_x1, nominal_y1
        )
        if result is None:
            print(f"  WARNING: {slug}: no content found in cell — skipping")
            continue

        (bx0, by0, bx1, by1), keep_mask = result
        masked_arr = np.full_like(arr, 255)
        masked_arr[by0:by1, bx0:bx1] = arr[by0:by1, bx0:bx1]

        bx0 = max(0, bx0 - pad_px)
        by0 = max(0, by0 - pad_px)
        bx1 = min(W, bx1 + pad_px)
        by1 = min(H, by1 + pad_px)

        crop = Image.fromarray(masked_arr[by0:by1, bx0:bx1])
        out_path = out_dir / f"{slug}.jpg"
        crop.save(out_path, "JPEG", quality=92)
        written.append(out_path)

    return written
