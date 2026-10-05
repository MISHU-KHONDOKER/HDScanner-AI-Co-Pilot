# M3 — Virtual instrument

**Milestone:** M3 of the [roadmap](../ROADMAP.md) · **Builds on:** [M1](M1_definition_of_correct.md), [M2](M2_test_foundation.md)

A virtual slide scanner that the **real, unchanged co-pilot** can drive end to end,
with real failures switched on at will. It makes the agent testable in the
situations that are too risky or too rare to create on a production machine:
another machine's configuration, a scan frozen behind a dialog, a status message
that lies, a scanner that is not running.

**First result:** the real co-pilot passed **11 of 13** scenarios and **reproduced
2 known open failure modes**, one of them a false success claim
([results](m3_first_runs.md)).

---

## 1. Design: replace the doors, keep the agent

The co-pilot touches the scanner through exactly five "doors". The virtual
scanner replaces these and nothing else:

```
Real co-pilot — UNCHANGED: 19 tools, checks and read-backs, the customer pipeline
        │
        │  five doors, swapped from outside by virtual_scanner/harness.py
        ▼
1 socket client      preview, scan, scan events            -> VirtualSocketClient
2 MCP client         scan parameters, events, preset focus  -> VirtualMCPClient
3 GUI automation     12 functions (settings, box, clicks)   -> VirtualGUI
4 program control    close normally / force-close / start   -> VirtualProcess
5 files              config.ini, previews, scan results     -> a temporary scanner folder
```

So the co-pilot's own decision logic — its checks, read-backs, retry and
recovery rules, the support codes — runs for real. Only the machine is simulated.

**The co-pilot's code is not modified.** The harness imports it and swaps the
five doors before anything runs. That keeps the test honest (it tests exactly
what is deployed) and carries zero risk to the production agent.

## 2. Safety: a test can never reach a real machine

- The harness **refuses to start** if any object from the real machine modules
  (`scanner_gui`, `scanner_client`, `scanner_mcp_client`) is still reachable from
  the co-pilot, or if any program-control function is not the virtual one.
- While it runs, **starting or stopping any program is blocked**, and so is any
  connection to the real scanner's control port.
- Both are proven: scenario S0 puts one real door back and checks the refusal and
  the port block; two unit tests do the same in CI.

## 3. Fidelity: every behaviour comes from a real observation

A simulator that only does what the code expects proves nothing. Each behaviour
below was observed on the real scanner (or its vendor simulator) and recorded in
the build log at the time.

| Twin behaviour | Observed on | Date |
|---|---|---|
| One preview reply per loaded slide; an empty position does not answer | real scanner, 4-slide loader | 2026-09-26 |
| A preview clears every focus point | vendor simulator | 2026-09-24 |
| The scan box is shared by all slides and redrawn from the saved scan region | real scanner | 2026-09-24 / 26 |
| A scan without a box scans the current box **with** its focus points; a box in the command replaces it and wipes the points | real scanner | 2026-09-29 |
| A right-click outside the scan box is ignored | real scanner | 2026-09-30 |
| A right-click on an existing focus point deletes it | real scanner | 2026-09-29 |
| A perfect scan reports `0`; the simulator reports `1` | real scanner / simulator | 2026-09-30 |
| The scan can run without ever sending "ScanStarted" | real scanner | 2026-09-29 |
| "ScanStopped" can arrive while the result is not yet written | real scanner | 2026-09-26 |
| Calibration mode on → a blocking dialog freezes every scan; the socket cannot see it | vendor simulator | 2026-09-18 |
| A normal close writes the live settings into config.ini | real scanner | 2026-09-26 |
| A foreign licence key in config.ini → the software refuses to start | real scanner | 2026-09-30 |
| Settings accept only the values the software offers | real scanner | 2026-09-22 / 23 |
| Config key names (`[Setup] AntiBlur / FocusDensity / StitchMode`, `[Slide] Type`) | real config files | 2026-09-28 |

**Simplified on purpose:** previews are synthetic drawings (from M2); the scan is
instant and always 132 tiles; option lists for anti-blur and focus density are
representative, not copied.

## 4. Faults that can be switched on

| Switch | M1 failure mode |
|---|---|
| `other_machine_good_file` | F01 — another machine's config and licence key |
| `wrong_mode_good_file` | F02 — the other imaging mode's file |
| `simulator_result_code` | F03 — status code 1 instead of 0 |
| `early_scan_stopped` | F05 — "stopped" before the result exists |
| `no_scan_started` | F06 — no start confirmation |
| `calibration_modal` | F13 — scan frozen behind a dialog |
| `focus_clicks_ignored` | focus points cannot be placed (real build, 2026-09-26) |
| `scrambled_settings` | settings changed in the window and saved (the in-house scramble test) |
| `scanner_not_running` | recovery: the software has to be started |
| actions: `lose_preview_files()`, `set_everywhere()`, faint / empty slides | F11, F25, F20, empty loader position |

Also reproducible through the twin's normal behaviour: F07, F08, F09, F10, F12.

**Not covered by M3, and why:**
- **F17** (slow switch to fluorescence): the handling lives *inside* the GUI door,
  which the twin replaces — it stays covered by real-hardware testing.
- **F14, F15, F26** (leaked tool calls, conversation corruption, session audience):
  agent-side, not machine behaviour — unit-tested or part of M6.
- **F21, F24, F27**: GUI targeting and scale details inside the replaced doors or
  already covered by M2 unit tests.

## 5. First end-to-end runs (no LLM)

[`tools/m3_first_runs.py`](../tools/m3_first_runs.py) runs 13 scenarios: the real
co-pilot's own functions on a fresh virtual scanner each time. No language model
is involved yet (that is M4), so the runs are free, fast and repeatable.
Full table: **[m3_first_runs.md](m3_first_runs.md)**.

| | Result |
|---|---|
| ✅ Pass (13) | clean scan; another machine's config refused before any write; wrong-mode config refused; **scrambled settings repaired** (4 settings, backup made, live values = good file); success judged from the result file, not the status code; no restart and no second scan after an ambiguous stop; frozen scan reported as still scanning, never retried; faint sample → "not found"; empty position → "no slide"; scanner not running → started once, then scanned; harness safety; **no blind scan when focus fails and the automatic grid is off (S11, fixed 2026-10-05)**; **focus tool refuses when the preview is missing, takes no preview itself (S12, fixed 2026-10-05)** |
| 🟡 Open (0) | — (first run: S11 / F25 and S12 / F11 — both fixed, see below) |
| ❌ Fail (0) | — |

The two open results of the first run were not surprises — both were in the M1
catalogue as open risks. The twin turned them from suspicions into **reproducible
evidence**, which is the point: they can now be fixed and the fix proven by the
same scenario.

### S11 fixed (2026-10-05) — and what the real result files taught first

**First run:** OPEN — the customer was told "success" although the twin's result
file said all 132 tiles failed focus.

**The obvious fix was wrong.** The plan was "read `[Focus] Failed` from the result
file and refuse when it is above 0". Before building it, three real result files
from a production scanner were checked:
- every one had three measured focus points and a fitted focus plane (`Z=…`);
- one of them, with **sharp** images, said `Failed=1`; the others `Failed=0`.

So `Failed > 0` would have reported a **good** scan as failed — swapping one false
message for the opposite one. The twin's `Failed = <all tiles>` for an unfocused
scan is an **assumption**, not an observation: no real unfocused result file has
been seen yet.

**The fix that does not depend on that guess:** stop the blind scan *before* it
starts. When the focus points cannot be placed, the co-pilot used to fall back to
"the scanner's own focus" — which does not exist when `FocusDensity = 0`. Now it
checks that setting first and, when it is 0, stops with `FOCUS-POINTS` and starts
no scan. S11 was tightened to require exactly that (`FOCUS-POINTS, scans=0`).

**Proof:** S11 OPEN → PASS; S0–S10 unchanged; **mutation check** — with the new
guard commented out, S11 goes straight back to OPEN with the old false success.
Step by step with the real terminal output: **[S11 fix demo](demo_s11_fix.md)**.

**Still to do:** one controlled real scan without focus, to see what the scanner
really writes — then correct the twin's result file, and decide whether a check
*after* the scan is needed as well.

### S12 fixed (2026-10-05) — a "look only" tool that changed the machine

**First run:** OPEN — with the preview file missing, `find_focus_points` took a
new preview on its own, which resets the scan box and the focus points. This
happened on a real scanner PC whose machine paths were wrong (F11): the fallback
wiped the user's box *and* hid the configuration error.

**Fix:** the tool refuses (`ok: false, preview_missing: true`) with a message
naming the file it looked for, and takes no preview. S12 now also requires that
answer, not only "no new preview".

**Proof:** S12 OPEN → PASS; **all 13 scenarios pass**; mutation check — with the
old fallback put back in a temporary copy, S12 goes back to OPEN. Step by step
with the real terminal output: **[S12 fix demo](demo_s12_fix.md)**.

**Checked by hand:** [M3 walkthrough](M3_walkthrough.md) — seven steps with the
real terminal output of each run, including breaking the harness on purpose.

## 6. How to run

```bash
# CI-safe: the twin and the harness safety, no private code needed
python -m pytest tests/test_virtual_scanner.py

# The real co-pilot on the twin (needs the private project and its Python)
<private-project>/venv/Scripts/python tools/m3_first_runs.py <private-project>
```

## 7. Limits — what the twin cannot tell us

- It tests the agent's **decisions**, not the GUI automation or socket timing
  inside the doors; those stay covered by runs on the real scanners.
- A pass on the twin is **not** a pass on the machine. M4 keeps a small set of
  confirmation runs on real hardware.
- The twin is only as good as its fidelity table. A new real-world observation
  must be added there — and to the twin — before it is trusted in a scenario.
