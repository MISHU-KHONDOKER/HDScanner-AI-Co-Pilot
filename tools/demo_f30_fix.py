"""F30 fix demo: a customer never sees a support code the co-pilot does not have.

F30 (found by the M4 evaluation): the real model told a customer to contact support
with the code "SCAN-RESULT-MISSING" - a code no tool ever returned. The fix is a check
in the co-pilot's code: in Customer mode the final answer may only name support codes
that a tool really returned in this conversation. Otherwise the model gets one retry
with a correction; still wrong -> a reply built from facts (the tool's own message,
or where the finished scan is), never the invented code.

A stand-in model says what the real model said. Four runs:

  1. check ON,  the retry corrects itself       -> the invented code never reaches the customer
  2. check ON,  the retry invents again         -> a reply built from facts instead
  3. check OFF  (in memory, no file is changed) -> the invented code reaches the customer (old F30)
  4. check ON,  a REAL code (CONFIG)            -> shown unchanged, no extra model call

Run with the PRIVATE project's Python:

    <private>/venv/Scripts/python tools/demo_f30_fix.py
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

SC = {s["id"]: s for s in SCENARIOS}
INVENTED = ("Your slide was scanned, but something looks wrong. Please contact support "
            "and give them this code: SCAN-RESULT-MISSING.")


def completion(content=None, tool=None, args=None):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": tool, "arguments": json.dumps(args)}}]
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "stand-in",
        "choices": [{"index": 0, "finish_reason": "stop", "message": msg}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})


def stand_in(final, retry=None):
    answers = [completion("Hello."), completion("Which slide should I scan — 1, 2, 3 or 4?"),
               completion(tool="auto_scan", args={"slide": 1}), completion(final)]
    if retry is not None:
        answers.append(completion(retry))
    it = iter(answers)
    return lambda *a, **k: next(it)


def run(step, label, sid, model, check=True):
    load = driver.load_copilot

    def load_with_or_without_check(private_root, twin):
        main = load(private_root, twin)
        if not check:
            main._invented_codes = lambda *a, **k: []            # the check switched off
        return main

    driver.load_copilot = load_with_or_without_check
    try:
        r = driver.run_conversation(PRIVATE, SC[sid]["script"], SC[sid]["mode"],
                                    faults=SC[sid]["faults"], fake_model=model)
    finally:
        driver.load_copilot = load
    seen = r["transcript"][-1]["text"]
    s = score_run(SC[sid], r)
    g1 = [b for b in s["rule_breaks"] if b.startswith("G1")]
    print(f"{step}. check {'ON ' if check else 'OFF'}  {label}")
    print(f"     customer sees: {seen}")
    print(f"     model calls: {len(r['model_calls'])}  ->  {'G1 BROKEN: ' + g1[0] if g1 else 'no invented code'}")
    return "SCAN-RESULT-MISSING" in seen, seen


if __name__ == "__main__":
    a, _ = run(1, "(model invents a code, the retry corrects itself)", "E1",
               stand_in(INVENTED, retry="Your slide has been scanned. Does this scan look right to you?"))
    b, _ = run(2, "(model invents a code, the retry invents again)", "E1",
               stand_in(INVENTED, retry=INVENTED))
    c, _ = run(3, "(model invents a code)", "E1", stand_in(INVENTED), check=False)
    real = "I'm sorry — this needs a technician. Please contact support and give them this code: CONFIG."
    d_bad, d_seen = run(4, "(a code the tool really returned)", "E2", stand_in(real))
    ok = not a and not b and c and not d_bad and d_seen == real
    print(f"\nF30 fix {'PROVEN' if ok else 'NOT proven'}: the invented code reaches the customer only "
          f"with the check switched off; a real code passes unchanged")
    sys.exit(0 if ok else 1)
