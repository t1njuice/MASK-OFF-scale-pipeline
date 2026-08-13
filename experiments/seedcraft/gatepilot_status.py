"""One-line-per-arm progress for the running gate-pilot arms (no API calls).

Usage: python experiments/seedcraft/gatepilot_status.py [p6 p7 ...]
"""

import glob
import json
import sys
from collections import Counter

for arm in sys.argv[1:] or ["p6", "p7"]:
    logs = sorted(glob.glob(f"output/gatepilot_{arm}_*_run_log.jsonl"))
    if not logs:
        print(f"{arm}: no run log yet")
        continue
    stem = logs[-1].removesuffix("_run_log.jsonl")
    recs = [json.loads(l) for l in open(logs[-1])]
    rounds = [r for r in recs if "votes" in r]
    lints = [r for r in recs if r.get("stage") == "lint"]
    try:
        acc = [json.loads(l) for l in open(f"{stem}_accepted.jsonl")]
    except FileNotFoundError:
        acc = []
    seeds = {r["seed_name"] for r in recs}
    it = Counter(r["iteration"] for r in rounds)
    done = {a["seed_name"] for a in acc}
    # a seed is still working if its last round neither accepted nor killed it
    last = {}
    for r in rounds:
        if r["iteration"] >= last.get(r["seed_name"], (0,))[0]:
            last[r["seed_name"]] = (r["iteration"], r)
    active = sum(1 for s, (_, r) in last.items()
                 if s not in done and not r["seed_defect"])
    print(f"{arm}: {len(acc)}/{len(seeds)} accepted | {len(rounds)} rounds "
          f"| iters {dict(sorted(it.items()))} | ~{active} seeds active "
          f"| lint fired {len(lints)}x "
          f"| accepts at iter {sorted(a['iterations'] for a in acc)}")
