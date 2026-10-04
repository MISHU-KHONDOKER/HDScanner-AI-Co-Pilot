"""Where the scanner software lives on this machine.

The private co-pilot gets these from its scanner protocol client, which is not
published. Here they come only from the environment (.env), with no built-in
machine path: a missing setting must show up as a missing setting, not as a
silent fallback to some other PC's folder (failure mode F11 in M1).
"""
import os

from dotenv import load_dotenv

load_dotenv()

HDSCANNER_DIR = os.getenv("HDSCANNER_DIR", "")
HDSCANNER_EXE = os.getenv("HDSCANNER_EXE", "")
