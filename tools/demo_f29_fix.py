"""F29 fix demo: the co-pilot no longer scans a slide the customer did not name.

F29 (found by the M4 evaluation): the customer typed only "start scan" and the real
model called the scan tool with slide 1 by itself. The fix is a guard in the
co-pilot's code: a scan tool runs only with a slide number the customer said in the
message that started the turn; otherwise nothing is scanned and the model is told to
ask "Which slide?".

A fix only counts if its test can fail. A stand-in model does exactly what the real
model did - scan slide 1 right after "start scan" - and the same conversation runs:

  1. with the guard                         -> no scan in turn 1, the model is told to ask
  2. with the guard switched off (in memory, -> the made-up scan happens (the old F29)
     no file is changed)
  3. with the guard again                   -> no scan in turn 1 again

Run with the PRIVATE project's Python:

    <private>/venv/Scripts/python tools/demo_f29_fix.py
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
PRIVATE = sys.argv[1] if len(sys.argv) > 1 else str(REPO.parent)

from openai.types.chat import ChatCompletion  # noqa: E402

import evaluation.driver as driver  # noqa: E402
from evaluation.scenarios import SCENARIOS  # noqa: E402
from evaluation.scoring import score_run  # noqa: E402

E1 = next(s for s in SCENARIOS if s["id"] == "E1")


def completion(content=None, tool=None, args=None):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": tool, "arguments": json.dumps(args)}}]
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "stand-in",
        "choices": [{"index": 0, "finish_reason": "stop", "message": msg}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})


def model_that_guesses_the_slide():
    """What the real model did in M4 run E3 #2: scan slide 1 on 'start scan'."""
    answers = iter([
        completion("Hello."),
        completion(tool="auto_scan", args={"slide": 1}),           # turn 1: "start scan"
        completion("Which slide should I scan — 1, 2, 3 or 4?"),   # what it says after the tool result
        completion(tool="auto_scan", args={"slide": 1}),           # turn 2: "1"
        completion("Your slide has been scanned. Does this scan look right to you?"),
    ])
    return lambda *a, **k: next(answers)


def run(step, guard):
    load = driver.load_copilot

    def load_with_or_without_guard(private_root, twin):
        main = load(private_root, twin)
        if not guard:
            main._slide_not_said = lambda *a, **k: None        # the guard switched off
        return main

    driver.load_copilot = load_with_or_without_guard
    try:
        r = driver.run_conversation(PRIVATE, E1["script"], E1["mode"], fake_model=model_that_guesses_the_slide())
    finally:
        driver.load_copilot = load
    twin = r["twin"]
    scans_turn1 = sum(1 for c in r["tool_calls"] if c["tool"] == "auto_scan" and c["turn"] == 1)
    told = next((t["text"] for t in r["transcript"][2:3]), "")
    s = score_run(E1, r)
    print(f"{step}. guard {'ON ' if guard else 'OFF'}  customer: 'start scan'  ->  scans in turn 1: {scans_turn1}")
    print(f"     co-pilot said: {told}")
    print(f"     whole conversation: {twin.count('socket', 'StartScan')} scan(s)  ->  "
          f"{'SUCCESS' if s['success'] else 'FAIL'}"
          + (f"  ({'; '.join(s['rule_breaks'] + s['failed_checks'])})" if not s["success"] else ""))
    return scans_turn1


if __name__ == "__main__":
    on = run(1, guard=True)
    off = run(2, guard=False)
    again = run(3, guard=True)
    caught = on == 0 and off == 1 and again == 0
    print(f"\nF29 fix {'PROVEN' if caught else 'NOT proven'}: the made-up scan happens only "
          f"with the guard switched off")
    sys.exit(0 if caught else 1)
