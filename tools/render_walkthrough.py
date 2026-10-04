"""Turn the saved terminal transcripts in docs/walkthrough/ into pictures.

The transcripts are real terminal output, copied from the runs as they happened;
only the local folder path is shortened to <project>. Each one passes the leak
check before it is drawn.

    python tools/render_walkthrough.py
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import leak_check  # noqa: E402

SOURCE = REPO / "docs" / "walkthrough"
OUT = REPO / "docs" / "images"

TITLES = {
    "step1_twin_tests": "Step 1 - the virtual scanner's own tests",
    "step2_first_runs": "Step 2 - the real co-pilot in 13 situations",
    "step3_scramble": "Step 3 - scrambled settings, step by step",
    "step4_other_machine": "Step 4 - another machine's config (the 30 Sept incident)",
    "step5_door_left_open": "Step 5 - one real door left open on purpose",
    "step6_door_restored": "Step 6 - door restored, everything works again",
}


def colour(line):
    s = line.lstrip()
    if line.startswith("PS "):
        return (120, 190, 255), True
    if (s.startswith("PASS ") or " PASSED" in line or s.startswith("ok ")
            or s.startswith("SUCCESS")):
        return (90, 220, 120), s.startswith(("PASS ", "SUCCESS"))
    if s.startswith(("OPEN ", "repaired:")):
        return (255, 200, 80), True
    if (s.startswith(("NO ", "support code", "Traceback", "FAIL"))
            or "DoorNotSwapped" in line or "still the real" in line):
        return (255, 110, 110), True
    if s.endswith(":") and not s.startswith(("File", "PS")):
        return (230, 230, 230), True
    return (205, 208, 214), False


def render(lines, title, out_path):
    try:
        font = ImageFont.truetype("consola.ttf", 16)
        bold = ImageFont.truetype("consolab.ttf", 16)
    except OSError:
        font = bold = ImageFont.load_default()
    pad, lh, bar = 22, 22, 40
    longest = max((len(line) for line in lines), default=80)
    width = pad * 2 + int(font.getlength("M") * max(longest, 80)) + 10
    height = bar + pad * 2 + lh * len(lines)
    img = Image.new("RGB", (width, height), (24, 26, 33))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, bar], fill=(45, 48, 58))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16 + i * 22, 13, 30 + i * 22, 27], fill=c)
    d.text((100, 10), title, font=bold, fill=(220, 220, 220))
    y = bar + pad
    for line in lines:
        col, strong = colour(line)
        d.text((pad, y), line, font=bold if strong else font, fill=col)
        y += lh
    img.save(out_path)


def main():
    terms = leak_check.private_terms()
    OUT.mkdir(parents=True, exist_ok=True)
    problems, done = [], 0
    for name, title in TITLES.items():
        path = SOURCE / f"{name}.txt"
        text = path.read_text(encoding="utf-8")
        found = leak_check.check_file(f"docs/walkthrough/{name}.txt", text.encode(), terms)
        if found:
            problems += found
            continue
        lines = [re.sub(r"\s+$", "", ln) for ln in text.splitlines()]
        render(lines, title, OUT / f"m3_{name}.png")
        done += 1
    if problems:
        print("NOT drawn (leak check):", *problems, sep="\n  ")
        return 1
    print(f"{done} pictures written to docs/images/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
