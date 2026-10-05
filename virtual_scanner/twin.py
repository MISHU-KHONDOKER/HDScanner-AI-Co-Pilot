"""The virtual scanner: a small, predictable model of the real slide scanner.

It replaces the five "doors" through which the co-pilot touches the machine:

  1. socket client   -> VirtualSocketClient  (preview, scan, scan events)
  2. MCP client      -> VirtualMCPClient     (scan parameters, events, preset focus)
  3. GUI automation  -> VirtualGUI           (the 12 GUI functions the co-pilot imports)
  4. program control -> VirtualProcess       (close normally / force-close / start)
  5. files           -> a temporary scanner folder: config.ini, CapturedImages/, scanresults/

Every behaviour is copied from something observed on the real scanner; the
source of each one is listed in docs/M3_virtual_instrument.md (fidelity table).

Faults are switched on explicitly (see FAULTS). With no faults the twin behaves
like a healthy real scanner.
"""
import configparser
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import slides as slide_art

MACHINE_KEY = "AAAA1111FAKE"           # this virtual machine's licence key (made up)
OTHER_MACHINE_KEY = "BBBB2222FAKE"     # another machine's key (made up)
SLIDE_MM = (75.0, 25.0)

ANTI_BLUR_OPTIONS = ["0", "5", "10", "15", "20", "30", "50", "100", "200", "500", "1000"]
SLIDE_TYPES = ["Generic", "TCT", "IHC", "HE", "FLUO", "WP6", "WP12", "WP24", "WP48",
               "WP96", "WP240", "WP384", "WP1536"]
STITCH_MODES = ["Seamless", "Seamless+", "Tiled", "Custom"]
FOCUS_DENSITIES = ["0", "1", "2", "3", "4", "5", "6", "8", "10", "12", "16", "20"]

FAULTS = {
    "other_machine_good_file": "F01: the good config belongs to another machine (different licence key)",
    "wrong_mode_good_file": "F02: the good config is the other imaging mode's file",
    "simulator_result_code": "F03 (inverse): ScanStopped says 1 (simulator) instead of 0 (real scanner)",
    "early_scan_stopped": "F05: ScanStopped arrives at once, the result file only much later",
    "no_scan_started": "F06: the scanner never sends ScanStarted (real build behaviour)",
    "calibration_modal": "F13: calibration mode is on; a blocking dialog freezes every scan",
    "focus_clicks_ignored": "focus-point clicks are not accepted (real build, 0 of 3, 2026-09-26)",
    "scrambled_settings": "settings changed in the window and saved (the in-house scramble test)",
    "scanner_not_running": "the scanner software is not running at the start",
}


def _write_ini(path, sections):
    lines = []
    for section, values in sections.items():
        lines.append(f"[{section}]")
        lines += [f"{k}={v}" for k, v in values.items()]
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# Real preview scale: 75.0 mm across a 1882 px preview (real scanner config).
UM_PER_PREVIEW_PX = 75000 / 1882
FOCUS_Z_UM = 2250.0           # real focus heights were 2240-2310 um


def _focus_section(points, auto_grid, tiles):
    """The result file's [Focus] section.

    OBSERVED (3 real Customer scans, 2026-09-26..30, all sharp): one line per focus
    point "x/y/zum -0.0" in micrometres, a fitted plane "Z=aX+bY+c", StdDev,
    Excluded, and Failed=0 or Failed=1 - Failed=1 on a SHARP scan, so it is not a
    verdict. Positions here are preview px x the real scale; the stage offset is
    not modelled (nothing reads the numbers).

    ASSUMPTIONS (no real file seen yet - see docs/M3_virtual_instrument.md):
    - focus by the scanner's own grid only (no placed points): plane, no F lines;
    - no focus at all: no F lines, no plane, Failed = every tile.
    """
    plane = {"Z": f"0.000000X+0.000000Y+{FOCUS_Z_UM:.6f}", "StdDev": "0.00",
             "Excluded": "0", "Failed": "0"}
    if points:
        lines = {f"F{i}": f"{x * UM_PER_PREVIEW_PX:.1f}/{y * UM_PER_PREVIEW_PX:.1f}/{FOCUS_Z_UM:.1f}um -0.0"
                 for i, (x, y) in enumerate(points)}
        return {**lines, **plane}
    if auto_grid:
        return plane                          # ASSUMPTION
    return {"Failed": str(tiles)}             # ASSUMPTION


def _read_ini(path):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    with open(path, encoding="utf-8-sig") as f:
        cp.read_file(f)
    return cp


class VirtualScanner:
    """State of one virtual scanner + its five doors."""

    def __init__(self, root, mode="brightfield", loaded=("clear", None, None, None), faults=()):
        unknown = set(faults) - set(FAULTS)
        if unknown:
            raise ValueError(f"unknown fault(s): {sorted(unknown)}")
        self.root = Path(root)
        self.mode = mode
        self.loaded = list(loaded)              # slide kind per loader position, None = empty
        self.faults = set(faults)
        self.log = []                            # every door call: (door, action, detail)
        self.result_delay_s = 10.0               # for early_scan_stopped

        self.captured = self.root / "CapturedImages"
        self.results = self.root / "scanresults"
        self.captured.mkdir(parents=True, exist_ok=True)
        self.results.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "config.ini"
        self.exe_path = self.root / "HDScanner.exe"
        self.good_bf = self.root / "good_brightfield.ini"
        self.good_fluo = self.root / "good_fluorescence.ini"

        _write_ini(self.good_bf, self._config("brightfield"))
        _write_ini(self.good_fluo, self._config("fluorescence"))
        if "other_machine_good_file" in self.faults:
            for p in (self.good_bf, self.good_fluo):
                p.write_text(p.read_text(encoding="utf-8").replace(MACHINE_KEY, OTHER_MACHINE_KEY),
                             encoding="utf-8")
        if "wrong_mode_good_file" in self.faults:
            other = "fluorescence" if mode == "brightfield" else "brightfield"
            shutil.copy(self.good_bf if other == "brightfield" else self.good_fluo,
                        self.good_bf if mode == "brightfield" else self.good_fluo)

        live_cfg = self._config(mode)
        if "scrambled_settings" in self.faults:
            live_cfg["Setup"].update(AntiBlur="50", FocusDensity="0", StitchMode="0")
            live_cfg["Slide"]["Type"] = "Generic"
        _write_ini(self.config_path, live_cfg)

        self.running = False
        self.calibration = "calibration_modal" in self.faults
        self.live = {}
        self.scan_region_mm = None
        self.points = {i: [] for i in range(4)}   # green scan-area focus points (preview px)
        self.preset_points = []                    # magenta preset points (stage um)
        self.preview_taken = False
        self.messages = []                         # (time, message) from the scanner
        self.mcp_events = []
        self.pending_results = []                  # (due_time, sample_id, slide_no, focus_points)
        if "scanner_not_running" not in self.faults:
            self._start()

        self.socket = VirtualSocketClient(self)
        self.mcp = VirtualMCPClient(self)
        self.gui = VirtualGUI(self)
        self.process = VirtualProcess(self)

    # ------------------------------------------------------------ state helpers

    def _config(self, mode):
        fluo = mode != "brightfield"
        return {
            "Controller": {"Key": MACHINE_KEY},
            "Camera": {"Model": "CameraVirtual"},
            "Setup": {"ImagingFluo": "true" if fluo else "false", "AntiBlur": "10",
                      "FocusDensity": "4", "StitchMode": "2"},
            "Slide": {"Type": "FLUO" if fluo else "TCT",
                      "Width": str(SLIDE_MM[0]), "Height": str(SLIDE_MM[1]),
                      "ScanLeft": "5.0", "ScanTop": "5.0", "ScanWidth": "5.0", "ScanHeight": "5.0"},
            "Scan": {"InputPath": "virtual", "ResultsPath": str(self.results)},
        }

    def good_config_for(self, mode):
        return str(self.good_bf if mode == "brightfield" else self.good_fluo)

    def note(self, door, action, detail=None):
        self.log.append((door, action, detail))

    def count(self, door, action):
        return sum(1 for d, a, _ in self.log if d == door and a == action)

    def _start(self):
        """Load config.ini like the real software does on start."""
        cfg = _read_ini(self.config_path)
        if cfg.get("Controller", "Key", fallback=None) != MACHINE_KEY:
            self.running = False
            self.note("process", "start_refused", "access security key invalid")
            return False
        self.live = {
            "AntiBlur": cfg.get("Setup", "AntiBlur", fallback="10"),
            "FocusDensity": cfg.get("Setup", "FocusDensity", fallback="4"),
            "StitchMode": cfg.get("Setup", "StitchMode", fallback="0"),
            "SlideType": cfg.get("Slide", "Type", fallback="Generic"),
        }
        self.scan_region_mm = [float(cfg.get("Slide", k, fallback="5")) for k in
                               ("ScanLeft", "ScanTop", "ScanWidth", "ScanHeight")]
        self.points = {i: [] for i in range(4)}
        self.preview_taken = False
        self.running = True
        return True

    def _save_live_to_config(self):
        """What a NORMAL close does on the real scanner: write the live values."""
        cfg = _read_ini(self.config_path)
        cfg.set("Setup", "AntiBlur", self.live["AntiBlur"])
        cfg.set("Setup", "FocusDensity", self.live["FocusDensity"])
        cfg.set("Setup", "StitchMode", self.live["StitchMode"])
        cfg.set("Slide", "Type", self.live["SlideType"])
        for k, v in zip(("ScanLeft", "ScanTop", "ScanWidth", "ScanHeight"), self.scan_region_mm):
            cfg.set("Slide", k, f"{v:.2f}")
        with open(self.config_path, "w", encoding="utf-8") as f:
            cfg.write(f, space_around_delimiters=False)

    def mm_per_px(self):
        w, h = slide_art.size_for(self.mode)
        return SLIDE_MM[0] / w, SLIDE_MM[1] / h

    def box_px(self):
        sx, sy = self.mm_per_px()
        l, t, w, h = self.scan_region_mm
        return [round(l / sx), round(t / sy), round(w / sx), round(h / sy)]

    def require_running(self):
        if not self.running:
            raise ConnectionResetError("virtual scanner is not running")

    # ------------------------------------------------------------ machine actions

    def take_preview(self):
        """NewScan: one PreviewImage per loaded slide; clears every focus point."""
        self.require_running()
        self.points = {i: [] for i in range(4)}
        self.preview_taken = True
        replies = []
        for n, kind in enumerate(self.loaded):
            if kind is None:
                continue
            path = self.captured / f"Preview#{n + 1}.tif"
            slide_art.draw(str(path), self.mode, kind)
            x, y, w, h = self.box_px()
            replies.append({"method": "PreviewImage", "slideNo": n, "result": str(path),
                            "scanAreas": [{"x": x, "y": y, "w": w, "h": h}]})
        return replies

    def lose_preview_files(self):
        """F11: the preview pictures disappear from the scanner folder."""
        for p in self.captured.glob("Preview#*.tif"):
            p.unlink()

    def set_everywhere(self, section, key, value, live_key=None):
        """Set one value in both good files, the config file and (optionally) live."""
        for path in (self.good_bf, self.good_fluo, self.config_path):
            cfg = _read_ini(path)
            cfg.set(section, key, value)
            with open(path, "w", encoding="utf-8") as f:
                cfg.write(f, space_around_delimiters=False)
        if live_key:
            self.live[live_key] = value

    def scan(self, slide_no, sample_id, box=None):
        """StartScan. Returns the messages the scanner sends (possibly none)."""
        self.require_running()
        if box is not None:                      # a box in the command REPLACES it and wipes points
            self.points = {i: [] for i in range(4)}
        if self.calibration:                     # frozen behind the "turn off calibration?" dialog
            self.note("machine", "scan_frozen_by_dialog", sample_id)
            return []
        if slide_no >= len(self.loaded) or self.loaded[slide_no] is None:
            return [{"method": "ErrorInfo", "result": 1, "text": "no slide"}]
        msgs = []
        if "no_scan_started" not in self.faults:
            msgs.append({"method": "ScanStarted", "sampleId": sample_id})
        msgs += [{"method": "ScannedImage", "index": i} for i in range(3)]
        code = 1 if "simulator_result_code" in self.faults else 0
        msgs.append({"method": "ScanStopped", "result": code})
        due = time.time() + (self.result_delay_s if "early_scan_stopped" in self.faults else 0)
        self.pending_results.append((due, sample_id, slide_no, list(self.points[slide_no])))
        self.flush_results()
        return msgs

    def flush_results(self):
        """Write every result file whose time has come (Scan.txt)."""
        now, keep = time.time(), []
        for due, sample_id, slide_no, points in self.pending_results:
            if due > now:
                keep.append((due, sample_id, slide_no, points))
                continue
            folder = self.results / datetime.now().strftime("%Y-%m-%d") / sample_id
            folder.mkdir(parents=True, exist_ok=True)
            auto_grid = self.live.get("FocusDensity", "0") != "0"
            tiles = 132
            _write_ini(folder / "Scan.txt", {
                "General": {"SlideID": sample_id, "SlideType": self.live.get("SlideType"),
                            "Magnification": "20X", "RowCount": "11", "ColumnCount": "12",
                            "Quantity": str(tiles), "ScanStopped": "0", "StitchMode": "2"},
                "Focus": _focus_section(points, auto_grid, tiles),
                "Camera": {"ExpoTime": "1212", "ExpoGain": "1"},
            })
        self.pending_results = keep


class VirtualSocketClient:
    """Door 1: same methods and return shapes as the co-pilot's socket client."""

    def __init__(self, twin):
        self.twin = twin
        self.sock = None
        self.last_preview_slides = []
        self._inbox = []
        self.received = []

    def connect(self, timeout=5):
        self.twin.note("socket", "connect")
        if not self.twin.running:
            raise ConnectionRefusedError("virtual scanner is not running")
        self.sock = "virtual"

    def close(self):
        self.sock = None

    def reset(self):
        self.twin.note("socket", "reset")
        self.sock = None
        self._inbox = []

    def _receive(self, msgs):
        t = time.time()
        for m in msgs:
            self._inbox.append(m)
            self.received.append((t, m.get("method")))

    def methods_since(self, t0):
        return [m for t, m in self.received if t >= t0]

    def new_scan(self, expo_wait=1000, timeout=60, slide_no=0, settle_s=5.0):
        self.twin.note("socket", "NewScan", slide_no)
        if self.sock is None:
            raise ConnectionResetError("not connected")
        replies = self.twin.take_preview()
        self._receive(replies)
        self.last_preview_slides = [r["slideNo"] for r in replies]
        self._inbox = [m for m in self._inbox if m.get("method") != "PreviewImage"]
        return next((r for r in replies if r["slideNo"] == slide_no), None)

    def start_scan(self, slide_no=0, sample_id="SAMPLE-001", x=None, y=None, w=None, h=None,
                   timeout=60):
        self.twin.note("socket", "StartScan", {"slide_no": slide_no, "sample_id": sample_id,
                                               "box": None if x is None else [x, y, w, h]})
        if self.sock is None:
            raise ConnectionResetError("not connected")
        self._inbox = [m for m in self._inbox if m.get("method") not in ("ScanStarted", "ScanStopped")]
        box = None if None in (x, y, w, h) else [x, y, w, h]
        self._receive(self.twin.scan(slide_no, sample_id, box))
        started = next((m for m in self._inbox if m.get("method") == "ScanStarted"), None)
        if started:
            self._inbox.remove(started)
        return started

    def wait_for_scan_finished(self, timeout=600):
        stopped = next((m for m in self._inbox if m.get("method") == "ScanStopped"), None)
        if stopped:
            self._inbox.remove(stopped)
        self.twin.flush_results()
        return stopped


class VirtualMCPClient:
    """Door 2: the MCP adaptor (start / list_tools / call_tool / close)."""

    TOOLS = ["MCP_GetDeviceInfo", "MCP_GetStageInfo", "MCP_GetStatus", "MCP_ScanStitchMode",
             "MCP_ScanFocusDensity", "MCP_PresetFocus", "MCP_Stop", "MCP_WaitForEvent"]

    def __init__(self, twin):
        self.twin = twin

    def start(self):
        self.twin.note("mcp", "start")
        self.twin.require_running()

    def close(self):
        self.twin.note("mcp", "close")

    def list_tools(self):
        return [{"name": n, "description": f"virtual {n}",
                 "inputSchema": {"type": "object", "properties": {}}} for n in self.TOOLS]

    def call_tool(self, name, arguments=None, timeout=None):
        args = arguments or {}
        self.twin.note("mcp", name, args)
        t = self.twin
        t.require_running()
        data = {"accepted": True}                   # unknown commands: a blind acknowledgement
        if name == "MCP_Connect":
            data = {"connected": True}
        elif name == "MCP_GetDeviceInfo":
            data = {"camera": True, "controller": True, "taskrunning": False}
        elif name == "MCP_GetStageInfo":
            data = {"X": 0, "Y": 0, "Z": 0}
        elif name == "MCP_GetStatus":
            data = {"connected": True, "runtimeState": "Idle"}
        elif name == "MCP_ScanStitchMode":
            t.live["StitchMode"] = str(int(args.get("index", 0)))
        elif name == "MCP_ScanFocusDensity":
            t.live["FocusDensity"] = FOCUS_DENSITIES[int(args.get("index", 0))]
        elif name == "MCP_PresetFocus":
            if args.get("clear"):
                t.preset_points = []
            else:
                t.preset_points.append((args.get("x"), args.get("y"), args.get("z")))
        elif name == "MCP_StartScan":
            t.mcp_events += t.scan(0, "MCP-SCAN")
        elif name == "MCP_WaitForEvent":
            data = t.mcp_events.pop(0) if t.mcp_events else {}
            return {"ok": True, "text": json.dumps(data) if data else "", "raw": data}
        return {"ok": True, "text": json.dumps(data), "raw": data}


class VirtualGUI:
    """Door 3: the 12 GUI-automation functions the co-pilot imports."""

    NAMES = ["ensure_calibration_on", "get_anti_blur", "set_anti_blur", "get_slide_type",
             "set_slide_type", "get_stitch_mode", "set_stitch_mode", "get_focus_density",
             "set_focus_density", "set_scan_region_fields", "read_scan_boxes_on_screen",
             "place_focus_points_by_click"]

    def __init__(self, twin):
        self.twin = twin

    def _window(self, action):
        self.twin.note("gui", action)
        if not self.twin.running:
            return {"ok": False, "error": "Could not find the HDScanner window. Is the GUI open?"}
        return None

    def ensure_calibration_on(self):
        if (e := self._window("ensure_calibration_on")):
            return e
        was = "ON" if self.twin.calibration else "OFF"
        self.twin.calibration = True
        return {"ok": True, "was": was, "now": "ON", "changed": was == "OFF"}

    def _get(self, action, key, options, as_label=None):
        if (e := self._window(action)):
            return e
        current = self.twin.live[key]
        if as_label:
            current = options[int(current)]
        return {"ok": True, "current": current, "options": list(options),
                "index": options.index(current) if current in options else None,
                "source": "virtual scanner", "label_found": True, "found": True}

    def _set(self, action, key, options, value, as_label=None):
        if (e := self._window(action)):
            return e
        want = str(value).strip()
        match = next((o for o in options if o.lower() == want.lower()), None)
        old = self.twin.live[key]
        old = options[int(old)] if as_label else old
        if match is None:
            return {"ok": False, "old": old, "requested": want, "options": list(options),
                    "error": f"{want!r} is not an available value."}
        self.twin.live[key] = str(options.index(match)) if as_label else match
        return {"ok": True, "old": old, "now": match, "requested": match,
                "changed": old.lower() != match.lower(), "saved": False,
                "note": "Changed live in the software only; config.ini not saved."}

    def get_anti_blur(self):
        return self._get("get_anti_blur", "AntiBlur", ANTI_BLUR_OPTIONS)

    def set_anti_blur(self, value):
        return self._set("set_anti_blur", "AntiBlur", ANTI_BLUR_OPTIONS, value)

    def get_slide_type(self):
        return self._get("get_slide_type", "SlideType", SLIDE_TYPES)

    def set_slide_type(self, value):
        return self._set("set_slide_type", "SlideType", SLIDE_TYPES, value)

    def get_stitch_mode(self):
        return self._get("get_stitch_mode", "StitchMode", STITCH_MODES, as_label=True)

    def set_stitch_mode(self, value):
        return self._set("set_stitch_mode", "StitchMode", STITCH_MODES, value, as_label=True)

    def get_focus_density(self):
        return self._get("get_focus_density", "FocusDensity", FOCUS_DENSITIES)

    def set_focus_density(self, value):
        return self._set("set_focus_density", "FocusDensity", FOCUS_DENSITIES, value)

    def set_scan_region_fields(self, left, top, width, height):
        if (e := self._window("set_scan_region_fields")):
            return e
        self.twin.scan_region_mm = [round(float(v), 2) for v in (left, top, width, height)]
        return {"ok": True, "typed": list(self.twin.scan_region_mm)}

    def read_scan_boxes_on_screen(self, preview_size=(1500, 500)):
        if (e := self._window("read_scan_boxes_on_screen")):
            return e
        if not self.twin.preview_taken:
            return {"ok": False, "error": "No previews on the Scan tab."}
        box = self.twin.box_px()
        slides = [{"slide": n + 1, "box_px": list(box), "focus_marks": len(self.twin.points[n]),
                   "focus_marks_px": [list(p) for p in self.twin.points[n]]}
                  for n, kind in enumerate(self.twin.loaded) if kind is not None]
        return {"ok": True, "slides": slides, "preview_size": list(preview_size)}

    def place_focus_points_by_click(self, points_px, preview_size=(1500, 500), slide=0):
        """Right-clicks: outside the box -> ignored; on an existing point -> deletes it."""
        if (e := self._window("place_focus_points_by_click")):
            return e
        existing = self.twin.points[slide]
        before = len(existing)
        bx, by, bw, bh = self.twin.box_px()
        placed, n_ok = [], 0
        for x, y in points_px:
            if "focus_clicks_ignored" in self.twin.faults:
                placed.append({"px": [x, y], "verified": False})
                continue
            if not (bx <= x <= bx + bw and by <= y <= by + bh):
                placed.append({"px": [x, y], "verified": False})      # ignored by the machine
                continue
            hit = next((p for p in existing if abs(p[0] - x) <= 4 and abs(p[1] - y) <= 4), None)
            if hit:
                existing.remove(hit)                                   # a right-click ON a point deletes it
                self.twin.note("machine", "focus_point_deleted", hit)
                placed.append({"px": [x, y], "verified": False})
                continue
            existing.append((x, y))
            placed.append({"px": [x, y], "verified": True})
            n_ok += 1
        return {"ok": n_ok == len(points_px), "placed": placed, "verified_count": n_ok,
                "requested": len(points_px), "slide": slide, "points_before": before,
                "points_after": len(existing)}


class VirtualProcess:
    """Door 4: closing and starting the scanner software."""

    def __init__(self, twin):
        self.twin = twin

    def close_hdscanner_normally(self, timeout_s=30):
        self.twin.note("process", "close_normally")
        if not self.twin.running:
            return None
        self.twin._save_live_to_config()
        self.twin.running = False
        return True

    def stop_hdscanner(self, timeout_s=15):
        self.twin.note("process", "force_close")
        self.twin.running = False
        return True

    def start_hdscanner(self, exe=None, timeout_s=90, settle_s=25):
        self.twin.note("process", "start")
        return self.twin._start()

    def hdscanner_running(self):
        return self.twin.running

    def socket_up(self, *args, **kwargs):
        return self.twin.running
