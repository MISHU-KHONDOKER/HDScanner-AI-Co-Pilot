"""Load the REAL co-pilot with its five machine doors swapped for the virtual scanner.

The co-pilot's code is not changed. It is imported from the private project, and
before anything runs, every name through which it can touch a machine is
replaced by the virtual scanner's version. The harness then REFUSES to continue
if any machine-touching name is still the real one, and it blocks the real
scanner's control port and every attempt to start or stop a program.

    from virtual_scanner import VirtualScanner
    from virtual_scanner.harness import load_copilot

    twin = VirtualScanner(tmp_dir, mode="brightfield")
    copilot = load_copilot(private_root, twin)
    copilot.auto_scan(slide=1, mode="brightfield")
"""
import contextlib
import importlib
import os
import socket
import subprocess
import sys
from pathlib import Path

SCANNER_PORT = 58207

# Modules whose objects talk to a real machine. No object from these may remain
# reachable from the co-pilot's namespace after swapping.
MACHINE_MODULES = {"scanner_gui", "scanner_client", "scanner_mcp_client"}

# Program-control names, in the co-pilot and in its config module.
PROCESS_IN_COPILOT = {"stop_hdscanner": "stop_hdscanner", "start_hdscanner": "start_hdscanner"}
PROCESS_IN_CONFIG = {
    "close_hdscanner_normally": "close_hdscanner_normally",
    "stop_hdscanner": "stop_hdscanner",
    "start_hdscanner": "start_hdscanner",
    "_hdscanner_running": "hdscanner_running",
    "_socket_up": "socket_up",
    "_wait_for_socket": "socket_up",
}

# The co-pilot's own modules: dropped from the import cache so every load is fresh.
PRIVATE_MODULES = ("app", "app.main", "customer_config", "scan_reader", "scanner_client",
                   "scanner_gui", "scanner_mcp_client", "scanner_focus", "scanner_focus_placement",
                   "scanner_sample_area", "scanner_find_samples_bf", "scanner_find_samples_fluo",
                   "scanner_focus_points_bf", "scanner_focus_points_fluo")


class DoorNotSwapped(RuntimeError):
    """A machine-touching name is still the real one - refusing to run."""


class RealMachineBlocked(RuntimeError):
    """Something tried to reach a real program or the real scanner port."""


# ------------------------------------------------------------------ blocks

_originals = {}


def _blocked_process(*args, **kwargs):
    raise RealMachineBlocked(f"blocked: tried to run a real program {args[:1]!r}")


class _BlockedPopen(subprocess.Popen):
    """Still a class (the standard library subclasses Popen at import time), but
    creating one - i.e. starting a program - is refused."""

    def __init__(self, *args, **kwargs):
        _blocked_process(*args, **kwargs)


def _guarded_create_connection(address, *args, **kwargs):
    if address and address[1] == SCANNER_PORT:
        raise RealMachineBlocked("blocked: tried to reach the real scanner port")
    return _originals["create_connection"](address, *args, **kwargs)


def _guarded_connect(self, address):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] == SCANNER_PORT:
        raise RealMachineBlocked("blocked: tried to reach the real scanner port")
    return _originals["socket_connect"](self, address)


def install_blocks():
    """No real program can be started or stopped; the scanner port is unreachable."""
    if _originals:
        return
    _originals.update(run=subprocess.run, Popen=subprocess.Popen,
                      create_connection=socket.create_connection,
                      socket_connect=socket.socket.connect)
    subprocess.run = _blocked_process
    subprocess.Popen = _BlockedPopen
    socket.create_connection = _guarded_create_connection
    socket.socket.connect = _guarded_connect


def remove_blocks():
    if not _originals:
        return
    subprocess.run, subprocess.Popen = _originals["run"], _originals["Popen"]
    socket.create_connection = _originals["create_connection"]
    socket.socket.connect = _originals["socket_connect"]
    _originals.clear()


# ------------------------------------------------------------------ loading

@contextlib.contextmanager
def _inside(folder):
    old = os.getcwd()
    os.chdir(folder)
    try:
        yield
    finally:
        os.chdir(old)


def load_copilot(private_root, twin):
    """Import the private co-pilot fresh, wired to `twin`. Returns its main module."""
    private_root = str(Path(private_root).resolve())
    install_blocks()
    # Point every path the co-pilot reads at the virtual scanner's folder. These are
    # set before import, so the private .env cannot point them at a real machine.
    os.environ.update({
        "HDSCANNER_DIR": str(twin.root),
        "HDSCANNER_EXE": str(twin.exe_path),
        "HDSCANNER_CONFIG": str(twin.config_path),
        "SCAN_RESULTS_DIR": str(twin.results),
        "CUSTOMER_LIVE_CHECK": "1",
    })
    for name in PRIVATE_MODULES:
        sys.modules.pop(name, None)
    if private_root not in sys.path:
        sys.path.insert(0, private_root)
    with _inside(private_root):
        main = importlib.import_module("app.main")
    config = sys.modules["customer_config"]

    # Door 1 + 2: the socket and MCP clients (and their classes).
    main.scanner = twin.socket
    main.mcp_scanner = twin.mcp
    main.HDScannerClient = type(twin.socket)
    main.HDScannerMCPClient = type(twin.mcp)
    main._mcp_started = False
    main._mcp_tools_cache = None
    # Door 3: the GUI functions.
    for name in twin.gui.NAMES:
        setattr(main, name, getattr(twin.gui, name))
    # Door 4: program control, in the co-pilot and in its config module.
    for name, attr in PROCESS_IN_COPILOT.items():
        setattr(main, name, getattr(twin.process, attr))
    for name, attr in PROCESS_IN_CONFIG.items():
        setattr(config, name, getattr(twin.process, attr))
    # Which good config belongs to this (virtual) machine and mode.
    main.good_config_for = twin.good_config_for

    check_all_doors_swapped(main, config, twin)
    return main


def check_all_doors_swapped(main, config, twin):
    """Refuse to run if anything that can touch a real machine is still reachable."""
    problems = []
    for name, obj in vars(main).items():
        module = getattr(obj, "__module__", None) or getattr(type(obj), "__module__", None)
        if module in MACHINE_MODULES:
            problems.append(f"co-pilot.{name} is still the real {module} object")
    for name, attr in PROCESS_IN_COPILOT.items():
        if getattr(main, name) != getattr(twin.process, attr):
            problems.append(f"co-pilot.{name} is not the virtual one")
    for name, attr in PROCESS_IN_CONFIG.items():
        if getattr(config, name) != getattr(twin.process, attr):
            problems.append(f"customer_config.{name} is not the virtual one")
    if problems:
        raise DoorNotSwapped("refusing to run - real machine doors left open:\n  "
                             + "\n  ".join(problems))
