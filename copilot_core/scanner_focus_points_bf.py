# Synced from the private co-pilot by tools/sync_from_private.py - change it there, then re-sync.
"""BRIGHTFIELD ONLY — choose focus points ON the cells inside the disc.

(Fluorescence and the simulator keep the fixed patterns in
scanner_focus_placement.py; the two are never mixed.)

HDScanner's own points are a grid over the SQUARE scan box, but the TCT sample
is a ROUND disc, so the corner points land on bare glass and focus wrong. Here:

  1. the disc CIRCLE comes from scanner_find_samples_bf.find_disc (not the
     square box) and is shrunk to SAFE_FRACTION — the disc edge is the least
     reliable place to focus;
  2. a CELL MAP marks the small dark dots (cells): pixels clearly darker than
     their smoothed surroundings. Big dark blobs (thick clumps / debris) are
     avoided — their top is not the cell plane;
  3. candidate spots = spots inside the safe circle with enough cells nearby;
  4. ANY number of points: an ideal, evenly spread layout in the safe circle
     (1 = centre; 2-6 = a ring, so 3 points make a triangle for the slide's
     tilt, never a line; 7+ = an even sunflower spiral), then each ideal spot
     is moved to the nearest good cell spot.

Sizes are tuned on Scanner A/Scanner B previews (1119 x 373) and scale with the
picture width. Pillow only. Read-only: never talks to the scanner.

    python scanner_focus_points_bf.py [preview.tif] [count]
"""
import math
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from scanner_find_samples_bf import MIN_EDGE_SCORE, TUNED_WIDTH, find_disc

SAFE_FRACTION = 0.85     # points stay within 85 % of the disc radius
BACKGROUND_BLUR = 8      # px — the "surroundings" a cell is compared with
DOT_DARKNESS = 10        # a cell pixel is this much darker than its surroundings
BLOB_BACKGROUND = 20     # px — wider surroundings, so a whole clump shows as dark
BLOB_BLUR = 3            # px — darkness that survives this blur is a blob, not a dot
BLOB_DARKNESS = 20       # clumps 23-45, ordinary cells mostly < 10 (Scanner A slide 2)
BLOB_KEEP_AWAY = 14      # px (~one 20X field) — no point this close to a blob
CELL_WINDOW = 10         # px — radius in which cells are counted around a spot
GRID_STEP = 3            # px between candidate spots
MIN_CELL_SHARE = 0.4     # a spot needs >= 40 % of the disc's typical cell count
FIELD_PX = 12            # one 20X camera field (~0.6 mm) — closer points are pointless
BOX_MARGIN = 6           # px (~half a field) — points stay this far inside the scan box


def safe_disc(path):
    """(cx, cy, r_safe, r) in preview pixels, or None when no disc is seen."""
    score, cx, cy, r = find_disc(path)
    if score < MIN_EDGE_SCORE:
        return None
    return cx, cy, r * SAFE_FRACTION, r


def cell_maps(img, k):
    """(dots, blobs) as 0/1 grids [x][y]: small dark dots, and big dark blobs."""
    L = img.convert("L")
    bg = L.filter(ImageFilter.BoxBlur(max(1, round(BACKGROUND_BLUR * k))))
    dark = ImageChops.subtract(bg, L)          # >0 where darker than surroundings
    wide = L.filter(ImageFilter.BoxBlur(max(1, round(BLOB_BACKGROUND * k))))
    dark_smooth = ImageChops.subtract(wide, L).filter(
        ImageFilter.BoxBlur(max(1, round(BLOB_BLUR * k))))
    W, H = img.size
    d, ds = dark.load(), dark_smooth.load()
    blobs = [[1 if ds[x, y] >= BLOB_DARKNESS else 0 for y in range(H)] for x in range(W)]
    dots = [[1 if d[x, y] >= DOT_DARKNESS and not blobs[x][y] else 0 for y in range(H)]
            for x in range(W)]                 # a clump's pixels are not cells
    return dots, blobs


def _integral(grid, W, H):
    """Summed-area table, so a window's count is 4 lookups."""
    S = [[0] * (H + 1) for _ in range(W + 1)]
    for x in range(W):
        col, prev, run = S[x + 1], S[x], 0
        g = grid[x]
        for y in range(H):
            run += g[y]
            col[y + 1] = prev[y + 1] + run
    return S


def _count(S, W, H, x, y, r):
    x0, y0 = max(0, x - r), max(0, y - r)
    x1, y1 = min(W, x + r + 1), min(H, y + r + 1)
    return S[x1][y1] - S[x0][y1] - S[x1][y0] + S[x0][y0]


def candidate_spots(path, box_px=None):
    """Spots inside the safe circle that sit on cells and away from blobs.
    With box_px = [x, y, w, h] (preview pixels) the spots must ALSO be inside
    that scan box, BOX_MARGIN in from its edges.

    Returns (disc, [(x, y, cells)], k) or (None, [], k) when no disc is seen."""
    img = Image.open(path).convert("RGB")
    W, H = img.size
    k = W / TUNED_WIDTH
    disc = safe_disc(path)
    if disc is None:
        return None, [], k
    cx, cy, rs, _ = disc
    dots, blobs = cell_maps(img, k)
    Sd, Sb = _integral(dots, W, H), _integral(blobs, W, H)
    win, keep, step = round(CELL_WINDOW * k), round(BLOB_KEEP_AWAY * k), max(1, round(GRID_STEP * k))
    if box_px:
        bx, by, bw, bh = box_px
        m = BOX_MARGIN * k
        x_lo, x_hi, y_lo, y_hi = bx + m, bx + bw - m, by + m, by + bh - m

    spots = []
    for x in range(round(cx - rs), round(cx + rs) + 1, step):
        for y in range(round(cy - rs), round(cy + rs) + 1, step):
            if (x - cx) ** 2 + (y - cy) ** 2 > rs * rs or not (0 <= x < W and 0 <= y < H):
                continue
            if box_px and not (x_lo <= x <= x_hi and y_lo <= y <= y_hi):
                continue                          # outside the scan box
            if _count(Sb, W, H, x, y, keep):
                continue                          # on / next to a clump
            spots.append((x, y, _count(Sd, W, H, x, y, win)))
    if not spots:
        return disc, [], k
    typical = sorted(c for _, _, c in spots)[len(spots) // 2]   # median cell count
    need = max(1, typical * MIN_CELL_SHARE)
    return disc, [s for s in spots if s[2] >= need], k


RING_FRACTION = 0.8      # small counts: ring at 80 % of the safe radius
GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))


def ideal_layout(count, cx, cy, rx, ry):
    """Evenly spread spots in the allowed oval (before looking at the cells).
    rx = ry = the safe radius when there is no scan box (a circle)."""
    if count == 1:
        return [(cx, cy)]
    if count <= 6:                               # ring, first point at the top
        return [(cx + rx * RING_FRACTION * math.sin(2 * math.pi * i / count),
                 cy - ry * RING_FRACTION * math.cos(2 * math.pi * i / count)) for i in range(count)]
    # sunflower spiral: equal area per point, the outermost near the rim
    return [(cx + rx * math.sqrt((i + 0.5) / count) * math.cos(i * GOLDEN_ANGLE),
             cy + ry * math.sqrt((i + 0.5) / count) * math.sin(i * GOLDEN_ANGLE))
            for i in range(count)]


def choose_points(spots, ideal, snap_px, min_gap_px):
    """Move each ideal spot to a good cell spot: the most cells within snap_px,
    else the nearest one; never closer than min_gap_px to a point already chosen."""
    chosen = []
    for ix, iy in ideal:
        free = [s for s in spots
                if all(math.hypot(s[0] - c[0], s[1] - c[1]) >= min_gap_px for c in chosen)]
        if not free:
            break
        near = [s for s in free if math.hypot(s[0] - ix, s[1] - iy) <= snap_px]
        pick = (max(near, key=lambda s: (s[2], -math.hypot(s[0] - ix, s[1] - iy))) if near
                else min(free, key=lambda s: math.hypot(s[0] - ix, s[1] - iy)))
        chosen.append(pick)
    return chosen


def propose_bf_points(path, count, box_px=None):
    """Choose `count` (any number >= 1) focus points on the cells inside the disc
    (and, with box_px = [x, y, w, h], inside that scan box too).

    Returns {ok, disc_px{cx,cy,r,r_safe}, box_px, points_px[[x,y]], min_spacing_px, warning}
    or {ok: False, error}."""
    if count < 1:
        return {"ok": False, "error": "count must be at least 1."}
    disc, spots, k = candidate_spots(path, box_px)
    if disc is None:
        return {"ok": False, "error": "No sample disc found in the preview — not guessing focus points."}
    if not spots:
        where = "inside the scan box" if box_px else "inside it"
        return {"ok": False, "error": f"Disc found but no cells seen {where} — not guessing focus points."}
    cx, cy, rs, r = disc
    if box_px:          # the allowed area = disc ∩ box: fit the oval to its spots
        xs, ys = [s[0] for s in spots], [s[1] for s in spots]
        ox, oy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        rx, ry = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
    else:
        ox, oy, rx, ry = cx, cy, rs, rs
    ideal = ideal_layout(count, ox, oy, rx, ry)
    # snap no farther than a quarter of the ideal spacing (so the layout keeps its shape)
    ideal_gap = math.sqrt(math.pi * rx * ry / count)
    pts = choose_points(spots, ideal, snap_px=max(3 * k, min(ideal_gap / 4, 15 * k)),
                        min_gap_px=FIELD_PX * k / 2)
    spacing = min((math.hypot(a[0] - b[0], a[1] - b[1])
                   for i, a in enumerate(pts) for b in pts[i + 1:]), default=None)
    warning = None
    if len(pts) < count:
        warning = f"Only {len(pts)} distinct cell spots available (asked for {count})."
    elif spacing is not None and spacing < FIELD_PX * k:
        warning = (f"{count} points are closer than one camera field (~0.6 mm) — "
                   "extra points add scan time but no information.")
    return {"ok": True,
            "disc_px": {"cx": round(cx), "cy": round(cy), "r": round(r), "r_safe": round(rs)},
            "box_px": box_px,
            "points_px": [[x, y] for x, y, _ in pts],
            "cells_px": [c for _, _, c in pts],
            "min_spacing_px": None if spacing is None else round(spacing, 1),
            "warning": warning}


def draw_proposal(path, result, out_path):
    """Picture for the operator: disc (blue), safe zone (dashed green), scan box
    (solid green), numbered points."""
    img = Image.open(path).convert("RGB")
    d = ImageDraw.Draw(img)
    c = result["disc_px"]
    cx, cy = c["cx"], c["cy"]
    d.ellipse([cx - c["r"], cy - c["r"], cx + c["r"], cy + c["r"]], outline=(0, 90, 255), width=2)
    rs = c["r_safe"]
    for a in range(0, 360, 8):                               # dashed safe circle
        t0, t1 = math.radians(a), math.radians(a + 4)
        d.line([cx + rs * math.cos(t0), cy + rs * math.sin(t0),
                cx + rs * math.cos(t1), cy + rs * math.sin(t1)], fill=(0, 150, 0), width=1)
    if result.get("box_px"):                                 # the scan box (solid green)
        x, y, w, h = result["box_px"]
        d.rectangle([x, y, x + w, y + h], outline=(0, 170, 0), width=2)
    for n, (x, y) in enumerate(result["points_px"], 1):
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 0, 0), width=2)
        d.text((x + 7, y - 7), str(n), fill=(200, 0, 0))
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    import json
    path = sys.argv[1] if len(sys.argv) > 1 else "previews_bf.tif"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    res = propose_bf_points(path, n)
    print(json.dumps(res, indent=2))
    if res.get("ok"):
        print("saved", draw_proposal(path, res, "_focus_bf_proposal.png"))
