"""Fix demo: prove an M3 fix with the real co-pilot on the virtual scanner.

A fix only counts if its test can fail. Three steps, each a real run of
tools/m3_first_runs.py (all 13 scenarios, no LLM):

  1. the real co-pilot, with the fix              -> the scenario must PASS
  2. the fix undone in a TEMPORARY COPY of the     -> the scenario must go back to OPEN
     private co-pilot (a "mutation")                  (the old weakness)
  3. the real co-pilot again                       -> the scenario must PASS again

The private code is never changed: step 2 runs on a copy that is deleted
afterwards. Each step's real output is saved to docs/demo/ as text and, with
--render, as a terminal-style picture (docs/images/). Paths are removed and the
text passes the leak check before anything is written.

Run with the PRIVATE project's Python (it has the co-pilot's dependencies):

    <private>/venv/Scripts/python tools/demo_m3_fix.py s11|s12 [--render]

Exit code 0 = the mutation was caught (the scenario really tests the fix).
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import leak_check  # noqa: E402
from render_walkthrough import colour as m3_colour  # noqa: E402  (same colours as the M3 walkthrough)

PRIVATE = REPO.parent
REPORT = REPO / "docs" / "m3_first_runs.md"
OUT_TEXT = REPO / "docs" / "demo"
OUT_IMG = REPO / "docs" / "images"
COMMAND = r"PS <project>\MISHU_KHONDOKER> ..\venv\Scripts\python tools\m3_first_runs.py"

# Each fix: the exact guard text in the private app/main.py, how many times it
# appears, the mutant that undoes it, what the scenario must say with the fix,
# and the lines shown above the mutated run.
FIXES = {
    "s11": {
        "scenario": "S11",
        "name": "no blind scan",
        "guard": ('            if not _hdscanner_focuses_itself():\n'
                  '                return {"ok": False, "code": "FOCUS-POINTS", "unreachable": False}\n'),
        "times": 2,
        "mutant": '            pass  # MUTATION: S11 guard switched off (no FocusDensity check)\n',
        "pass_text": "FOCUS-POINTS, scans=0",
        "shown": ["# mutation in a temporary copy of the private app/main.py (both places):",
                  "#   if not _hdscanner_focuses_itself():",
                  "#       return {... \"code\": \"FOCUS-POINTS\" ...}",
                  "#   ->  pass  # MUTATION: S11 guard switched off (no FocusDensity check)"],
    },
    "s12": {
        "scenario": "S12",
        "name": "no silent preview",
        "guard": ('    if not os.path.exists(preview_path):\n'
                  '        return {"ok": False, "preview_missing": True,\n'),
        "times": 1,
        "mutant": ('    if not os.path.exists(preview_path):  # MUTATION: the old silent preview is back\n'
                   '        preview = scanner.new_scan(slide_no=slide)\n'
                   '        preview_path = (preview or {}).get("result", preview_path)\n'
                   '    if not os.path.exists(preview_path):\n'
                   '        return {"ok": False, "preview_missing": True,\n'),
        "pass_text": "refused, new previews=0",
        "shown": ["# mutation in a temporary copy of the private app/main.py:",
                  "#   preview missing  ->  refuse (ok false, preview_missing)",
                  "#   ->  preview missing  ->  scanner.new_scan(slide)   # MUTATION: the old silent preview"],
    },
    "s13": {
        "scenario": "S13",
        "name": "never click on an existing focus point",
        "guard": ('    existing = next((s.get("focus_marks_px") or [] for s in seen["slides"]\n'
                  '                     if s["slide"] == slide + 1), [])\n'),
        "times": 1,
        "mutant": '    existing = []  # MUTATION: existing focus points ignored - click anyway\n',
        "pass_text": "customer's point kept, skipped=1, placed=2",
        "shown": ["# mutation in a temporary copy of the private app/main.py:",
                  "#   existing = <the focus points already on the preview>",
                  "#   ->  existing = []   # MUTATION: existing focus points ignored - click anyway"],
    },
}


def run_m3(private_root):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    if Path(private_root) != PRIVATE:
        # The copy has no .env (it is never copied). M3 never calls the language model,
        # but the co-pilot builds its client at import, so hand the copy the same
        # value the normal runs read from the private .env - nothing is written down.
        from dotenv import dotenv_values
        env["DEEPSEEK_API_KEY"] = dotenv_values(PRIVATE / ".env").get("DEEPSEEK_API_KEY") or ""
    r = subprocess.run([sys.executable, str(REPO / "tools" / "m3_first_runs.py"), str(private_root)],
                       cwd=REPO, capture_output=True, text=True, encoding="utf-8", env=env)
    return r.stdout + r.stderr


def private_copy(work):
    """Only the co-pilot's code and knowledge files - no .env, no venv, no data."""
    for path in PRIVATE.glob("*.py"):
        shutil.copy(path, work / path.name)
    for part in ("app", "knowledge"):
        shutil.copytree(PRIVATE / part, work / part, ignore=shutil.ignore_patterns("__pycache__"))


def clean(text, *folders):
    for folder in folders:
        for form in (str(folder), str(folder).replace("\\", "/")):
            text = text.replace(form, "<project>")
    text = re.sub(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s']+[^\s']*", "<tmp>", text)
    return text


def scenario_line(out, sid):
    return next((ln for ln in out.splitlines() if re.match(rf"\w+\s+{sid} ", ln)), "")


def render(lines, title, out_path, sid):
    """Terminal-style picture of the real output; the scenario's line gets a highlight bar."""
    from PIL import Image, ImageDraw, ImageFont
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
        col, strong = m3_colour(line)
        if line.lstrip().startswith("#") or "MUTATION" in line:
            col, strong = (255, 200, 80), True
        if scenario_line(line, sid):
            d.rectangle([pad - 8, y - 3, width - pad + 8, y + lh - 3], outline=col, width=2,
                        fill=tuple(int(c * 0.22) for c in col))
        d.text((pad, y), line, font=bold if strong else font, fill=col)
        y += lh
    img.save(out_path)


def main(key=None):
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    key = key or (args[0].lower() if args else "")
    if key not in FIXES:
        sys.exit(f"usage: demo_m3_fix.py {'|'.join(FIXES)} [--render]")
    fix, sid = FIXES[key], FIXES[key]["scenario"]
    want_pictures = "--render" in sys.argv
    report_before = REPORT.read_text(encoding="utf-8") if REPORT.exists() else None
    work = Path(tempfile.mkdtemp(prefix=f"{key}-demo-")).resolve()
    report_rewritten_by_real_run = False
    try:
        def passed(out):
            line = scenario_line(out, sid)
            return line.startswith("PASS") and fix["pass_text"] in line

        steps = []
        out = run_m3(PRIVATE)
        steps.append((f"{key}_1_fix_on", f"{sid} Step 1 - the real co-pilot with the fix: {sid} PASS",
                      passed(out), [], out))

        private_copy(work)
        target = work / "app" / "main.py"
        original = target.read_text(encoding="utf-8")
        assert original.count(fix["guard"]) == fix["times"], \
            f"{sid} guard not found exactly {fix['times']}x in app/main.py"
        target.write_text(original.replace(fix["guard"], fix["mutant"]), encoding="utf-8")
        out = run_m3(work)
        steps.append((f"{key}_2_fix_off", f"{sid} Step 2 - fix undone: {sid} must go back to OPEN",
                      scenario_line(out, sid).startswith("OPEN"), fix["shown"], out))

        out = run_m3(PRIVATE)
        report_rewritten_by_real_run = True
        steps.append((f"{key}_3_fix_restored", f"{sid} Step 3 - the real co-pilot again: {sid} PASS again",
                      passed(out), [], out))

        problems, ready = [], []
        for name, title, ok, prefix, out in steps:
            lines = prefix + [COMMAND] + [ln.rstrip() for ln in clean(out, work, PRIVATE, REPO).splitlines()
                                          if ln.strip()]
            text = "\n".join(lines) + "\n"
            problems += leak_check.check_file(f"docs/demo/{name}.txt", text.encode(),
                                              leak_check.private_terms())
            ready.append((name, title, ok, lines, text))
        if problems:
            print("demo: NOTHING saved - leak check found:", *problems, sep="\n  - ")
            return 2

        OUT_TEXT.mkdir(parents=True, exist_ok=True)
        for name, title, ok, lines, text in ready:
            (OUT_TEXT / f"{name}.txt").write_text(text, encoding="utf-8")
            if want_pictures:
                OUT_IMG.mkdir(parents=True, exist_ok=True)
                render(lines, title, OUT_IMG / f"{name}.png", sid)
            print(f"{'OK  ' if ok else 'FAIL'} {title}")

        caught = all(ok for _, _, ok, _, _ in ready)
        print("\nResult:", f"the mutation was CAUGHT - {sid} really tests the fix ({fix['name']})."
              if caught else f"UNEXPECTED - look at docs/demo/ before trusting {sid}.")
        return 0 if caught else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
        # The mutated run rewrites the M3 report; step 3 rewrites it again from the
        # real co-pilot. If we stopped before step 3, put the original back.
        if report_before is not None and not report_rewritten_by_real_run:
            REPORT.write_text(report_before, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
