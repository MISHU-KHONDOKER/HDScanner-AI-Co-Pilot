# Synced from the private co-pilot by tools/sync_from_private.py - change it there, then re-sync.
"""Phase 1 prototype — find the sample(s) in a slide preview image.

Two ways of seeing, tried in order:

1. COLOUR method — a sample is a connected blob of strongly COLOURED pixels
   (high saturation). Finds vivid stand-ins such as the simulator's magenta
   squares; ignores the beige glass, grey outlines and black label text.

2. SMALL DARK DOTS method (used when colour finds nothing) — real stained cells
   are pale, but in a preview they show up as MANY tiny, slightly darker,
   bluish dots packed close together. Keep only small dots (printed letters and
   slide edges are long strokes, so they drop out), measure how crowded the dots
   are, and take the most crowded area(s) as the sample. Tuned on one real TCT
   preview photo; sizes scale with the picture width.

Pillow only (no OpenCV on this machine). Read-only: never talks to the scanner.

    python scanner_find_samples_fluo.py [preview.tif]
"""
import sys
from collections import deque

from PIL import Image, ImageChops, ImageDraw, ImageFilter

DEFAULT_PREVIEW = r"CapturedImages/Preview#1.tif"

# Colour method
MIN_SATURATION = 80   # 0-255; beige glass is ~30, magenta ~255, real tissue ~40-80
MIN_BRIGHTNESS = 50    # skip near-black pixels (label text)
MIN_AREA_PX = 5000     # ignore small fragments (real sample is >100k px)

# Small-dark-dots method. Pixel sizes are for a picture 1120 px wide (the photo
# it was tuned on) and are scaled to the actual width.
DOTS_TUNED_WIDTH = 1120
DOT_DARKER_BY = 8        # a dot pixel is at least this much darker than its surroundings
DOT_MIN_SATURATION = 20  # ...and slightly coloured (cells ~39, grey logo ~27)
DOT_MIN_BRIGHTNESS = 60  # ...but not the black holder (~63)
DOT_MAX_SPAN_PX = 12     # a "small" dot is at most this wide/tall (letters are longer)
DOT_MAX_AREA_PX = 80
BACKGROUND_RADIUS_PX = 10
CROWD_RADIUS_PX = 18     # how far to look when measuring how crowded the dots are
CROWD_THRESHOLD = 8      # 0-255: blurred dot map above this = "crowded"
MIN_REGION_FRACTION = 0.15  # keep crowded areas at least 15% the size of the largest
# ...and at least 1% of the whole picture (~19 mm² of slide). Without this, a slide
# with NO sample still "finds" small patches around the slide edge / logo (0.5%);
# the real TCT cell circle is 8.8%. Limit: a sample smaller than this is missed.
MIN_REGION_IMAGE_FRACTION = 0.01


def _components(grid):
    """Yield each connected blob of True cells as a list of (x, y) (4-neighbour flood fill)."""
    H, W = len(grid), len(grid[0])
    seen = [[False] * W for _ in range(H)]
    for y0 in range(H):
        for x0 in range(W):
            if not grid[y0][x0] or seen[y0][x0]:
                continue
            q = deque([(x0, y0)])
            seen[y0][x0] = True
            pts = []
            while q:
                x, y = q.popleft()
                pts.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        q.append((nx, ny))
            yield pts


def _box(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {"x": min(xs), "y": min(ys), "w": max(xs) - min(xs) + 1,
            "h": max(ys) - min(ys) + 1, "area": len(pts)}


def _reading_order(boxes):
    # Group into rows by vertical centre, then left to right.
    boxes.sort(key=lambda b: (round((b["y"] + b["h"] / 2) / 50), b["x"]))
    return boxes


def find_samples_by_colour(img, min_area=MIN_AREA_PX, keep_pixels=False):
    """Colour method: blobs of strongly coloured pixels.
    keep_pixels=True: each box also gets "pixels" [(x, y)] — the sample itself."""
    W, H = img.size
    hsv = img.convert("HSV").load()
    mask = [[False] * W for _ in range(H)]
    for y in range(H):
        row = mask[y]
        for x in range(W):
            _, s, v = hsv[x, y]
            row[x] = s >= MIN_SATURATION and v >= MIN_BRIGHTNESS
    boxes = []
    for pts in _components(mask):
        if len(pts) >= min_area:
            b = _box(pts)
            if keep_pixels:
                b["pixels"] = pts
            boxes.append(b)
    for b in boxes:
        b["method"] = "colour"
    return _reading_order(boxes)


def find_samples_by_dots(img, keep_pixels=False):
    """Small-dark-dots method: the most crowded area(s) of tiny darker bluish dots.
    keep_pixels=True: each box also gets "pixels" [(x, y)] — the sample itself."""
    W, H = img.size
    k = W / DOTS_TUNED_WIDTH  # scale the tuned pixel sizes to this picture
    _, s, v = img.convert("HSV").split()

    # 1. Dark dots: pixels darker than their surroundings, slightly coloured, not black.
    surroundings = v.filter(ImageFilter.BoxBlur(max(1, round(BACKGROUND_RADIUS_PX * k))))
    darker = ImageChops.subtract(surroundings, v).load()
    S, V = s.load(), v.load()
    dots = [[darker[x, y] > DOT_DARKER_BY and S[x, y] >= DOT_MIN_SATURATION
             and V[x, y] > DOT_MIN_BRIGHTNESS for x in range(W)] for y in range(H)]

    # 2. Keep only SMALL dots (cells); long strokes (letters, edges) drop out.
    max_span = DOT_MAX_SPAN_PX * k
    max_area = DOT_MAX_AREA_PX * k * k
    small = Image.new("L", (W, H), 0)
    px = small.load()
    for pts in _components(dots):
        b = _box(pts)
        if 2 <= b["area"] <= max_area and max(b["w"], b["h"]) <= max_span:
            for x, y in pts:
                px[x, y] = 255

    # 3. How crowded: blur the small-dot map; crowded areas become bright.
    crowd = small.filter(ImageFilter.BoxBlur(max(1, round(CROWD_RADIUS_PX * k)))).load()
    crowded = [[crowd[x, y] > CROWD_THRESHOLD for x in range(W)] for y in range(H)]

    # 4. The biggest crowded area(s) = the sample.
    regions = []
    for pts in _components(crowded):
        if len(pts) >= MIN_REGION_IMAGE_FRACTION * W * H:
            b = _box(pts)
            if keep_pixels:
                b["pixels"] = pts
            regions.append(b)
    if not regions:
        return []
    largest = max(r["area"] for r in regions)
    keep = [r for r in regions if r["area"] >= MIN_REGION_FRACTION * largest]
    for b in keep:
        b["method"] = "small dark dots"
    return _reading_order(keep)


def find_samples(path, min_area=MIN_AREA_PX, keep_pixels=False):
    """Return sample boxes in PREVIEW PIXELS: [{x, y, w, h, area, method}], reading
    order (top row first, then left to right). Tries the colour method first; if it
    finds nothing, falls back to the small-dark-dots method for pale real stain.
    keep_pixels=True: each box also carries "pixels" [(x, y)] — the sample itself."""
    img = Image.open(path).convert("RGB")
    boxes = find_samples_by_colour(img, min_area, keep_pixels)
    if boxes:
        return boxes
    return find_samples_by_dots(img, keep_pixels)


def draw_boxes(path, boxes, out_path):
    img = Image.open(path).convert("RGB")
    d = ImageDraw.Draw(img)
    for i, b in enumerate(boxes, 1):
        d.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]], outline=(0, 160, 0), width=3)
        d.text((b["x"], b["y"] - 14), f"#{i}", fill=(0, 120, 0))
    img.save(out_path)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PREVIEW
    found = find_samples(path)
    print(f"Found {len(found)} sample(s) in {path}:")
    for i, b in enumerate(found, 1):
        print(f"  #{i}: x={b['x']} y={b['y']} w={b['w']} h={b['h']}  "
              f"(area {b['area']} px, method: {b['method']})")
