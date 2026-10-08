"""M4 reachability check: can every scenario's machine end state be reached at all?

Before spending tokens on a real run: a stand-in model that behaves correctly - asks
which slide, scans the slide the customer named, confirms the first scan on yes / no
with the real sample id - drives the real co-pilot through every scenario on the
virtual scanner. The machine side (outcome, scans, stops, settings, quality,
reference) must come out as the scenario expects. The customer-facing words are not
judged here: they are the real model's job. No model, no cost.

    <private>/venv/Scripts/python tools/m4_reach_check.py
"""
import json
import re
import sys

from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from openai.types.chat import ChatCompletion  # noqa: E402

from evaluation.driver import run_conversation  # noqa: E402
from evaluation.scenarios import SCENARIOS  # noqa: E402
from evaluation.scoring import score_run  # noqa: E402

PRIVATE = sys.argv[1] if len(sys.argv) > 1 else str(REPO.parent)


def completion(content=None, tool=None, args=None):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": tool, "arguments": json.dumps(args)}}]
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "stand-in",
        "choices": [{"index": 0, "finish_reason": "stop", "message": msg}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})


def reactive_model(*args, **kwargs):
    msgs = kwargs["messages"]
    last = msgs[-1]
    if last["role"] == "tool":
        return completion("(stand-in reply)")
    users = [m for m in msgs if m["role"] == "user"]
    if not users:
        return completion("Hello.")
    text = users[-1]["content"] if isinstance(users[-1]["content"], str) else ""
    low = text.lower()
    if low.startswith(("yes", "no")):
        sample = None
        for m in reversed(msgs):
            if m["role"] == "tool":
                try:
                    sample = json.loads(m["content"]).get("sample_id")
                except Exception:
                    pass
                if sample:
                    break
        return completion(tool="confirm_scan_quality",
                          args={"sample_id": sample, "looks_right": low.startswith("yes")})
    nums = re.findall(r"\d", text) or (["2"] if "二" in text else [])
    if nums:
        return completion(tool="auto_scan", args={"slide": int(nums[-1])})
    return completion("Which slide should I scan — 1, 2, 3 or 4?")


ok = 0
for sc in SCENARIOS:
    run = run_conversation(PRIVATE, sc["script"], sc["mode"], faults=sc["faults"],
                           loaded=sc.get("loaded", ("clear", None, None, None)),
                           setup=sc.get("setup", ()), fake_model=reactive_model)
    s = score_run(sc, run)
    machine = [f for f in s["failed_checks"] if not f.startswith("reply")]
    good = not machine and not s["rule_breaks"]
    ok += good
    m = s["measured"]
    extra = ", ".join(f"{k}={m[k]}" for k in ("stops", "quality", "level", "reference_saved")
                      if k in sc["expect"])
    print(f"{'REACHABLE' if good else 'PROBLEM  '}  {sc['id']:4} {sc['title'][:58]:58} "
          f"{m['outcome']:15} scans={m['scans']}{', ' + extra if extra else ''}"
          f"{'  | ' + '; '.join(machine + s['rule_breaks']) if not good else ''}")
print()
print(f"{ok} of {len(SCENARIOS)} scenarios reachable")
