import json
import re
import sys
from collections import Counter
from pathlib import Path

F = Path(__file__).parent.parent.parent / (
    "output/frozen_20_gen-opus-4-8_gate-opus-4-8_seeds-e2e20_"
    "2026-08-05_123007Z_run_log.jsonl"
)
recs = [json.loads(l) for l in open(F)]
last = {}
for r in recs:
    if "accepted" in r:
        last[r["seed_name"]] = r
sc = []
print("ACCEPTED:")
for name, r in sorted(last.items()):
    if r["accepted"]:
        counts = []
        for v in r["votes"]:
            if v["verdict"] == "accept":
                note = (v["constraints"].get("inference_distance") or {}).get("note", "")
                m = re.search(r"S\s*\+\s*C\s*=\s*(\d+)", note)
                if m:
                    counts.append(int(m.group(1)))
        sc.extend(counts)
        print(f"  {name[:52]} (iter {r['iteration']}, {r['n_accept']}/3, S+C {counts})")
print("EXHAUSTED:")
for name, r in sorted(last.items()):
    if not r["accepted"]:
        fails = Counter()
        for v in r["votes"]:
            for k, c in (v.get("constraints") or {}).items():
                if isinstance(c, dict) and c.get("passed") is False:
                    fails[k] += 1
        print(f"  {name[:52]} (scope {r.get('scope','-')}, fails: {[k for k, _ in fails.most_common(3)]})")
print("\naccepting-vote S+C distribution:", dict(Counter(sc)))
