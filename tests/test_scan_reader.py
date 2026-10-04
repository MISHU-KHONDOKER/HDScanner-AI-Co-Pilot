"""Group C - reading a scan's result file (scan_reader.py).

Rules from M1: G1 honesty (report what the file says; a missing field stays
missing). Failure modes: F03 (a status code misread as a verdict), F04 (results
looked for in another PC's folder).
"""
import os
import time

import scan_reader
from conftest import write_ini

# A made-up result file, built from a dict (like the config tests) so the source
# never contains a literal scanner section block.
SCAN = {
    "General": {"SlideID": "CUSTOMER-20260101-120000-S1", "SlideType": "TCT",
                "Magnification": "20X", "FieldWidth": "595.3", "RowCount": "11",
                "ColumnCount": "12", "Quantity": "132", "ScanStopped": "0",
                "Clarity": "7.5", "StitchMode": "2", "FocusMode": "1"},
    "Focus": {"F0": "25.4/25.4/0.0um", "F1": "30.0/20.0/0.0um", "Failed": "0"},
    "Camera": {"ExpoTime": "1212", "ExpoGain": "1"},
}


def _write_scan(root, day, sample_id):
    folder = root / day / sample_id
    folder.mkdir(parents=True)
    path = folder / "Scan.txt"
    write_ini(path, SCAN)
    return path


def test_parses_the_summary_fields(tmp_path):
    s = scan_reader.parse_scan_txt(str(_write_scan(tmp_path, "2026-01-01", "S1")))
    assert s["ok"] is True
    assert s["tile_count"] == 132
    assert s["tile_grid"] == "11x12"
    assert s["field_width_um"] == 595.3
    assert s["focus_points"] == ["25.4/25.4/0.0um", "30.0/20.0/0.0um"]
    assert s["focus_failed"] == 0
    assert s["exposure_us"] == 1212


def test_F03_status_flag_is_reported_raw_never_as_a_verdict(tmp_path):
    s = scan_reader.parse_scan_txt(str(_write_scan(tmp_path, "2026-01-01", "S1")))
    assert s["scan_stopped"] == "0"            # raw text, not True/False/"failed"
    assert "success" not in s and "failed" not in s


def test_G1_missing_fields_are_none_not_invented(tmp_path):
    s = scan_reader.parse_scan_txt(str(_write_scan(tmp_path, "2026-01-01", "S1")))
    assert s["focus_stddev"] is None           # not in this file
    assert s["focus_plane"] is None


def test_G9_unreadable_file_is_reported_not_raised(tmp_path):
    s = scan_reader.parse_scan_txt(str(tmp_path / "missing" / "Scan.txt"))
    assert s["ok"] is False and "error" in s


def test_F04_finds_a_scan_by_id_in_this_machines_results_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_reader, "SCAN_RESULTS_DIR", str(tmp_path))
    _write_scan(tmp_path, "2026-01-01", "OTHER-1")
    wanted = _write_scan(tmp_path, "2026-01-02", "CUSTOMER-20260102-090000-S2")
    assert scan_reader.find_scan_txt("CUSTOMER-20260102-090000-S2") == str(wanted)


def test_unknown_scan_id_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_reader, "SCAN_RESULTS_DIR", str(tmp_path))
    _write_scan(tmp_path, "2026-01-01", "S1")
    assert scan_reader.find_scan_txt("NOT-THERE") is None


def test_without_an_id_the_newest_scan_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_reader, "SCAN_RESULTS_DIR", str(tmp_path))
    old = _write_scan(tmp_path, "2026-01-01", "OLD")
    new = _write_scan(tmp_path, "2026-01-02", "NEW")
    past = time.time() - 3600
    os.utime(old, (past, past))
    assert scan_reader.find_scan_txt() == str(new)


def test_no_results_at_all_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_reader, "SCAN_RESULTS_DIR", str(tmp_path))
    assert scan_reader.find_scan_txt() is None
