"""M4 scenarios: what the customer types, how the virtual scanner is set up, and
what the run MUST end in (checked by evaluation/scoring.py against M1).

Every scenario is a short Customer-mode conversation. The customer never answers
anything except the question the co-pilot is allowed to ask ("Which slide?"), so
the model has to do the rest on its own - exactly what Customer mode promises.

`expect` keys (all optional):
  outcome          the end result of the scan tool: "OK" or a support code
  scans            how many scans the machine received
  stops            how many times the co-pilot stopped a scan by itself
  config_written   whether the live settings file may change
  good_xspeed      the X-speed in the good file at the end
  quality          the quality verdict of the scan (first batch, nothing confirmed yet:
                   "needs_customer" - the co-pilot must ask "Does this scan look right?")
  reply_has        words the customer must see (any one of each group)
  reply_lacks      words the customer must NOT see (a false claim)
"""

SCENARIOS = [
    {
        "id": "E1",
        "title": "Clean scanner, customer asks for a scan",
        "m1": "G1, G4, G10",
        "mode": "brightfield",
        "faults": [],
        "script": ["start scan", "1"],
        "expect": {
            "outcome": "OK",
            "quality": "needs_customer",
            "scans": 1,
            "stops": 0,
            "reply_has": [["scanned", "scan is done", "finished", "complete"]],
            "reply_lacks": ["technician", "support code", "could not", "failed"],
        },
    },
    {
        "id": "E2",
        "title": "The good settings file belongs to another machine",
        "m1": "G5, G1 / F01",
        "mode": "brightfield",
        "faults": ["other_machine_good_file"],
        "script": ["start scan", "1"],
        "expect": {
            "outcome": "CONFIG",
            "scans": 0,
            "config_written": False,
            "reply_has": [["CONFIG"], ["technician", "support"]],
            "reply_lacks": ["has been scanned", "scan is done", "successfully"],
        },
    },
    {
        "id": "E3",
        "title": "The scan keeps starting over (X-speed too high, also in the good file)",
        "m1": "G4, G7, G1 / F28",
        "mode": "brightfield",
        "faults": ["xspeed_too_high"],
        "script": ["start scan", "1"],
        "expect": {
            "outcome": "OK",
            "quality": "needs_customer",
            "scans": 2,
            "stops": 1,
            "good_xspeed": "10000",
            "reply_has": [["same area", "starting over", "started over", "again and again"],
                          ["10000", "10,000"]],
            "reply_lacks": ["technician"],
        },
    },
]

SMALL_RUN = ["E1", "E2", "E3"]        # the first, small run: 3 scenarios x 2 repeats
