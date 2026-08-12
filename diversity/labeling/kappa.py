"""Agreement statistics for label files: Cohen's kappa, PABAK, Krippendorff's alpha.

Usage:
    .venv/bin/python diversity/labeling/kappa.py out/author_AR.jsonl out/author_XX.jsonl

Each file: jsonl with result_id + one or more label keys. Pairwise statistics run
over the shared result_ids. Task A response rows use "<item id>#<response key>"
as result_id and "label" as the key, so they need no separate code path.

Prints per pair and per axis: n, raw agreement, kappa with a 95% bootstrap
interval, PABAK, alpha. Then, per axis, the top confusion pairs — the overlap
diagnostic from LABELING_DESIGN.md §6: one ordered pair holding 30% or more of
an axis's disagreements is a named residual overlap in the menu, not noise.

Files whose stamps (menu_version, sample_sha) disagree are NOT compared. Two
menus produce two different measurements; a kappa across them means nothing.
"""

import json
import random
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

BOOTSTRAP = 2000
OVERLAP_SHARE = 0.30  # pre-declared: a confusion pair at or above this is an overlap


def cohen_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in ca) / n**2
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def pabak(a: list[str], b: list[str]) -> float:
    po = sum(x == y for x, y in zip(a, b)) / len(a)
    return 2 * po - 1


def krippendorff_alpha(a: list[str], b: list[str]) -> float:
    """Nominal alpha for exactly two raters, no missing data."""
    pairs = list(zip(a, b))
    values = Counter(a) + Counter(b)
    n = sum(values.values())
    do = sum(x != y for x, y in pairs) / len(pairs)  # observed disagreement
    de = 1 - sum(c * (c - 1) for c in values.values()) / (n * (n - 1))
    return 1 - do / de if de else 1.0


def kappa_ci(
    a: list[str], b: list[str], clusters: list[str] | None = None, reps: int = BOOTSTRAP
) -> tuple[float, float]:
    """95% percentile bootstrap interval. Seeded, so it repeats.

    `clusters` names the independent unit. Task A rows are graded three at a time on
    one screen (design §12), so the three labels of an item are one joint judgment,
    not three draws. Resampling responses there would report an interval that is too
    narrow; resampling items reports the precision the design actually bought.
    """
    rng = random.Random(0)
    groups = defaultdict(list)
    for i, key in enumerate(clusters if clusters is not None else range(len(a))):
        groups[key].append(i)
    keys = list(groups)
    draws = []
    for _ in range(reps):
        idx = [i for _ in keys for i in groups[rng.choice(keys)]]
        draws.append(cohen_kappa([a[i] for i in idx], [b[i] for i in idx]))
    draws.sort()
    return draws[int(0.025 * reps)], draws[min(reps - 1, int(0.975 * reps))]


AXIS_KEYS = ["role", "beneficiary", "institution", "standing", "label"]
# "role" = legacy flat scheme; "label" = Task A response label
SENTENCE_KEYS = ["beneficiary", "institution", "standing"]
STAMPS = ["menu_version", "sample_sha"]


def load(path: str) -> dict[str, dict]:
    rows = {}
    for r in map(json.loads, Path(path).read_text().splitlines()):
        if r["result_id"] in rows:
            raise SystemExit(f"{path}: duplicate row for {r['result_id']} — fix the file by hand")
        rows[r["result_id"]] = r
    # sentence-level label: the assembled triple; agreement = the whole sentence matches
    for r in rows.values():
        if all(k in r for k in SENTENCE_KEYS):
            r["sentence"] = "+".join(r[k] for k in SENTENCE_KEYS)
    return rows


def stamps_of(rows: dict[str, dict]) -> dict[str, set]:
    return {s: {r.get(s) for r in rows.values()} for s in STAMPS}


def confusion(a: list[str], b: list[str], top: int = 5) -> list[tuple[tuple[str, str], int]]:
    """Ordered disagreement pairs, most common first."""
    return Counter((x, y) for x, y in zip(a, b) if x != y).most_common(top)


def main(paths: list[str]) -> None:
    sets = {Path(p).stem: load(p) for p in paths}
    for name, rows in sets.items():
        st = stamps_of(rows)
        print(f"{name}: n={len(rows)} " + " ".join(f"{s}={sorted(map(str, st[s]))}" for s in STAMPS))
    print()
    print(f"{'pair / axis':<58} {'n':>4} {'po':>6} {'kappa':>6} {'95% CI':>15} {'PABAK':>6} {'alpha':>6}")
    for (na, la), (nb, lb) in combinations(sets.items(), 2):
        for s in STAMPS:
            sa, sb = stamps_of(la)[s], stamps_of(lb)[s]
            if sa != sb:
                print(f"{na} vs {nb}: SKIPPED — {s} differs ({sorted(map(str, sa))} vs {sorted(map(str, sb))})")
                break
        else:
            ids = sorted(la.keys() & lb.keys())
            if not ids:
                print(f"{na} vs {nb}: no shared result_ids")
                continue
            for key in AXIS_KEYS + ["sentence"]:
                if any(key not in next(iter(x.values())) for x in (la, lb)):
                    continue
                a = [la[i][key] for i in ids]
                b = [lb[i][key] for i in ids]
                po = sum(x == y for x, y in zip(a, b)) / len(a)
                cl = [i.split("#")[0] for i in ids]
                lo, hi = kappa_ci(a, b, clusters=cl if len(set(cl)) < len(ids) else None)
                print(
                    f"{na + ' vs ' + nb + ' / ' + key:<58} {len(ids):>4} {po:>6.3f}"
                    f" {cohen_kappa(a, b):>6.3f} [{lo:>6.3f},{hi:>6.3f}]"
                    f" {pabak(a, b):>6.3f} {krippendorff_alpha(a, b):>6.3f}"
                )
                pairs = confusion(a, b)
                bad = sum(n for _p, n in pairs)
                for (x, y), n in pairs:
                    share = n / max(1, sum(1 for p, q in zip(a, b) if p != q))
                    mark = "  <-- OVERLAP" if share >= OVERLAP_SHARE else ""
                    print(f"      {x} / {y}: {n} ({share:.0%} of disagreements){mark}")
                if not bad:
                    print("      no disagreements")
    for name, rows in sets.items():
        print(f"\n{name}: n={len(rows)}")
        for key in AXIS_KEYS:
            if key not in next(iter(rows.values())):
                continue
            counts = Counter(r[key] for r in rows.values())
            other = counts.get("other", 0)
            print(f"  {key}: other-rate={other / len(rows):.1%} {dict(counts.most_common())}")
        hard = sum(1 for r in rows.values() if r.get("hard_case"))
        print(f"  hard cases flagged: {hard}/{len(rows)} ({hard / len(rows):.1%})")


def _selfcheck() -> None:
    a = ["x", "x", "y", "y", "z", "z", "x", "y"]
    assert cohen_kappa(a, a) == 1.0 and pabak(a, a) == 1.0
    b = ["x", "x", "y", "z", "z", "z", "x", "x"]
    k = cohen_kappa(a, b)
    assert 0 < k < 1, k
    # kappa < raw agreement because chance agreement is removed
    assert k < sum(x == y for x, y in zip(a, b)) / len(a)
    assert -1 <= krippendorff_alpha(a, b) <= 1
    lo, hi = kappa_ci(a, b, reps=200)
    assert lo <= k <= hi, (lo, k, hi)
    # Correlated-within-cluster data: 20 items where all 3 responses agree, 10 where
    # all 3 disagree. Treating 90 responses as independent overstates the precision,
    # so the clustered interval must come out WIDER on the same rows.
    ca, cb, keys = [], [], []
    for item in range(30):
        lab, other = "xyz"[item % 3], "xyz"[(item + 1) % 3]
        for _r in range(3):
            ca.append(lab)
            cb.append(lab if item < 20 else other)
            keys.append(str(item))
    wide = kappa_ci(ca, cb, clusters=keys, reps=400)
    tight = kappa_ci(ca, cb, reps=400)
    assert (wide[1] - wide[0]) > (tight[1] - tight[0]), (wide, tight)
    assert confusion(a, b)[0] == (("y", "z"), 1) or confusion(a, b)[0][1] >= 1
    assert Counter(dict(confusion(a, b)))[("y", "x")] == 1


if __name__ == "__main__":
    _selfcheck()
    if len(sys.argv) > 2:
        main(sys.argv[1:])
    else:
        print("selfcheck ok — pass 2+ label files to compare")
