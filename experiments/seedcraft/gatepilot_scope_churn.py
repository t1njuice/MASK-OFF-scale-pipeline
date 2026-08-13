"""Separate Fix 2's two changes: merged feedback vs the most-severe Scope rule.

Fix 2 changed the forwarded diagnosis in two independent ways:
  (a) one vote's diagnosis  ->  every revise vote as an attributed block
  (b) forwarded `Scope:`     ->  most severe among revise votes, not the modal one

(b) mechanically produces more `frame` grades, and `frame` instructs a full
rebuild of prompt and email rather than a minimal diff — which breaks
constraints that were passing. So a post-fix rise in oscillation churn may be
(b)'s doing, with (a) innocent. That matters: merged blocks and the scope rule
can be shipped independently, so if (b) is the culprit the scale run can keep
merged feedback and revert `scope` to modal.

Two measurements, both from existing logs, no API calls:
  1. frame-scope share of forwarded feedback per arm
  2. churn split by the scope forwarded at the START of each transition — the
     grade that actually governed the revision that produced the next round

Usage: python gatepilot_scope_churn.py LABEL=RUN_STEM ...
"""

import json
import sys
from collections import Counter, defaultdict


def failed(vote: dict) -> set:
    return {n for n, c in vote["constraints"].items() if not c["passed"]}


def union_failed(rec: dict) -> set:
    return set().union(*(failed(v) for v in rec["votes"])) if rec["votes"] else set()


def analyze(label: str, stem: str) -> dict:
    rounds = [json.loads(l) for l in open(f"{stem}_run_log.jsonl")]
    rounds = [r for r in rounds if "votes" in r]
    by_seed = defaultdict(dict)
    for r in rounds:
        by_seed[r["seed_name"]][r["iteration"]] = r

    # 1. forwarded-scope mix over rounds that actually forwarded a diagnosis
    revises = [r for r in rounds if not r["accepted"] and r.get("feedback")]
    mix = Counter(r.get("scope") or "(none)" for r in revises)

    # 2. churn attributed to the scope that governed the revision. The feedback
    # forwarded at round i is what produced round i+1's candidate, so the
    # transition belongs to round i's grade.
    intro = Counter()   # scope -> newly-introduced failures
    trans = Counter()   # scope -> transitions
    for iters in by_seed.values():
        ks = sorted(iters)
        for a, b in zip(ks, ks[1:]):
            scope = iters[a].get("scope") or "(none)"
            intro[scope] += len(union_failed(iters[b]) - union_failed(iters[a]))
            trans[scope] += 1
    return {"label": label, "mix": mix, "n_revise": len(revises),
            "intro": intro, "trans": trans}


def main():
    arms = [analyze(*a.split("=", 1)) for a in sys.argv[1:]]

    print("=== 1. Forwarded-scope share (of rounds that forwarded a diagnosis) ===")
    scopes = sorted({s for a in arms for s in a["mix"]})
    print(f"{'arm':6} {'revise rounds':>13} " + " ".join(f"{s:>12}" for s in scopes))
    for a in arms:
        n = a["n_revise"] or 1
        cells = " ".join(f"{a['mix'][s]:>4} {a['mix'][s]/n:>6.0%}" for s in scopes)
        print(f"{a['label']:6} {a['n_revise']:>13} {cells}")

    print("\n=== 2. Churn split by the scope that governed the transition ===")
    print(f"{'arm':6} {'scope':>10} {'transitions':>12} {'new fails':>10} {'churn':>8}")
    for a in arms:
        for s in sorted(a["trans"], key=lambda s: -a["trans"][s]):
            print(f"{a['label']:6} {s:>10} {a['trans'][s]:>12} {a['intro'][s]:>10} "
                  f"{a['intro'][s]/a['trans'][s]:>8.2f}")
        tot_t, tot_i = sum(a["trans"].values()), sum(a["intro"].values())
        if tot_t:
            print(f"{a['label']:6} {'ALL':>10} {tot_t:>12} {tot_i:>10} {tot_i/tot_t:>8.2f}")

    print("\n=== 3. Like-for-like: churn on frame vs surgical transitions ===")
    print("If frame churn is similar ACROSS arms but the frame SHARE rose, the")
    print("scope rule (b) explains the aggregate rise and merged feedback (a) is")
    print("exonerated. If frame churn itself rose post-fix, (a) is implicated too.")
    print(f"\n{'arm':6} {'frame churn':>12} {'surgical churn':>15} {'frame share':>12}")
    for a in arms:
        n = a["n_revise"] or 1
        f_c = a["intro"]["frame"] / a["trans"]["frame"] if a["trans"]["frame"] else float("nan")
        s_c = a["intro"]["surgical"] / a["trans"]["surgical"] if a["trans"]["surgical"] else float("nan")
        print(f"{a['label']:6} {f_c:>12.2f} {s_c:>15.2f} {a['mix']['frame']/n:>11.0%}")

    # 4. Counterfactual: hold each arm's own per-scope churn fixed and swap in a
    # reference arm's scope MIX. The gap between observed and counterfactual is
    # the part of the arm's churn attributable purely to the scope rule (b).
    ref = next((a for a in arms if a["label"].upper() == "P4"), None)
    if ref:
        rt = sum(ref["trans"].values())
        w = {s: ref["trans"][s] / rt for s in ref["trans"]} if rt else {}
        print(f"\n=== 4. Counterfactual: each arm's churn under {ref['label']}'s scope mix ===")
        print("Observed minus counterfactual isolates the scope rule's contribution.")
        print(f"{'arm':6} {'observed':>9} {'cf':>9} {'scope-rule effect':>18}")
        for a in arms:
            cf = sum(
                w.get(s, 0) * (a["intro"][s] / a["trans"][s])
                for s in w if a["trans"].get(s)
            )
            norm = sum(w.get(s, 0) for s in w if a["trans"].get(s)) or 1
            cf /= norm
            tot_t = sum(a["trans"].values())
            obs = sum(a["intro"].values()) / tot_t if tot_t else 0
            print(f"{a['label']:6} {obs:>9.2f} {cf:>9.2f} {obs - cf:>+18.2f}")


if __name__ == "__main__":
    main()
