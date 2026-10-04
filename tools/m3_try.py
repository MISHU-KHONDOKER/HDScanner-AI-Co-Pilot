"""Try the real co-pilot on the virtual scanner yourself, with any faults.

Runs ONE customer "start scan" (auto_scan) on a fresh virtual scanner and prints
every step the co-pilot took, what the customer is told, and what the virtual
machine saw. Real machines are blocked by the harness.

Run with the PRIVATE project's Python:

    ..\\venv\\Scripts\\python tools\\m3_try.py                              # healthy scanner
    ..\\venv\\Scripts\\python tools\\m3_try.py --fault scrambled_settings
    ..\\venv\\Scripts\\python tools\\m3_try.py --fault other_machine_good_file
    ..\\venv\\Scripts\\python tools\\m3_try.py --slide 2 --load clear,faint
    ..\\venv\\Scripts\\python tools\\m3_try.py --list                       # all fault switches
"""
import argparse
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from virtual_scanner import FAULTS, VirtualScanner  # noqa: E402
from virtual_scanner.harness import load_copilot  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fault", action="append", default=[], help="a fault switch (repeatable)")
    ap.add_argument("--slide", type=int, default=1, help="slide to scan, 1-4 (default 1)")
    ap.add_argument("--load", default="clear", help="slides in the loader, e.g. clear,faint,empty")
    ap.add_argument("--mode", default="brightfield", choices=["brightfield", "fluorescence"])
    ap.add_argument("--private", default=str(REPO.parent), help="path to the private co-pilot")
    ap.add_argument("--list", action="store_true", help="list the fault switches and exit")
    a = ap.parse_args()

    if a.list:
        for name, what in FAULTS.items():
            print(f"  {name:<26} {what}")
        return 0

    kinds = [k.strip() or None for k in a.load.split(",")]
    kinds = [None if k == "none" else k for k in kinds] + [None] * (4 - len(kinds))
    twin = VirtualScanner(tempfile.mkdtemp(prefix="vscan-"), a.mode, kinds[:4], a.fault)
    copilot = load_copilot(a.private, twin)

    print(f"\nVirtual scanner: mode={a.mode}, loader={kinds[:4]}, faults={a.fault or 'none'}")
    print(f"Customer: \"start scan\" on slide {a.slide}\n")
    r = copilot.auto_scan(a.slide, a.mode)

    print("Steps the co-pilot took:")
    for s in r.get("steps", []):
        extra = {k: v for k, v in s.items() if k in ("attempt", "restored", "restarted", "fixed",
                                                    "samples_found", "verified", "finished",
                                                    "result_code")}
        print(f"  {'ok ' if s.get('ok') else 'NO '} {s.get('step'):<16} {extra}")
        for fixed in s.get("fixed_settings") or []:
            print(f"        repaired: {fixed}")

    print("\nOutcome:")
    if r.get("ok"):
        res = r.get("result") or {}
        print(f"  SUCCESS - sample {r.get('sample_id')}, tiles={res.get('tile_count')}, "
              f"focus_failed={res.get('focus_failed')}")
    else:
        print(f"  support code: {r.get('support_code')}  level: {r.get('level')}")
    if r.get("customer_message"):
        print(f"  the customer is told: \"{r['customer_message']}\"")

    print("\nWhat the virtual scanner saw:")
    for door, action in (("process", "close_normally"), ("process", "force_close"),
                         ("process", "start"), ("socket", "NewScan"), ("socket", "StartScan")):
        print(f"  {door}.{action:<15} {twin.count(door, action)}x")
    print(f"  live settings now: {twin.live}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
