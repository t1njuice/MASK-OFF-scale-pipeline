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


# ---------------------------------------------------------------------------
# Frame projection (amendment 2026-08-22, LABELING_DESIGN.md §13).
#
# The role-audit frame is a stratified draw: disagree + agree_cell are censuses
# (weight_stratum = 1), agree_noncell is a seeded SRS (weight_stratum > 1).
# The gate statistic is the FRAME-PROJECTED kappa: Horvitz–Thompson-weighted
# P_o and marginals, kappa formed from those. The registered 0.80 / 0.67 bars
# apply to this number. Per-stratum unweighted kappas are diagnostics only —
# the enriched stratum understates kappa by construction, and the SRS stratum
# is too small to read alone.


def weighted_kappa(a: list[str], b: list[str], w: list[float]) -> tuple[float, float]:
    """(P_o, kappa) with item weights: weighted agreement, weighted marginals."""
    tot = sum(w)
    po = sum(wi for x, y, wi in zip(a, b, w) if x == y) / tot
    ca, cb = defaultdict(float), defaultdict(float)
    for x, y, wi in zip(a, b, w):
        ca[x] += wi
        cb[y] += wi
    pe = sum(ca[k] * cb[k] for k in ca) / tot**2
    return po, (po - pe) / (1 - pe) if pe < 1 else 1.0


def projected_ci(
    a: list[str], b: list[str], w: list[float], strata: list[str], reps: int = BOOTSTRAP
) -> tuple[float, float]:
    """95% stratified bootstrap on the frame-projected kappa. Seeded.

    Census strata (weight 1) are held FIXED — under the finite-population
    estimand they carry no sampling error. Only sampled strata (weight > 1)
    are resampled. No fpc on the resample, so the interval is slightly
    conservative for a without-replacement draw.
    """
    rng = random.Random(0)
    fixed = [i for i, wi in enumerate(w) if wi == 1.0]
    sampled = defaultdict(list)
    for i, (wi, s) in enumerate(zip(w, strata)):
        if wi != 1.0:
            sampled[s].append(i)
    draws = []
    for _ in range(reps):
        idx = fixed + [rng.choice(members) for s, members in sampled.items() for _i in members]
        draws.append(weighted_kappa([a[i] for i in idx], [b[i] for i in idx], [w[i] for i in idx])[1])
    draws.sort()
    return draws[int(0.025 * reps)], draws[min(reps - 1, int(0.975 * reps))]


def load_frame(path: str) -> dict:
    frame = json.loads(Path(path).read_text())
    meta = {i["result_id"]: i for i in frame["items"]}
    frame["meta"] = meta
    return frame


def project_pair(na: str, la: dict, nb: str, lb: dict, frame: dict) -> None:
    meta = frame["meta"]
    ids = sorted(la.keys() & lb.keys() & meta.keys())
    dropped = len(la.keys() & lb.keys()) - len(ids)
    per_stratum = Counter(meta[i]["stratum"] for i in ids)
    coverage = "  ".join(
        f"{s}={per_stratum.get(s, 0)}/{sum(1 for m in meta.values() if m['stratum'] == s)}"
        for s in frame["stratum_frames"]
    )
    print(f"\n{na} vs {nb} — frame projection ({coverage}; {dropped} shared rows outside frame)")
    if not ids:
        return
    incomplete = any(
        per_stratum.get(s, 0) < sum(1 for m in meta.values() if m["stratum"] == s)
        for s in frame["stratum_frames"]
    )
    if incomplete:
        print("  ⚠ frame not fully labeled — projections below are PROVISIONAL")
    strata = [meta[i]["stratum"] for i in ids]
    ws = [meta[i]["weight_stratum"] for i in ids]
    wc = [meta[i]["weight"] for i in ids]  # × weight_domain: corpus rates only
    for key in SENTENCE_KEYS:
        if any(key not in next(iter(x.values())) for x in (la, lb)):
            continue
        a = [la[i][key] for i in ids]
        b = [lb[i][key] for i in ids]
        po_f, k_f = weighted_kappa(a, b, ws)
        lo, hi = projected_ci(a, b, ws, strata)
        po_c, k_c = weighted_kappa(a, b, wc)
        # trivial-rater baseline: the best weighted single-label agreement
        base = max(
            sum(wi for y, wi in zip(col, ws) if y == lab) / sum(ws)
            for col in (a, b)
            for lab in set(col)
        )
        print(
            f"  {key:<12} frame: po={po_f:.3f} kappa={k_f:.3f} [{lo:.3f},{hi:.3f}]"
            f"   corpus: po={po_c:.3f} kappa={k_c:.3f}   majority-baseline po={base:.3f}"
        )
        for s in frame["stratum_frames"]:
            sa = [x for x, st in zip(a, strata) if st == s]
            sb = [y for y, st in zip(b, strata) if st == s]
            if len(set(sa) | set(sb)) < 2 or not sa:
                continue
            print(
                f"      [{s}] n={len(sa)} po={sum(x == y for x, y in zip(sa, sb)) / len(sa):.3f}"
                f" kappa={cohen_kappa(sa, sb):.3f}  (diagnostic only)"
            )


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


def main(paths: list[str], frame_path: str | None = None) -> None:
    frame = load_frame(frame_path) if frame_path else None
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
    if frame:
        print(f"\n=== FRAME-PROJECTED (gate) — role_audit strata {frame['stratum_frames']} ===")
        for (na, la), (nb, lb) in combinations(sets.items(), 2):
            if any(r.get("sample_sha") != frame["sample_sha"] for x in (la, lb) for r in x.values()):
                print(f"{na} vs {nb}: frame projection SKIPPED — sample_sha differs from frame")
                continue
            project_pair(na, la, nb, lb, frame)
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
    # frame projection: uniform weights in one stratum must reproduce plain kappa
    w1 = [1.0] * len(a)
    po_u, k_u = weighted_kappa(a, b, w1)
    assert abs(k_u - cohen_kappa(a, b)) < 1e-12 and abs(po_u - 6 / 8) < 1e-12
    # census-only strata carry no sampling error: the interval must be a point
    lo1, hi1 = projected_ci(a, b, w1, ["c"] * len(a), reps=50)
    assert lo1 == hi1 == k_u, (lo1, hi1, k_u)
    # up-weighting disagreeing items must pull kappa down
    w2 = [1.0 if x == y else 4.0 for x, y in zip(a, b)]
    assert weighted_kappa(a, b, w2)[1] < k_u
    # sampled stratum resamples: interval must widen around the point estimate
    lo2, hi2 = projected_ci(a, b, w2, ["s"] * len(a), reps=200)
    assert lo2 < hi2


if __name__ == "__main__":
    _selfcheck()
    argv = sys.argv[1:]
    frame_path = None
    if "--frame" in argv:
        i = argv.index("--frame")
        frame_path = argv[i + 1]
        argv = argv[:i] + argv[i + 2 :]
    if len(argv) >= 2:
        main(argv, frame_path)
    else:
        print("selfcheck ok — usage: kappa.py [--frame role_audit.json] <file1> <file2> [...]")
