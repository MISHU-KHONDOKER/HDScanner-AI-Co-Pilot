"""Group D - geometry and bounds (scanner_sample_area.py).

Rules from M1: G8 bounds (a box never leaves the slide), G2 verify by read-back
(needs the right scale). Failure mode: F24 (real slide size and non-square
pixels made a correct box fail verification).
"""
import pytest

import scanner_sample_area as sa
from conftest import fluo_preview, write_ini


def test_F24_scale_comes_from_the_machines_slide_size_per_axis(tmp_path):
    cfg = write_ini(tmp_path / "config.ini", {"Slide": {"Width": "75.0", "Height": "25.0"}})
    sx, sy, w_mm, h_mm = sa.slide_scale(1882, 632, cfg)
    assert sx == pytest.approx(75.0 / 1882)
    assert sy == pytest.approx(25.0 / 632)
    assert sx != pytest.approx(sy, rel=1e-3)     # pixels are NOT square on this machine
    assert (w_mm, h_mm) == (75.0, 25.0)


def test_scale_without_a_slide_size_uses_the_simulator_default(tmp_path):
    sx, sy, w_mm, _ = sa.slide_scale(1500, 500, str(tmp_path / "no-config.ini"))
    assert sx == sy == pytest.approx(76.2 / 1500)
    assert w_mm == 76.2


@pytest.mark.parametrize("box, expected", [
    ((10, 10, 50, 30), (10, 10, 50, 30)),        # already inside
    ((-5, -8, 50, 50), (0, 0, 45, 42)),          # sticks out top-left
    ((90, 40, 50, 50), (90, 40, 10, 10)),        # sticks out bottom-right
])
def test_G8_box_is_clamped_inside_the_slide(box, expected):
    assert sa._clamp_box(*box, img_w=100, img_h=50) == expected


def test_pixels_to_millimetres():
    assert sa._to_mm([100, 50, 20, 10], 0.05, 0.04) == [5.0, 2.0, 1.0, 0.4]


def test_proposal_has_a_margin_and_stays_on_the_slide(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "_CONFIG", str(tmp_path / "no-config.ini"))
    preview = fluo_preview(tmp_path / "preview.png")
    r = sa.propose_sample_area(preview, margin_px=10)
    assert r["ok"] is True and r["samples_found"] == 1
    x, y, w, h = r["proposed_box_px"]
    assert (x, y, w, h) == (690, 190, 120, 120)  # 100 px sample + 10 px each side


def test_G3_no_sample_means_no_box(tmp_path):
    preview = fluo_preview(tmp_path / "blank.png", square=False)
    r = sa.propose_sample_area(preview)
    assert r["ok"] is False and r["samples_found"] == 0
    assert "proposed_box_px" not in r
