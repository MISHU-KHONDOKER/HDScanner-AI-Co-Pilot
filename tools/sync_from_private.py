"""Copy the approved co-pilot modules from the private project into copilot_core/.

The co-pilot is developed in a private repository. The parts that are tested
publicly (milestone M2) are copied here as plain files - never as git history,
which can contain secrets. Every copy:

  1. gets public rewrites (imports that point at code that is not published),
  2. gets private rewrites from `.sync-private.txt` (machine names, local paths;
     that file is gitignored, because the rules themselves name private things),
  3. is checked by tools/leak_check.py before it is written.

If any copy fails the leak check, nothing is written.

Usage:
  python tools/sync_from_private.py [path/to/private/project]   (default: ..)
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import leak_check  # noqa: E402

TARGET = REPO / "copilot_core"
PRIVATE_RULES = REPO / ".sync-private.txt"

# The modules approved for publishing (M2, groups B-F).
FILES = [
    "customer_config.py",           # B  config safety guards
    "scan_reader.py",               # C  scan result reading
    "scanner_sample_area.py",       # D  geometry and bounds
    "scanner_focus_points_bf.py",   # E  focus point chooser
    "scanner_find_samples_bf.py",   # F  sample finder (brightfield)
    "scanner_find_samples_fluo.py", # F  sample finder (fluorescence / simulator)
]

# Public rewrites: the scanner protocol client is not published, so the modules
# take the scanner's folder from copilot_core/scanner_paths.py instead.
PUBLIC_RULES = [
    ("from scanner_mcp_client import", "from scanner_paths import"),
]

HEADER = ("# Synced from the private co-pilot by tools/sync_from_private.py "
          "- change it there, then re-sync.\n")


def private_rules():
    if not PRIVATE_RULES.exists():
        sys.exit("sync: .sync-private.txt is missing - refusing to copy without the private rewrite rules.")
    rules = []
    for line in PRIVATE_RULES.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=>" in line:
            old, new = (part.strip() for part in line.split("=>", 1))
            rules.append((old, new))
    return rules


def main():
    source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO.parent
    rules = PUBLIC_RULES + private_rules()
    terms = leak_check.private_terms()

    copies, problems = {}, []
    for name in FILES:
        src = source / name
        if not src.exists():
            problems.append(f"{name}: not found in {source}")
            continue
        text = src.read_text(encoding="utf-8")
        for old, new in rules:
            text = text.replace(old, new)
        text = HEADER + text
        rel = f"copilot_core/{name}"
        problems += leak_check.check_file(rel, text.encode("utf-8"), terms)
        copies[name] = text

    if problems:
        print("sync: NOTHING written - fix these first:")
        for p in problems:
            print("  -", p)
        return 1

    TARGET.mkdir(exist_ok=True)
    for name, text in copies.items():
        (TARGET / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"sync: {len(copies)} module(s) copied to copilot_core/ - leak check clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
