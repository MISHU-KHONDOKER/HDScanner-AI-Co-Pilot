"""Group E - choosing focus points (scanner_focus_points_bf.py).

Rules from M1: G8 bounds (points on the sample and inside the scan box),
G3 refuse rather than guess. Failure mode: F10 (points outside the scan box are
silently ignored by the machine).
"""
import math

import pytest

import scanner_focus_points_bf as fp
from conftest import brightfield_preview


def _triangle_area(a, b, c):
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2


def test_one_point_goes_to_the_centre():
    assert fp.ideal_layout(1, 100, 50, 30, 30) == [(100, 50)]


def test_three_points_make_a_triangle_never_a_line():
    a, b, c = fp.ideal_layout(3, 100, 100, 50, 50)
    assert _triangle_area(a, b, c) > 1000


@pytest.mark.parametrize("count", [2, 5, 7, 20, 40])
def test_layout_has_the_requested_count_inside_the_allowed_oval(count):
    pts = fp.ideal_layout(count, 100, 100, 60, 40)
    assert len(pts) == count
    for x, y in pts:
        assert ((x - 100) / 60) ** 2 + ((y - 100) / 40) ** 2 <= 1.0001


def test_chosen_points_keep_the_minimum_gap():
    spots = [(x, y, 5) for x in range(0, 100, 2) for y in range(0, 100, 2)]
    ideal = [(10, 10), (11, 11), (12, 12), (80, 80)]
    chosen = fp.choose_points(spots, ideal, snap_px=5, min_gap_px=8)
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            assert math.hypot(a[0] - b[0], a[1] - b[1]) >= 8


def test_G8_points_lie_inside_the_safe_part_of_the_disc(tmp_path):
    path, (cx, cy, r) = brightfield_preview(tmp_path / "bf.png")
    res = fp.propose_bf_points(path, 5)
    assert res["ok"] is True and len(res["points_px"]) == 5
    safe = res["disc_px"]["r_safe"]
    for x, y in res["points_px"]:
        assert math.hypot(x - res["disc_px"]["cx"], y - res["disc_px"]["cy"]) <= safe + 1


def test_F10_with_a_scan_box_every_point_is_inside_the_box(tmp_path):
    path, (cx, cy, r) = brightfield_preview(tmp_path / "bf.png")
    box = [cx - 20, cy - 90, 110, 90]          # a small box in the upper right of the disc
    res = fp.propose_bf_points(path, 10, box_px=box)
    assert res["ok"] is True and res["points_px"]
    bx, by, bw, bh = box
    for x, y in res["points_px"]:
        assert bx < x < bx + bw and by < y < by + bh


def test_G3_no_disc_means_no_points(tmp_path):
    path, _ = brightfield_preview(tmp_path / "empty.png", disc=False)
    res = fp.propose_bf_points(path, 3)
    assert res["ok"] is False and "not guessing" in res["error"]


def test_count_below_one_is_refused(tmp_path):
    path, _ = brightfield_preview(tmp_path / "bf.png")
    assert fp.propose_bf_points(path, 0)["ok"] is False
