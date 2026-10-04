"""Shared test setup.

* Makes copilot_core/ importable.
* SAFETY: blocks every way the code under test could close, kill or start a
  real program. customer_config.py can force-close and restart the scanner
  software; a unit test must never do that, even by mistake. If a test reaches
  one of these calls it fails loudly instead.
* Builds synthetic test data. No real config, preview or result file from a
  scanner is ever used: the tests must run on any machine and leak nothing.
"""
import math
import random
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "copilot_core"))


class ProcessCallBlocked(AssertionError):
    pass


def _blocked(*args, **kwargs):
    raise ProcessCallBlocked(f"a test tried to run a real process: {args!r}")


@pytest.fixture(autouse=True)
def no_real_processes(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _blocked)
    monkeypatch.setattr(subprocess, "Popen", _blocked)
    import customer_config
    for name in ("stop_hdscanner", "start_hdscanner", "close_hdscanner_normally",
                 "_hdscanner_running"):
        monkeypatch.setattr(customer_config, name, _blocked)


# ---------------------------------------------------------------- config files

def write_ini(path, sections):
    """Write a scanner-style ini file from {section: {key: value}}."""
    lines = []
    for section, values in sections.items():
        lines.append(f"[{section}]")
        lines += [f"{k}={v}" for k, v in values.items()]
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def base_config(key="AAAA1111FAKE", fluo="false", camera="CameraReal"):
    """A small, entirely made-up scanner config."""
    return {
        "Controller": {"Key": key},
        "Camera": {"Model": camera, "ExpoTime20X": "1200"},
        "Setup": {"ImagingFluo": fluo, "FocusDensity": "4", "StitchMode": "2"},
        "Slide": {"Type": "TCT", "ScanLeft": "10.0", "ScanTop": "2.0",
                  "ScanWidth": "20.0", "ScanHeight": "20.0"},
        "Scan": {"InputPath": "sim/input", "ResultsPath": "results"},
    }


# ------------------------------------------------------------- preview images

BF_SIZE = (1119, 373)   # the size the brightfield finder is tuned on


def brightfield_preview(path, disc=True, contrast=6, cells=True, logo=False, seed=1):
    """A synthetic brightfield slide preview: light glass, optionally a round
    sample disc that is slightly darker than the glass, with small dark cells."""
    rnd = random.Random(seed)
    W, H = BF_SIZE
    glass = 200
    img = Image.new("RGB", (W, H), (glass, glass, glass))
    d = ImageDraw.Draw(img)
    cx, cy, r = 300, 186, 155
    if disc:
        inside = glass - contrast
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(inside, inside, inside + 4))
        if cells:
            for _ in range(2500):
                a, rr = rnd.uniform(0, 2 * math.pi), r * math.sqrt(rnd.random()) * 0.95
                x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
                v = inside - 40
                d.ellipse([x - 1, y - 1, x + 1, y + 1], fill=(v, v, v + 10))
    if logo:   # a small printed mark, like the logo the old finder mistook for the sample
        for i in range(5):
            a = 2 * math.pi * i / 5
            x, y = 330 + 18 * math.cos(a), 186 + 18 * math.sin(a)
            d.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(60, 60, 60), width=3)
    img.save(path)
    return str(path), (cx, cy, r)


def fluo_preview(path, square=True):
    """A synthetic simulator-style preview: beige glass with a magenta sample."""
    img = Image.new("RGB", (1500, 500), (225, 215, 190))
    if square:
        ImageDraw.Draw(img).rectangle([700, 200, 799, 299], fill=(230, 0, 230))
    img.save(path)
    return str(path)
