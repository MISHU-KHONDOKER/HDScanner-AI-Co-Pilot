"""The test suite itself must never touch a real program (see conftest.py)."""
import subprocess

import pytest

import customer_config as cc
from conftest import ProcessCallBlocked


@pytest.mark.parametrize("call", [
    lambda: cc.stop_hdscanner(),
    lambda: cc.start_hdscanner("anything.exe"),
    lambda: cc.close_hdscanner_normally(),
    lambda: subprocess.run(["taskkill", "/F", "/IM", "anything.exe"]),
])
def test_closing_or_starting_programs_is_blocked_in_tests(call):
    with pytest.raises(ProcessCallBlocked):
        call()
