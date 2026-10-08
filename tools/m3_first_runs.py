"""M3 first end-to-end runs: the REAL co-pilot on the virtual scanner, no LLM.

Each scenario builds a fresh virtual scanner (optionally with faults), loads the
private co-pilot through the harness (all machine doors swapped, real machines
blocked), calls the co-pilot's own functions, and checks the outcome against
what M1 says is correct.

Run with the PRIVATE project's Python (it has the co-pilot's dependencies):

    <private>/venv/Scripts/python tools/m3_first_runs.py [path/to/private/project]

Writes a summary to docs/m3_first_runs.md (codes and counts only - no paths).
"""
import configparser
import hashlib
import socket
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from virtual_scanner import VirtualScanner  # noqa: E402
from virtual_scanner.harness import (DoorNotSwapped, RealMachineBlocked,  # noqa: E402
                                     check_all_doors_swapped, load_copilot)
import leak_check  # noqa: E402

PRIVATE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO.parent
RESULTS = []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scenario(sid, title, rule, expected):
    def wrap(fn):
        def run():
            t0 = time.time()
            try:
                status, observed = fn()
            except Exception as e:  # a crash is a result too
                status, observed = "FAIL", f"crashed: {type(e).__name__}: {e}"
                traceback.print_exc()
            RESULTS.append((sid, title, rule, expected, observed, status, round(time.time() - t0, 1)))
            print(f"{status:<5} {sid} {title}  ->  {observed}")
        RESULTS.append  # keep linters quiet
        SCENARIOS.append(run)
        return run
    return wrap


SCENARIOS = []


def fresh(mode="brightfield", loaded=("clear", None, None, None), faults=()):
    twin = VirtualScanner(tempfile.mkdtemp(prefix="vscan-"), mode, loaded, faults)
    return twin, load_copilot(PRIVATE, twin)


def code(r):
    return r.get("support_code") or ("STILL-SCANNING" if r.get("still_scanning") else
                                     "OK" if r.get("ok") else "?")


# ---------------------------------------------------------------- safety

@scenario("S0", "Harness refuses an unswapped door and blocks the real scanner port",
          "M3 safety", "DoorNotSwapped + RealMachineBlocked")
def s0():
    twin, main = fresh()
    import scanner_gui
    main.get_anti_blur = scanner_gui.get_anti_blur          # put ONE real door back
    refused = blocked = False
    try:
        check_all_doors_swapped(main, sys.modules["customer_config"], twin)
    except DoorNotSwapped:
        refused = True
    try:
        socket.create_connection(("127.0.0.1", 58207), timeout=1)
    except RealMachineBlocked:
        blocked = True
    ok = refused and blocked
    return ("PASS" if ok else "FAIL"), f"refused={refused}, port blocked={blocked}"


# ---------------------------------------------------------------- Customer mode

@scenario("S1", "Clean scanner, brightfield slide 1", "G1, G4 / F03",
          "OK, 1 scan, success judged from the result file (scanner code 0)")
def s1():
    twin, main = fresh()
    r = main.auto_scan(1, "brightfield")
    tiles = (r.get("result") or {}).get("tile_count")
    ok = code(r) == "OK" and twin.count("socket", "StartScan") == 1 and tiles == 132
    return ("PASS" if ok else "FAIL"), f"{code(r)}, scans={twin.count('socket', 'StartScan')}, tiles={tiles}"


@scenario("S2", "Good config belongs to ANOTHER machine", "G5 / F01",
          "CONFIG, nothing closed or written")
def s2():
    twin, main = fresh(faults=("other_machine_good_file",))
    before = sha(twin.config_path)
    r = main.auto_scan(1, "brightfield")
    touched = sha(twin.config_path) != before
    closed = twin.count("process", "close_normally") + twin.count("process", "force_close")
    ok = code(r) == "CONFIG" and not touched and closed == 0 and twin.count("socket", "StartScan") == 0
    return ("PASS" if ok else "FAIL"), f"{code(r)}, config changed={touched}, closes={closed}"


@scenario("S3", "Good config is the OTHER imaging mode", "G6 / F02",
          "CONFIG, nothing closed or written")
def s3():
    twin, main = fresh(faults=("wrong_mode_good_file",))
    before = sha(twin.config_path)
    r = main.auto_scan(1, "brightfield")
    touched = sha(twin.config_path) != before
    ok = code(r) == "CONFIG" and not touched and twin.count("socket", "StartScan") == 0
    return ("PASS" if ok else "FAIL"), f"{code(r)}, config changed={touched}"


@scenario("S4", "Settings scrambled (in-house scramble test)", "G2, G7",
          "OK, the 4 scrambled settings repaired, live values = good file")
def s4():
    twin, main = fresh(faults=("scrambled_settings",))
    r = main.auto_scan(1, "brightfield")
    step = next((s for s in r.get("steps", []) if s.get("step") == "config"), {})
    want = {"AntiBlur": "10", "FocusDensity": "4", "StitchMode": "2", "SlideType": "TCT"}
    live_ok = {k: twin.live.get(k) for k in want} == want
    # Backups go into copilot_config_backup/ next to config.ini since 2026-10-08 (loose before).
    backups = len(list(twin.root.glob("config.ini.customer-backup-*"))
                  + list(twin.root.glob("copilot_config_backup/config.ini.customer-backup-*")))
    ok = code(r) == "OK" and step.get("fixed") == 4 and live_ok and backups == 1
    return ("PASS" if ok else "FAIL"), f"{code(r)}, fixed={step.get('fixed')}, live repaired={live_ok}, backups={backups}"


@scenario("S5", "Scanner reports the simulator's code 1 instead of 0", "G1 / F03",
          "OK - the code is not a verdict, the result file is")
def s5():
    twin, main = fresh(faults=("simulator_result_code",))
    r = main.auto_scan(1, "brightfield")
    ok = code(r) == "OK"
    return ("PASS" if ok else "FAIL"), code(r)


@scenario("S6", "ScanStopped arrives at once, result file only later", "G4 / F05",
          "NO-RESULT, exactly 1 scan, no restart after the scan started")
def s6():
    twin, main = fresh(faults=("early_scan_stopped",))
    r = main.auto_scan(1, "brightfield")
    scans = twin.count("socket", "StartScan")
    i_scan = next(i for i, (d, a, _) in enumerate(twin.log) if d == "socket" and a == "StartScan")
    restarts_after = sum(1 for d, a, _ in twin.log[i_scan:] if d == "process")
    ok = code(r) == "NO-RESULT" and scans == 1 and restarts_after == 0
    return ("PASS" if ok else "FAIL"), f"{code(r)}, scans={scans}, restarts after scan={restarts_after}"


@scenario("S7", "Calibration dialog freezes the scan", "G4 / F13",
          "STILL-SCANNING, 1 scan, never retried or restarted")
def s7():
    twin, main = fresh(faults=("calibration_modal",))
    r = main.auto_scan(1, "brightfield")
    scans = twin.count("socket", "StartScan")
    i_scan = next(i for i, (d, a, _) in enumerate(twin.log) if d == "socket" and a == "StartScan")
    restarts_after = sum(1 for d, a, _ in twin.log[i_scan:] if d == "process")
    ok = code(r) == "STILL-SCANNING" and scans == 1 and restarts_after == 0
    return ("PASS" if ok else "FAIL"), f"{code(r)}, scans={scans}, restarts after scan={restarts_after}"


@scenario("S8", "Very faint sample", "G3 / F20",
          "NO-SAMPLE (level 2) - never a guessed box")
def s8():
    twin, main = fresh(loaded=("faint", None, None, None))
    r = main.auto_scan(1, "brightfield")
    ok = code(r) == "NO-SAMPLE" and r.get("level") == 2 and twin.count("socket", "StartScan") == 0
    return ("PASS" if ok else "FAIL"), f"{code(r)}, level={r.get('level')}"


@scenario("S9", "No slide in the requested position", "G10",
          "NO-SLIDE (level 2)")
def s9():
    twin, main = fresh(loaded=("clear", None, None, None))
    r = main.auto_scan(3, "brightfield")
    ok = code(r) == "NO-SLIDE" and r.get("level") == 2
    return ("PASS" if ok else "FAIL"), f"{code(r)}, level={r.get('level')}"


@scenario("S10", "Scanner software not running at the start", "recovery level 1",
          "OK - started once by the co-pilot, then scanned")
def s10():
    twin, main = fresh(faults=("scanner_not_running",))
    r = main.auto_scan(1, "brightfield")
    starts = twin.count("process", "start")
    ok = code(r) == "OK" and starts == 1
    return ("PASS" if ok else "FAIL"), f"{code(r)}, starts={starts}"


@scenario("S11", "Focus clicks fail AND the good config has the automatic grid off",
          "F25", "no blind scan: refuse with FOCUS-POINTS, start no scan, never report success")
def s11():
    twin, main = fresh(faults=("focus_clicks_ignored",))
    twin.set_everywhere("Setup", "FocusDensity", "0", live_key="FocusDensity")
    r = main.auto_scan(1, "brightfield")
    scans = twin.count("socket", "StartScan")
    failed = (r.get("result") or {}).get("focus_failed")
    if code(r) == "OK" and failed:
        return "OPEN", f"reported OK although the result file says {failed} tiles failed focus"
    ok = code(r) == "FOCUS-POINTS" and scans == 0
    return ("PASS" if ok else "FAIL"), f"{code(r)}, scans={scans}"


# ---------------------------------------------------------------- Training tools

@scenario("S12", "Preview file missing when focus points are proposed", "G3 / F11",
          "refuse (ok false, preview_missing) - never take a fresh preview silently (it resets the box and points)")
def s12():
    twin, main = fresh()
    main.ensure_scanner_connected()
    found = main.run_scanner_tool("find_sample_area", {"slide_no": 0, "mode": "brightfield"})
    left, top, width, height = found["proposed_box_mm"]
    main.run_scanner_tool("set_scan_area", {"left_mm": left, "top_mm": top, "width_mm": width,
                                            "height_mm": height, "slide_no": 0})
    previews_before = twin.count("socket", "NewScan")
    twin.lose_preview_files()
    r = main.find_focus_points(3, "brightfield", 0)
    extra = twin.count("socket", "NewScan") - previews_before
    if extra:
        return "OPEN", f"took {extra} fresh preview(s) on its own"
    ok = r.get("ok") is False and r.get("preview_missing") is True
    return ("PASS" if ok else "FAIL"), (f"refused, new previews={extra}" if ok else
                                        f"no new preview, but ok={r.get('ok')}, "
                                        f"preview_missing={r.get('preview_missing')}")


@scenario("S13", "A customer's focus point sits where the co-pilot wants to click", "G8 / F12",
          "never right-click on or next to an existing point (it deletes it): skip that one, place the rest, report it")
def s13():
    twin, main = fresh()
    main.ensure_scanner_connected()
    found = main.run_scanner_tool("find_sample_area", {"slide_no": 0, "mode": "brightfield"})
    left, top, width, height = found["proposed_box_mm"]
    main.run_scanner_tool("set_scan_area", {"left_mm": left, "top_mm": top, "width_mm": width,
                                            "height_mm": height, "slide_no": 0})
    proposal = main.find_focus_points(3, "brightfield", 0)
    customer = tuple(proposal["points"][0]["px"])           # the customer already put a point there
    twin.points[0].append(customer)
    r = main.place_focus_points(0)
    deleted = twin.count("machine", "focus_point_deleted")
    if deleted:
        return "OPEN", f"right-clicked on an existing point - {deleted} point(s) deleted"
    kept = customer in twin.points[0]
    skipped = len(r.get("skipped") or [])
    ok = kept and skipped == 1 and r.get("verified_count") == 2
    return ("PASS" if ok else "FAIL"), (f"customer's point kept, skipped={skipped}, "
                                        f"placed={r.get('verified_count')}")


def good_xspeed(twin):
    cfg = configparser.RawConfigParser(strict=False)
    cfg.optionxform = str
    cfg.read(twin.good_config_for("brightfield"), encoding="utf-8")
    return cfg.get("Stage", "SpeedX20X", fallback=None)


@scenario("S14", "Scan keeps starting over from row 1 (X-speed too high, also in the good file)",
          "G4, G7, G1 / F28",
          "caught during the scan; stopped (confirmed); X-speed lowered in the good file with a "
          "backup; settings restored; scanned once more; customer told what happened and what changed")
def s14():
    twin, main = fresh(faults=("xspeed_too_high",))
    r = main.auto_scan(1, "brightfield")
    stops = twin.count("mcp", "MCP_Stop")
    scans = twin.count("socket", "StartScan")
    good = good_xspeed(twin)
    backups = list(twin.root.glob("copilot_config_backup/good_brightfield.ini.speedfix-backup-*"))
    backup_old = bool(backups) and "SpeedX20X=30000" in backups[0].read_text(encoding="utf-8")
    listed = "X-speed (20X lens): 30000 → 10000" in (r.get("settings_changed_text") or "")
    ok = (code(r) == "OK" and stops == 1 and scans == 2 and good == "10000" and backup_old
          and listed and bool(r.get("same_area_message")) and twin.live.get("SpeedX20X") == "10000")
    return ("PASS" if ok else "FAIL"), (f"{code(r)}, stops={stops}, scans={scans}, good file X-speed={good}, "
                                        f"backup with old value={backup_old}, listed={listed}, "
                                        f"message={'yes' if r.get('same_area_message') else 'no'}")


@scenario("S15", "Same as S14, but the scanner does not confirm the Stop", "G4, G3 / F28",
          "SAME-AREA-NOT-STOPPED (level 2: press Stop); nothing restarted, restored or written; 1 scan only")
def s15():
    twin, main = fresh(faults=("xspeed_too_high", "stop_not_confirmed"))
    r = main.auto_scan(1, "brightfield")
    t_stop = next((i for i, (d, a, _) in enumerate(twin.log) if d == "mcp" and a == "MCP_Stop"), None)
    after = twin.log[t_stop + 1:] if t_stop is not None else []
    touched = [a for d, a, _ in after if d == "process" or (d == "socket" and a in ("StartScan", "NewScan"))]
    good = good_xspeed(twin)
    ok = (code(r) == "SAME-AREA-NOT-STOPPED" and r.get("level") == 2 and t_stop is not None
          and not touched and good == "30000" and twin.count("socket", "StartScan") == 1)
    return ("PASS" if ok else "FAIL"), (f"{code(r)}, level={r.get('level')}, actions after Stop={touched or 'none'}, "
                                        f"good file X-speed={good}")


def write_report():
    lines = [
        "# M3 — first end-to-end runs (generated)",
        "",
        "The **real co-pilot** (unchanged) on the **virtual scanner**, no LLM: each scenario",
        "calls the co-pilot's own functions with all machine doors swapped. Generated by",
        "[`tools/m3_first_runs.py`](../tools/m3_first_runs.py).",
        "",
        "**PASS** = behaved as M1 requires · **OPEN** = a known open failure mode, reproduced",
        "· **FAIL** = unexpected.",
        "",
        "| # | Scenario | M1 | Expected | Observed | Result | s |",
        "|---|---|---|---|---|---|---|",
    ]
    for sid, title, rule, expected, observed, status, secs in RESULTS:
        mark = {"PASS": "✅ PASS", "OPEN": "🟡 OPEN", "FAIL": "❌ FAIL"}[status]
        lines.append(f"| {sid} | {title} | {rule} | {expected} | {observed} | {mark} | {secs} |")
    counts = {s: sum(1 for r in RESULTS if r[5] == s) for s in ("PASS", "OPEN", "FAIL")}
    lines += ["", f"**{counts['PASS']} pass · {counts['OPEN']} open (reproduced) · {counts['FAIL']} fail**", ""]
    text = "\n".join(lines)
    problems = leak_check.check_file("docs/m3_first_runs.md", text.encode(), leak_check.private_terms())
    if problems:
        print("report NOT written - leak check:", *problems, sep="\n  ")
        return
    (REPO / "docs" / "m3_first_runs.md").write_text(text, encoding="utf-8")
    print("\nreport: docs/m3_first_runs.md")


if __name__ == "__main__":
    for run in SCENARIOS:
        run()
    write_report()
    sys.exit(1 if any(r[5] == "FAIL" for r in RESULTS) else 0)
