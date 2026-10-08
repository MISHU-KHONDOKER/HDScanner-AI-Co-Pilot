"""M3 - the virtual scanner behaves like the real one (each test names its source).

These run in CI. They test the twin on its own; the co-pilot runs against it in
tools/m3_first_runs.py (needs the private project).
"""
import socket
import time
import types

import pytest

from virtual_scanner import VirtualScanner
from virtual_scanner import harness
from virtual_scanner.twin import MACHINE_KEY


@pytest.fixture
def twin(tmp_path):
    t = VirtualScanner(tmp_path / "scanner", "brightfield", ("clear", "clear", None, None))
    t.socket.connect()
    return t


def test_one_preview_reply_per_loaded_slide(twin):           # real 4-slide loader, 2026-09-26
    twin.socket.new_scan(slide_no=0)
    assert twin.socket.last_preview_slides == [0, 1]


def test_empty_position_gives_no_preview(twin):
    assert twin.socket.new_scan(slide_no=2) is None


def test_a_preview_clears_the_focus_points(twin):            # real, 2026-09-24
    twin.socket.new_scan()
    x, y, w, h = twin.box_px()
    twin.gui.place_focus_points_by_click([[x + w // 2, y + h // 2]], slide=0)
    assert twin.points[0]
    twin.socket.new_scan()
    assert twin.points[0] == []


def test_click_outside_the_box_is_ignored(twin):             # real, 2026-09-30
    twin.socket.new_scan()
    r = twin.gui.place_focus_points_by_click([[1, 1]], slide=0)
    assert r["verified_count"] == 0 and twin.points[0] == []


def test_right_click_on_an_existing_point_deletes_it(twin):  # real, 2026-09-29
    twin.socket.new_scan()
    x, y, w, h = twin.box_px()
    p = [x + w // 2, y + h // 2]
    twin.gui.place_focus_points_by_click([p], slide=0)
    twin.gui.place_focus_points_by_click([p], slide=0)
    assert twin.points[0] == []


def test_scan_without_a_box_keeps_the_points_with_a_box_wipes_them(twin):   # real, 2026-09-29
    twin.socket.new_scan()
    x, y, w, h = twin.box_px()
    twin.gui.place_focus_points_by_click([[x + w // 2, y + h // 2]], slide=0)
    twin.socket.start_scan(0, "A")
    assert twin.points[0]
    twin.socket.start_scan(0, "B", x, y, w, h)
    assert twin.points[0] == []


def test_real_scanner_reports_zero_on_a_perfect_scan(twin):  # real, 2026-09-30
    twin.socket.start_scan(0, "S1")
    assert twin.socket.wait_for_scan_finished()["result"] == 0
    assert list(twin.results.glob("*/S1/Scan.txt"))


def _focus_of(twin, sample_id):
    import configparser
    cp = configparser.RawConfigParser()
    cp.optionxform = str
    cp.read(next(twin.results.glob(f"*/{sample_id}/Scan.txt")), encoding="utf-8")
    return dict(cp["Focus"])


def test_focused_result_file_has_the_real_format(twin):      # real Scan.txt, 2026-09-26..30
    twin.socket.new_scan()
    x, y, w, h = twin.box_px()
    twin.gui.place_focus_points_by_click([[x + w // 3, y + h // 2], [x + 2 * w // 3, y + h // 2]], slide=0)
    twin.socket.start_scan(0, "S1")
    focus = _focus_of(twin, "S1")
    assert [k for k in focus if k.startswith("F") and k[1:].isdigit()] == ["F0", "F1"]
    assert all(focus[k].endswith("um -0.0") and focus[k].count("/") == 2 for k in ("F0", "F1"))
    assert focus["Z"].startswith("0.000000X") and focus["StdDev"] == "0.00"
    assert focus["Excluded"] == "0" and focus["Failed"] in ("0", "1")   # 1 seen on a SHARP scan


def test_unfocused_result_is_marked_as_an_assumption(twin):  # ASSUMPTION - no real file yet
    twin.live["FocusDensity"] = "0"
    twin.socket.new_scan()
    twin.socket.start_scan(0, "S2")
    assert _focus_of(twin, "S2") == {"Failed": "132"}


def test_simulator_code_fault(tmp_path):
    t = VirtualScanner(tmp_path, faults=("simulator_result_code",))
    t.socket.connect()
    t.socket.start_scan(0, "S1")
    assert t.socket.wait_for_scan_finished()["result"] == 1


def test_no_scan_started_fault_still_scans(tmp_path):        # real build, 2026-09-29
    t = VirtualScanner(tmp_path, faults=("no_scan_started",))
    t.socket.connect()
    assert t.socket.start_scan(0, "S1") is None
    assert t.socket.wait_for_scan_finished() is not None


def test_calibration_dialog_freezes_the_scan(tmp_path):      # real, 2026-09-18
    t = VirtualScanner(tmp_path, faults=("calibration_modal",))
    t.socket.connect()
    assert t.socket.start_scan(0, "S1") is None
    assert t.socket.wait_for_scan_finished() is None


def test_early_stop_result_file_comes_later(tmp_path):       # real, 2026-09-26
    t = VirtualScanner(tmp_path, faults=("early_scan_stopped",))
    t.result_delay_s = 0.3
    t.socket.connect()
    t.socket.start_scan(0, "S1")
    assert t.socket.wait_for_scan_finished() is not None
    assert not list(t.results.glob("*/S1/Scan.txt"))
    time.sleep(0.4)
    t.flush_results()
    assert list(t.results.glob("*/S1/Scan.txt"))


def test_normal_close_writes_the_live_values(twin):          # real, 2026-09-26
    twin.gui.set_focus_density("10")
    twin.process.close_hdscanner_normally()
    assert "FocusDensity=10" in twin.config_path.read_text(encoding="utf-8")


def test_foreign_licence_key_stops_the_software_starting(twin):   # real, 2026-09-30
    text = twin.config_path.read_text(encoding="utf-8")
    twin.config_path.write_text(text.replace(MACHINE_KEY, "BBBB2222FAKE"), encoding="utf-8")
    twin.process.stop_hdscanner()
    assert twin.process.start_hdscanner() is False


def test_scrambled_settings_differ_from_the_good_file(tmp_path):
    t = VirtualScanner(tmp_path, faults=("scrambled_settings",))
    assert t.live["FocusDensity"] == "0" and "FocusDensity=4" in t.good_bf.read_text(encoding="utf-8")


def test_settings_reject_values_the_software_does_not_offer(twin):
    r = twin.gui.set_stitch_mode("Sideways")
    assert r["ok"] is False and "Seamless" in r["options"]


def test_unknown_fault_is_refused(tmp_path):
    with pytest.raises(ValueError):
        VirtualScanner(tmp_path, faults=("made_up",))


# ------------------------------------------------------------------ harness safety

def test_harness_refuses_a_real_door_left_open(twin):
    fake_main = types.ModuleType("fake_main")
    real_looking = lambda: None                          # noqa: E731
    real_looking.__module__ = "scanner_gui"
    fake_main.get_anti_blur = real_looking
    for name, attr in harness.PROCESS_IN_COPILOT.items():
        setattr(fake_main, name, getattr(twin.process, attr))
    fake_config = types.ModuleType("fake_config")
    for name, attr in harness.PROCESS_IN_CONFIG.items():
        setattr(fake_config, name, getattr(twin.process, attr))
    with pytest.raises(harness.DoorNotSwapped):
        harness.check_all_doors_swapped(fake_main, fake_config, twin)


def test_harness_blocks_the_real_scanner_port():
    harness.install_blocks()
    try:
        with pytest.raises(harness.RealMachineBlocked):
            socket.create_connection(("127.0.0.1", harness.SCANNER_PORT), timeout=1)
    finally:
        harness.remove_blocks()


# ---- F28: "the scanner scans the same area again and again" (real, 2026-10-08) ----

def test_tiles_are_named_like_the_real_files(twin):          # real message log, 2026-09-29..10-08
    twin.socket.start_scan(0, "S1")
    tiles = [m["result"] for m in twin.socket._inbox if m.get("method") == "ScannedImage"]
    assert tiles and all("/S1/Images/IMG" in t and t.endswith(".jpg") for t in tiles)


def test_safe_xspeed_scans_normally(twin):
    twin.socket.start_scan(0, "S1")
    assert twin.socket.wait_for_scan_finished_or_repeat() == {"method": "ScanStopped", "result": 0}


def test_xspeed_too_high_scan_starts_over_from_row_1(tmp_path):   # real, 2026-10-08
    t = VirtualScanner(tmp_path, faults=("xspeed_too_high",))
    t.socket.connect()
    assert t.socket.start_scan(0, "S1") is not None
    r = t.socket.wait_for_scan_finished_or_repeat()
    assert r["method"] == "SameAreaRepeat" and r["tile"].endswith("IMG001x001.jpg")
    assert r["tiles_before"] == 6                               # rows 1-2 once, then row 1 again
    assert t.round_scan == "S1"                                 # still running: no ScanStopped


def test_the_too_high_speed_is_in_the_good_file_too(tmp_path):
    t = VirtualScanner(tmp_path, faults=("xspeed_too_high",))
    good = t.good_config_for("brightfield")
    assert "SpeedX20X=30000" in open(good, encoding="utf-8").read()


def test_stop_ends_a_scan_going_round(tmp_path):              # real Stop: ScanStopped -1
    t = VirtualScanner(tmp_path, faults=("xspeed_too_high",))
    t.socket.connect()
    t.socket.start_scan(0, "S1")
    t.socket.wait_for_scan_finished_or_repeat()
    t.mcp.call_tool("MCP_Stop")
    assert t.socket.wait_for("ScanStopped") == {"method": "ScanStopped", "result": -1}
    assert t.round_scan is None


def test_stop_not_confirmed_fault(tmp_path):                  # ASSUMPTION - not seen on the real scanner
    t = VirtualScanner(tmp_path, faults=("xspeed_too_high", "stop_not_confirmed"))
    t.socket.connect()
    t.socket.start_scan(0, "S1")
    t.socket.wait_for_scan_finished_or_repeat()
    t.mcp.call_tool("MCP_Stop")
    assert t.socket.wait_for("ScanStopped") is None
    assert t.round_scan == "S1"


def test_safe_xspeed_after_restart_scans_normally(tmp_path):
    t = VirtualScanner(tmp_path, faults=("xspeed_too_high",))
    t.set_everywhere("Stage", "SpeedX20X", "10000")
    t.process.stop_hdscanner()
    t.process.start_hdscanner()
    t.socket.connect()
    t.socket.start_scan(0, "S2")
    assert t.socket.wait_for_scan_finished_or_repeat()["method"] == "ScanStopped"


def test_start_notices_a_settings_file_written_from_outside(twin):     # for the M4 scorer (G5, G7)
    twin.process.close_hdscanner_normally()          # the software's own save: not "outside"
    twin.process.start_hdscanner()
    assert twin.count("files", "config_written_from_outside") == 0
    twin.process.stop_hdscanner()
    twin.config_path.write_text(twin.config_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    twin.process.start_hdscanner()
    assert twin.count("files", "config_written_from_outside") == 1


def test_result_file_records_the_scanned_area_like_the_real_one(twin):   # real Scan.txt, 2026-10-06
    twin.scan_region_mm = [13.0, 0.4, 22.6, 22.4]
    twin.socket.start_scan(0, "S1")
    twin.socket.wait_for_scan_finished()
    scan = next(twin.results.rglob("S1/Scan.txt")).read_text(encoding="utf-8")
    assert "Left=13.0" in scan and "Top=0.4" in scan and "Size=22.6x22.4" in scan
    assert "Clarity" not in scan                                 # the real build writes none


def test_result_picture_is_saved_like_the_real_one(twin):    # real Thumbs/Result-<id>.jpg, 2026-10-06
    twin.socket.start_scan(0, "S1")
    twin.socket.wait_for_scan_finished()
    assert next(twin.results.rglob("S1/Thumbs/Result-S1.jpg")).stat().st_size > 0
