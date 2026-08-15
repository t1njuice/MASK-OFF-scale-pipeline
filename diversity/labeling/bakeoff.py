"""Judge bake-off (ticket 007): which judge labels closest to the authors.

    .venv/bin/python diversity/labeling/bakeoff.py \
        out/<judge_A>.jsonl out/<judge_B>.jsonl out/<author_1>.jsonl [out/<author_2>.jsonl]

The first two files are the judges. The rest are author files. The gold label
per axis is the author consensus: rows where every author file agrees. Rows
with an author disagreement are dropped and counted — they are the ceiling's
problem, not the judges'.

Frozen rule (shared-understanding §7): higher judge–gold kappa wins; a tie
goes to the non-Claude judge ("claude" in the file stem marks the Claude one).
The delta-kappa bootstrap interval is printed so a within-noise margin is
visible, but the frozen rule decides on the point estimates.

Runnable the moment the author labels exist. No labels yet: `_selfcheck` runs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kappa import AXIS_KEYS, cohen_kappa, kappa_ci, load, stamps_of  # noqa: E402


def consensus(author_rows: list[dict[str, dict]], key: str) -> dict[str, str]:
    """result_id -> label where every author file has the row and agrees."""
    shared = set.intersection(*(set(r) for r in author_rows))
    gold = {}
    for rid in shared:
        labels = {rows[rid].get(key) for rows in author_rows}
        if len(labels) == 1 and None not in labels:
            gold[rid] = labels.pop()
    return gold


def delta_ci(a1, a2, gold, clusters, reps=2000):
    """Bootstrap 95% interval on kappa(judge1) - kappa(judge2), same resamples."""
    import random
    from collections import defaultdict

    rng = random.Random(0)
    groups = defaultdict(list)
    for i, key in enumerate(clusters):
        groups[key].append(i)
    keys = list(groups)
    draws = []
    for _ in range(reps):
        idx = [i for _ in keys for i in groups[rng.choice(keys)]]
        g = [gold[i] for i in idx]
        draws.append(cohen_kappa([a1[i] for i in idx], g) - cohen_kappa([a2[i] for i in idx], g))
    draws.sort()
    return draws[int(0.025 * reps)], draws[min(reps - 1, int(0.975 * reps))]


def main(paths: list[str]) -> None:
    names = [Path(p).stem for p in paths]
    judge_names, judges = names[:2], [load(p) for p in paths[:2]]
    authors = [load(p) for p in paths[2:]]
    stamp_sets = [stamps_of(r) for r in judges + authors]
    for s in ("menu_version", "sample_sha"):
        if len({frozenset(map(str, st[s])) for st in stamp_sets}) > 1:
            raise SystemExit(f"stamp {s} differs across files — two menus/samples are two measurements")

    wins = {n: 0 for n in judge_names}
    for key in AXIS_KEYS:
        if any(key not in next(iter(j.values())) for j in judges):
            continue
        gold = consensus(authors, key)
        ids = sorted(gold.keys() & judges[0].keys() & judges[1].keys())
        if not ids:
            continue
        dropped = len(set.intersection(*(set(r) for r in authors))) - len(gold)
        g = [gold[i] for i in ids]
        ks = [cohen_kappa([j[i][key] for i in ids], g) for j in judges]
        cl = [i.split("#")[0] for i in ids]
        lo, hi = delta_ci([judges[0][i][key] for i in ids], [judges[1][i][key] for i in ids], g, cl)
        print(f"\n{key}: n={len(ids)} gold rows ({dropped} author disagreements dropped)")
        for n, k in zip(judge_names, ks):
            print(f"  {n:<50} kappa {k:.3f}")
        print(f"  delta (first - second) 95% CI [{lo:+.3f}, {hi:+.3f}]" + ("  <-- margin within noise" if lo < 0 < hi else ""))
        if ks[0] == ks[1]:
            winner = next((n for n in judge_names if "claude" not in n.lower()), judge_names[0])
            print(f"  tie -> non-Claude rule -> {winner}")
        else:
            winner = judge_names[ks.index(max(ks))]
            print(f"  winner: {winner}")
        wins[winner] += 1
    print(f"\nverdict: {max(wins, key=wins.get)} (axes won: {wins})")


def _selfcheck() -> None:
    a1 = {f"i{k}": {"label": "12"[k % 2], "menu_version": "m", "sample_sha": "s"} for k in range(12)}
    a2 = dict(a1)
    a2["i0"] = {**a1["i0"], "label": "3"}  # one author disagreement -> dropped from gold
    gold = consensus([a1, a2], "label")
    assert len(gold) == 11 and "i0" not in gold
    ids = sorted(gold)
    g = [gold[i] for i in ids]
    perfect = g[:]
    noisy = g[:-2] + ["3", "3"]
    assert cohen_kappa(perfect, g) == 1.0 > cohen_kappa(noisy, g)
    lo, hi = delta_ci(perfect, noisy, g, ids, reps=200)
    assert hi >= lo >= 0.0, (lo, hi)  # the better judge never loses a resample here
    lo2, hi2 = kappa_ci(noisy, g, reps=200)
    assert lo2 <= cohen_kappa(noisy, g) <= hi2


if __name__ == "__main__":
    _selfcheck()
    if len(sys.argv) >= 4:
        main(sys.argv[1:])
    else:
        print("selfcheck ok — usage: bakeoff.py judge_A.jsonl judge_B.jsonl author_1.jsonl [author_2.jsonl]")
