# Synced from the private co-pilot by tools/sync_from_private.py - change it there, then re-sync.
"""
scan_reader.py  --  read back what a completed scan actually produced.

The scanner writes ONE Scan.txt per scan, into its results folder:

    ScanResults/YYYY-MM-DD/{sample-id}/Scan.txt

It's a Windows .ini file (key=value lines grouped under [Section] headers).
The copilot can already START a scan, but it can't yet REPORT how that scan
went. This file is step 1 of fixing that: a standalone parser that pulls the
meaningful summary out of Scan.txt (tile count, grid, completion flag, focus
failures, exposure, gain, clarity...) so we can prove the parsing works BEFORE
wiring it into main.py as a copilot tool.

Why configparser (not manual parsing): Scan.txt IS an ini file, so the standard
library reads it natively. Two gotchas handled below:
  1. Keys are CamelCase (SlideID, FieldWidth) but configparser lowercases them
     by default -> set optionxform = str to keep the original case.
  2. Every value comes back as a STRING, and some fields are absent from
     simulator/copilot scans (e.g. StdDev) -> every read is None-tolerant, so a
     missing field is reported honestly as missing, never a crash.

Standalone: does NOT import main.py or the copilot. Safe to run directly.

    python scan_reader.py
"""

import configparser
import glob
import os

from scanner_paths import HDSCANNER_DIR

# This machine's results: SCAN_RESULTS_DIR in .env if set, else <HDScanner folder>\scanresults
# (the Results Path HDScanner shows on its Scan tab; Windows ignores the case, so the
# dev PC's "ScanResults" matches too). Was hard-coded to the dev PC — on Scanner A the
# copilot could never find a scan's Scan.txt (2026-09-30).
SCAN_RESULTS_DIR = os.getenv("SCAN_RESULTS_DIR") or os.path.join(HDSCANNER_DIR, "scanresults")


def _open(path):
    """Return a ConfigParser with the file loaded, keys case-preserved.

    Raises on failure (missing file, not an ini, ...) -- the caller decides
    how to report it."""
    cp = configparser.ConfigParser()
    cp.optionxform = str  # keep CamelCase keys: SlideID, not slideid
    with open(path, "r", encoding="utf-8") as f:
        cp.read_file(f)
    return cp


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_scan_txt(path):
    """Read one Scan.txt and return a clean summary dict.

    Returns {ok: True, <fields...>} on success, or {ok: False, error: ...}.
    Fields that the file doesn't contain come back as None (e.g. focus StdDev
    is absent from simulator/copilot scans), so the caller can say so instead
    of inventing a value.
    """
    try:
        cp = _open(path)
    except Exception as e:
        return {"ok": False, "error": f"could not read {path}: {e}"}

    # A tiny helper so a missing key returns None instead of raising.
    def get(section, key):
        try:
            return cp.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return None

    # Focus points are F0, F1, F2, ... each like "25.4/25.4/0.0um" (+ maybe a
    # result code). A copilot/simulator scan may have just F0; a real GUI scan
    # has several. Collect whichever exist.
    focus_points = [get("Focus", f"F{i}") for i in range(6)]
    focus_points = [p for p in focus_points if p is not None]

    return {
        "ok": True,
        "path": path,
        # --- [General]: what the scan was, and how big it turned out ---
        "sample_id": get("General", "SlideID"),
        "slide_type": get("General", "SlideType"),
        "magnification": get("General", "Magnification"),
        "field_width_um": _to_float(get("General", "FieldWidth")),
        "tile_grid": (f"{get('General', 'RowCount')}x{get('General', 'ColumnCount')}"
                      if get("General", "RowCount") and get("General", "ColumnCount")
                      else None),
        "tile_count": _to_int(get("General", "Quantity")),
        # Raw ScanStopped flag. 1 was observed on completed copilot scans, but
        # the exact 0-vs-1 meaning is still unconfirmed, so we report the raw
        # value and let the caller describe it rather than assert "success".
        "scan_stopped": get("General", "ScanStopped"),
        "clarity": _to_float(get("General", "Clarity")),
        "stitch_mode": get("General", "StitchMode"),
        "focus_mode": get("General", "FocusMode"),
        # --- [Focus]: did it actually focus? (sparse in simulator scans) ---
        "focus_points": focus_points,
        "focus_failed": _to_int(get("Focus", "Failed")),
        "focus_stddev": _to_float(get("Focus", "StdDev")),
        "focus_plane": get("Focus", "Z"),
        # --- [Camera] / [Lights]: acquisition settings ---
        "exposure_us": _to_int(get("Camera", "ExpoTime")),
        "gain": _to_int(get("Camera", "ExpoGain")),
    }


def latest_scan_txt():
    """Path of the most recently-written Scan.txt under the results folder,
    or None if there are none."""
    files = glob.glob(os.path.join(SCAN_RESULTS_DIR, "*", "*", "Scan.txt"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def find_scan_txt(sample_id=None):
    """Path of a specific sample's Scan.txt, or the most recent one if no id.

    A scan's folder is named after its sample id, e.g. COPILOT-20260918-170507,
    so `ScanResults/*/<sample_id>/Scan.txt` locates it. Returns None if no match.
    """
    if sample_id:
        matches = glob.glob(os.path.join(SCAN_RESULTS_DIR, "*", sample_id, "Scan.txt"))
        if not matches:
            return None
        return max(matches, key=os.path.getmtime)  # newest if somehow duplicated
    return latest_scan_txt()


# ---- standalone self-test: run `python scan_reader.py` ---------------------
if __name__ == "__main__":
    # 1) Parse the most recent scan (whatever it is) and show the summary.
    latest = latest_scan_txt()
    if latest is None:
        print("No Scan.txt found under", SCAN_RESULTS_DIR)
    else:
        print("Most recent scan:", latest)
        print()
        summary = parse_scan_txt(latest)
        for key, val in summary.items():
            print(f"  {key:14} = {val}")

    # 2) Also parse one KNOWN copilot scan + one KNOWN GUI scan, side by side,
    #    to make the difference visible (copilot scans lack StdDev/plane).
    copilot = os.path.join(
        SCAN_RESULTS_DIR, "2026-09-18", "COPILOT-20260918-170507", "Scan.txt")
    gui = os.path.join(
        SCAN_RESULTS_DIR, "2026-09-18", "2026-09-18-160756", "Scan.txt")

    print("\n=== COPILOT scan (sparse focus) ===")
    if os.path.exists(copilot):
        s = parse_scan_txt(copilot)
        print("  focus_points :", s.get("focus_points"))
        print("  focus_failed :", s.get("focus_failed"))
        print("  focus_stddev :", s.get("focus_stddev"), "(absent -> None)")
    else:
        print("  (file not found)")

    print("\n=== GUI scan (rich focus) ===")
    if os.path.exists(gui):
        s = parse_scan_txt(gui)
        print("  focus_points :", s.get("focus_points"))
        print("  focus_failed :", s.get("focus_failed"))
        print("  focus_stddev :", s.get("focus_stddev"))
        print("  focus_plane  :", s.get("focus_plane"))
    else:
        print("  (file not found)")
