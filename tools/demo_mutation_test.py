"""Mutation-test demo: prove that the F01 test really protects the F01 guard.

A test only counts if it can fail. This script shows it, in three steps, on a
TEMPORARY COPY of copilot_core/ and tests/ (the real files are never touched):

  1. run the F01 test against the real guard          -> must PASS
  2. switch the guard off in the copy (a "mutation")   -> the test must FAIL
  3. put the guard back                                -> must PASS again

Each step's real output is saved to docs/demo/ as text and, with --render, as a
terminal-style picture (docs/images/). Local paths and user names are removed
and the text passes the leak check before anything is written.

    python tools/demo_mutation_test.py [--render]

Exit code 0 = the mutation was caught (the test is effective).
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

OUT_TEXT = REPO / "docs" / "demo"
OUT_IMG = REPO / "docs" / "images"
TEST = "tests/test_config_guards.py"
SELECT = "F01_config_from_another"
GUARD = "    wrong = _other_machine(live_path, good_path)\n"
MUTANT = "    wrong = None  # MUTATION: machine-identity guard switched off\n"
COMMAND = f"python -m pytest {TEST} -v -k {SELECT}"


def run_test(workdir):
    env = dict(os.environ, COLUMNS="110", PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "pytest", TEST, "-v", "-k", SELECT,
                        "--tb=short", "-p", "no:cacheprovider"],
                       cwd=workdir, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def clean(text, workdir):
    """Remove everything machine-specific from the output."""
    for form in (str(workdir), str(workdir).replace("\\", "/")):
        text = text.replace(form + "\\", "").replace(form + "/", "").replace(form, "<repo>")
    text = re.sub(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s']+[^\s']*", "<tmp>", text)
    text = re.sub(r"pytest-of-[^\\/\s']+", "pytest-of-user", text)
    text = re.sub(r"platform .*", "platform <os> -- Python <version>", text)
    text = re.sub(r"cachedir: .*\n", "", text)
    text = re.sub(r" -- \S*python(\.exe)?", "", text)
    return text


def render(lines, title, out_path):
    """A simple terminal-style picture of the real output."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("consola.ttf", 17)
        bold = ImageFont.truetype("consolab.ttf", 17)
    except OSError:
        font = bold = ImageFont.load_default()
    pad, lh, bar = 22, 23, 40
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
        color, f = (205, 208, 214), font
        if line.startswith("$ "):
            color, f = (120, 190, 255), bold
        elif "PASSED" in line or re.search(r"\d+ passed", line):
            color, f = (90, 220, 120), bold
        elif "FAILED" in line or re.search(r"\d+ failed", line) or line.startswith("E "):
            color, f = (255, 110, 110), bold
        elif "MUTATION" in line:
            color, f = (255, 200, 80), bold
        d.text((pad, y), line, font=f, fill=color)
        y += lh
    img.save(out_path)


def keep(output):
    """The lines worth showing (drop pytest's long separator lines)."""
    lines = []
    for line in output.splitlines():
        if re.fullmatch(r"[=_ -]*", line):
            continue
        line = re.sub(r"^[=_]{3,} ?(.*?) ?[=_]{3,}$", r"--- \1 ---", line)
        lines.append(line.rstrip())
    return lines


def main():
    want_pictures = "--render" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="mutation-demo-")).resolve()   # long path, as pytest prints it
    try:
        for part in ("copilot_core", "tests"):
            shutil.copytree(REPO / part, work / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(REPO / "pyproject.toml", work)
        target = work / "copilot_core" / "customer_config.py"
        original = target.read_text(encoding="utf-8")
        assert original.count(GUARD) == 1, "guard line not found exactly once"

        steps = []
        code, out = run_test(work)
        steps.append(("1_guard_on", "Step 1 - the real guard: test passes", code == 0, [], out))

        target.write_text(original.replace(GUARD, MUTANT), encoding="utf-8")
        code, out = run_test(work)
        steps.append(("2_guard_off", "Step 2 - guard switched off: test must FAIL",
                      code != 0 and "ProcessCallBlocked" in out,
                      ["$ # mutation in a temporary copy of customer_config.py:",
                       "$ #   " + GUARD.strip(),
                       "      ->  " + MUTANT.strip()], out))

        target.write_text(original, encoding="utf-8")
        code, out = run_test(work)
        steps.append(("3_guard_restored", "Step 3 - guard restored: test passes again", code == 0, [], out))

        problems = []
        OUT_TEXT.mkdir(parents=True, exist_ok=True)
        for name, title, ok, prefix, out in steps:
            lines = prefix + [f"$ {COMMAND}"] + keep(clean(out, work))
            text = "\n".join(lines) + "\n"
            problems += leak_check.check_file(f"docs/demo/{name}.txt", text.encode(),
                                              leak_check.private_terms())
            steps[steps.index((name, title, ok, prefix, out))] = (name, title, ok, lines, text)
        if problems:
            print("demo: NOTHING saved - leak check found:", *problems, sep="\n  - ")
            return 2

        for name, title, ok, lines, text in steps:
            (OUT_TEXT / f"{name}.txt").write_text(text, encoding="utf-8")
            if want_pictures:
                OUT_IMG.mkdir(parents=True, exist_ok=True)
                render(lines, title, OUT_IMG / f"mutation_{name}.png")
            print(f"{'OK  ' if ok else 'FAIL'} {title}")

        caught = all(ok for _, _, ok, _, _ in steps)
        print("\nResult:", "the mutation was CAUGHT - the test is effective."
              if caught else "UNEXPECTED - look at docs/demo/ before trusting this test.")
        return 0 if caught else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
