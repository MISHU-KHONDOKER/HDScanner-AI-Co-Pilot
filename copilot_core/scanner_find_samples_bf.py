# Synced from the private co-pilot by tools/sync_from_private.py - change it there, then re-sync.
"""BRIGHTFIELD ONLY — find the sample in a Brightfield slide preview.

(Fluorescence and the simulator use scanner_find_samples_fluo.py; the two are never
mixed — the chat mode picks one, see scanner_sample_area.find_samples_for_mode.)

DISC EDGE method — on Brightfield TCT slides the cells sit in a round disc
(~21 mm) left of the printed arc / XT logo; the label is on the right. The stain
is faint, so colour is unreliable: the preview has a colour cast that fades
left -> right (on faint slides the right half of the disc is no bluer than the
glass), and the camera differs between scanners. What IS visible on every slide
is the disc's EDGE: the disc is slightly DARKER inside than the glass just
outside it. So:

  1. look only at the left part of the preview (not the label),
  2. try circles of disc size at many positions; for each, compare brightness
     just outside vs just inside the circle all the way round (each point
     capped, so strong edges like the holder or the printed arc cannot win on
     their own — and those are darker OUTSIDE, which counts against them),
  3. the best circle is the disc; if its edge score is too low there is no
     disc -> report nothing (never guess).

History: 2026-09-28 "small dark dots" picked the XT logo; 2026-09-29 "blue disc"
(bluer than glass) worked on clear slides but cut off the right side of faint
slide 1 and was fooled by the holder. Tuned on Scanner B previews
(1119 x 373); sizes scale with the picture width. Pillow only. Read-only.

    python scanner_find_samples_bf.py [preview.tif]
"""
import math
import sys

from PIL import Image, ImageFilter

TUNED_WIDTH = 1119
ZONE_FRACTION = 0.55          # only the left 55% of the preview (label is on the right)
RADIUS_PX = range(140, 171, 5)   # disc radius to try (measured 155-158 px, ~21 mm across)
EDGE_GAP_PX = 5               # compare brightness this far outside vs inside the circle
EDGE_CAP = 4                  # cap per point, so one strong edge cannot dominate
ANGLES = 90                   # points round the circle
MIN_EDGE_SCORE = 1.6          # real discs 2.2-3.8; no disc (blank, simulator) 0.6-1.1


def _edge_score(L, W, H, cx, cy, r, gap, circle):
    s = n = 0
    for c, sn in circle:
        xo, yo = cx + (r + gap) * c, cy + (r + gap) * sn
        xi, yi = cx + (r - gap) * c, cy + (r - gap) * sn
        if 0 <= xo < W and 0 <= yo < H and 0 <= xi < W and 0 <= yi < H:
            diff = L[int(xo), int(yo)] - L[int(xi), int(yi)]   # outside brighter = +
            s += max(-EDGE_CAP, min(EDGE_CAP, diff))
            n += 1
    # Most of the circle must be inside the picture; divide by ALL points so a
    # circle half outside the picture cannot score high.
    return s / len(circle) if n > len(circle) * 0.6 else -99


def find_disc(path):
    """Best disc-sized circle as (score, cx, cy, r) in preview pixels."""
    img = Image.open(path).convert("RGB")
    W0, H0 = img.size
    k = W0 / TUNED_WIDTH
    zone = img.crop((0, 0, int(W0 * ZONE_FRACTION), H0))
    W, H = zone.size
    L = zone.convert("L").filter(ImageFilter.BoxBlur(max(1, round(2 * k)))).load()
    circle = [(math.cos(2 * math.pi * a / ANGLES), math.sin(2 * math.pi * a / ANGLES))
              for a in range(ANGLES)]
    gap = EDGE_GAP_PX * k
    score = lambda cx, cy, r: _edge_score(L, W, H, cx, cy, r, gap, circle)

    # Coarse search over the left part of the slide, then refine around the best.
    step = max(1, round(4 * k))
    best = max((score(cx, cy, r * k), cx, cy, r * k)
               for r in RADIUS_PX
               for cy in range(round(0.3 * H0), round(0.7 * H0) + 1, step)
               for cx in range(round(0.12 * W0), min(W, round(0.45 * W0)) + 1, step))
    _, bx, by, br = best
    return max((score(cx, cy, br + dr * k), cx, cy, br + dr * k)
               for dr in range(-4, 5)
               for cy in range(by - step, by + step + 1)
               for cx in range(bx - step, bx + step + 1))


def find_samples(path):
    """Return [{x, y, w, h, area, method, score}] in PREVIEW PIXELS — the disc's
    square box — or [] when no disc edge is seen (never guesses)."""
    sc, cx, cy, r = find_disc(path)
    if sc < MIN_EDGE_SCORE:
        return []
    with Image.open(path) as im:
        W0, H0 = im.size
    x0, y0 = max(0, round(cx - r)), max(0, round(cy - r))
    x1, y1 = min(W0 - 1, round(cx + r)), min(H0 - 1, round(cy + r))
    return [{"x": x0, "y": y0, "w": x1 - x0 + 1, "h": y1 - y0 + 1,
             "area": round(math.pi * r * r), "method": "disc edge", "score": round(sc, 2)}]


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "previews_bf.tif"
    sc, cx, cy, r = find_disc(path)
    print(f"Best circle: centre ({cx},{cy}) radius {r:.0f}  edge score {sc:.2f} "
          f"(need >= {MIN_EDGE_SCORE})")
    found = find_samples(path)
    print(f"Found {len(found)} sample(s) in {path}:")
    for i, b in enumerate(found, 1):
        print(f"  #{i}: x={b['x']} y={b['y']} w={b['w']} h={b['h']}  "
              f"(area {b['area']} px, method: {b['method']})")
