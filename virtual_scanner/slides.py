"""Synthetic slide previews for the virtual scanner.

Drawn, never copied from a real scanner: a brightfield slide is light glass with
a slightly darker round sample disc full of small dark cells (what the real
brightfield finder looks for); a fluorescence / simulator slide is beige glass
with a saturated sample patch.
"""
import math
import random

from PIL import Image, ImageDraw

BF_SIZE = (1119, 373)        # the size the brightfield finder is tuned on
FLUO_SIZE = (1500, 500)
DISC = (300, 186, 155)       # brightfield sample disc: centre x, y, radius (px)
FLUO_SQUARE = (700, 200, 100, 100)

# Slide kinds the virtual loader can hold.
KINDS = ("clear", "faint", "empty")


def brightfield(path, kind="clear", seed=1):
    rnd = random.Random(seed)
    W, H = BF_SIZE
    glass = 200
    img = Image.new("RGB", (W, H), (glass, glass, glass))
    d = ImageDraw.Draw(img)
    cx, cy, r = DISC
    if kind in ("clear", "faint"):
        contrast = 6 if kind == "clear" else 1
        inside = glass - contrast
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(inside, inside, inside + 4))
        if kind == "clear":
            for _ in range(2500):
                a, rr = rnd.uniform(0, 2 * math.pi), r * math.sqrt(rnd.random()) * 0.95
                x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
                v = inside - 40
                d.ellipse([x - 1, y - 1, x + 1, y + 1], fill=(v, v, v + 10))
    img.save(path)
    return path


def fluorescence(path, kind="clear"):
    img = Image.new("RGB", FLUO_SIZE, (225, 215, 190))
    if kind == "clear":
        x, y, w, h = FLUO_SQUARE
        ImageDraw.Draw(img).rectangle([x, y, x + w - 1, y + h - 1], fill=(230, 0, 230))
    elif kind == "faint":
        x, y, w, h = FLUO_SQUARE
        ImageDraw.Draw(img).rectangle([x, y, x + w - 1, y + h - 1], fill=(228, 205, 200))
    img.save(path)
    return path


def draw(path, mode, kind):
    return brightfield(path, kind) if mode == "brightfield" else fluorescence(path, kind)


def size_for(mode):
    return BF_SIZE if mode == "brightfield" else FLUO_SIZE
