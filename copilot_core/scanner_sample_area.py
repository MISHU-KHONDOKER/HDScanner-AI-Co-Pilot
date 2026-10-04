# Synced from the private co-pilot by tools/sync_from_private.py - change it there, then re-sync.
"""find_sample_area — the "look and propose" half of placing the scan box.

Given the scanner's own preview picture, find the sample(s), add a margin, keep
the box inside the slide, convert pixels -> slide millimetres, and draw the
proposal on a copy of the preview for the operator to check.

Changes NOTHING on the scanner: it only reads a picture file. Setting the box
(Setup -> Slide -> Scan Region, then NewScan) is a separate step that must only
run after the operator confirms.

IMPORTANT: analyse the preview NewScan returned (CapturedImages/Preview#1.tif),
not the chat's display photo — the scan box coordinates belong to that picture.

    python scanner_sample_area.py [preview.tif] [margin_px] [brightfield|fluorescence]
"""
import configparser
import os
import sys

from PIL import Image, ImageDraw

import scanner_find_samples_bf
import scanner_find_samples_fluo
from scanner_paths import HDSCANNER_DIR

SLIDE_WIDTH_MM = 76.2   # fallback when the config has no slide size (the dev sim)
DEFAULT_MARGIN_PX = 10
BF_MARGIN_PX = 12       # Brightfield: HDScanner's own box ~330 px around a ~312 px disc (+ safety)
_CONFIG = os.getenv("HDSCANNER_CONFIG") or os.path.join(HDSCANNER_DIR, "config.ini")


def slide_scale(img_w, img_h, config_path=_CONFIG):
    """(mm_per_px_x, mm_per_px_y, slide_w_mm, slide_h_mm) for a preview picture.

    The preview spans the whole slide, whose size is in config.ini [Slide]
    Width/Height (real scanner: 75.0 x 25.0 mm on a 1882 x 632 px preview ->
    0.03985 mm/px across, 0.03956 down — NOT the same, so x and y are separate).
    No size in the config (dev sim) -> 76.2 mm across and square pixels (0.0508)."""
    w_mm = h_mm = None
    try:
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        cp.optionxform = str
        with open(config_path, "r", encoding="utf-8-sig") as f:
            cp.read_file(f)
        w_mm = float(cp.get("Slide", "Width", fallback="") or 0) or None
        h_mm = float(cp.get("Slide", "Height", fallback="") or 0) or None
    except (OSError, ValueError, configparser.Error):
        pass
    sx = (w_mm or SLIDE_WIDTH_MM) / img_w
    sy = (h_mm / img_h) if h_mm else sx
    return sx, sy, round(img_w * sx, 2), round(img_h * sy, 2)


def _clamp_box(x, y, w, h, img_w, img_h):
    """Keep the box inside the picture (i.e. on the slide)."""
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(img_w, x + w), min(img_h, y + h)
    return x1, y1, x2 - x1, y2 - y1


def _to_mm(box_px, sx, sy):
    x, y, w, h = box_px
    return [round(x * sx, 2), round(y * sy, 2), round(w * sx, 2), round(h * sy, 2)]


def find_samples_for_mode(preview_path, mode=None):
    """The ONE place that picks the finder: Brightfield -> scanner_find_samples_bf
    (blue disc); anything else (fluorescence, the simulator) -> scanner_find_samples_fluo.
    The two are never mixed."""
    if mode == "brightfield":
        return scanner_find_samples_bf.find_samples(preview_path)
    return scanner_find_samples_fluo.find_samples(preview_path)


def propose_sample_area(preview_path, margin_px=DEFAULT_MARGIN_PX, proposal_path=None,
                        mode=None):
    """Find the sample(s) in `preview_path` and propose a scan box around one.

    Returns a dict (never raises for "nothing found"):
      ok, samples_found, samples[{index, box_px, box_mm}], proposed_index,
      proposed_box_px [x,y,w,h], proposed_box_mm [left,top,width,height],
      mm_per_px, preview_size, proposal_image, note
    The proposal is the LARGEST sample; with several, the caller (the AI) should
    ask the operator which one they mean.
    """
    if not os.path.exists(preview_path):
        return {"ok": False, "error": f"Preview picture not found: {preview_path}"}

    with Image.open(preview_path) as im:
        img_w, img_h = im.size
    sx, sy, _, _ = slide_scale(img_w, img_h)

    found = find_samples_for_mode(preview_path, mode)
    samples = []
    for i, b in enumerate(found, 1):
        box_px = [b["x"], b["y"], b["w"], b["h"]]
        samples.append({"index": i, "box_px": box_px, "box_mm": _to_mm(box_px, sx, sy),
                        "area_px": b["area"], "method": b.get("method")})

    result = {"ok": bool(samples), "samples_found": len(samples), "samples": samples,
              "mm_per_px": [round(sx, 5), round(sy, 5)], "preview_size": [img_w, img_h],
              "margin_px": margin_px}
    if not samples:
        result["note"] = ("No sample found in the preview. Do not guess a box — ask the "
                          "operator to check the slide/preview.")
        return result

    best = max(samples, key=lambda s: s["area_px"])
    x, y, w, h = best["box_px"]
    box_px = list(_clamp_box(x - margin_px, y - margin_px, w + 2 * margin_px, h + 2 * margin_px,
                             img_w, img_h))
    result.update({
        "proposed_index": best["index"],
        "proposed_box_px": box_px,
        "proposed_box_mm": _to_mm(box_px, sx, sy),
        "note": ("Proposal only — nothing was changed on the scanner. Show it to the operator "
                 "and wait for confirmation before setting the scan area."
                 + (" Several samples were found; ask which one they mean."
                    if len(samples) > 1 else "")),
    })

    if proposal_path:
        img = Image.open(preview_path).convert("RGB")
        d = ImageDraw.Draw(img)
        for s in samples:
            sx, sy, sw, sh = s["box_px"]
            d.rectangle([sx, sy, sx + sw, sy + sh], outline=(0, 90, 255), width=2)
            d.text((sx, max(0, sy - 12)), f"#{s['index']}", fill=(0, 90, 255))
        bx, by, bw, bh = box_px
        d.rectangle([bx, by, bx + bw, by + bh], outline=(0, 170, 0), width=4)
        img.save(proposal_path)
        result["proposal_image"] = proposal_path
    return result


if __name__ == "__main__":
    import json
    path = sys.argv[1] if len(sys.argv) > 1 else \
        r"CapturedImages/Preview#1.tif"
    mode = sys.argv[3] if len(sys.argv) > 3 else None
    margin = int(sys.argv[2]) if len(sys.argv) > 2 else \
        (BF_MARGIN_PX if mode == "brightfield" else DEFAULT_MARGIN_PX)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_proposal.png")
    print(json.dumps(propose_sample_area(path, margin, out, mode), indent=2))
