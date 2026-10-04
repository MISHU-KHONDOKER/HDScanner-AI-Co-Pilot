"""Group F - finding the sample on the slide preview.

Rules from M1: G3 refuse rather than guess. Failure modes: F19 (a printed logo
taken for the sample), F20 (a very faint sample not found - still OPEN).
"""
import pytest

import scanner_find_samples_bf as bf
import scanner_find_samples_fluo as fluo
from conftest import brightfield_preview, fluo_preview


def test_brightfield_disc_is_found_where_it_is(tmp_path):
    path, (cx, cy, r) = brightfield_preview(tmp_path / "bf.png")
    found = bf.find_samples(path)
    assert len(found) == 1
    b = found[0]
    assert abs((b["x"] + b["w"] / 2) - cx) <= 6
    assert abs((b["y"] + b["h"] / 2) - cy) <= 6
    assert abs(b["w"] / 2 - r) <= 10


def test_G3_empty_slide_gives_no_sample(tmp_path):
    path, _ = brightfield_preview(tmp_path / "empty.png", disc=False)
    assert bf.find_samples(path) == []


def test_F19_logo_alone_is_not_taken_for_a_sample(tmp_path):
    path, _ = brightfield_preview(tmp_path / "logo.png", disc=False, logo=True)
    assert bf.find_samples(path) == []


def test_F19_logo_next_to_a_real_disc_does_not_move_the_answer(tmp_path):
    path, (cx, cy, _) = brightfield_preview(tmp_path / "both.png", logo=True)
    b = bf.find_samples(path)[0]
    assert abs((b["x"] + b["w"] / 2) - cx) <= 6 and abs((b["y"] + b["h"] / 2) - cy) <= 6


def test_F20_very_faint_disc_is_reported_as_not_found_never_guessed(tmp_path):
    path, _ = brightfield_preview(tmp_path / "faint.png", contrast=1, cells=False)
    assert bf.find_samples(path) == []


@pytest.mark.xfail(strict=True, reason="F20 is OPEN: very faint samples are missed (M1)")
def test_F20_open_very_faint_disc_should_be_found(tmp_path):
    path, _ = brightfield_preview(tmp_path / "faint.png", contrast=1, cells=False)
    assert len(bf.find_samples(path)) == 1


def test_fluorescence_and_simulator_sample_is_found(tmp_path):
    found = fluo.find_samples(fluo_preview(tmp_path / "sim.png"))
    assert len(found) == 1
    assert (found[0]["x"], found[0]["y"], found[0]["w"], found[0]["h"]) == (700, 200, 100, 100)


def test_G3_fluorescence_blank_slide_gives_no_sample(tmp_path):
    assert fluo.find_samples(fluo_preview(tmp_path / "blank.png", square=False)) == []
