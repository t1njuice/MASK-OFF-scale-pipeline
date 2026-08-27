"""Trigger-family coverage and Hill numbers for the release pools.

    python diversity/trigger_family.py

Joins each item's `seed_name` to the seed file's `family:` frontmatter
(experiments/seedcorpus2/scenarios/seeds/). The tag is assigned at seed
authoring, so the table measures the assigned family, not the realized
one — the caption must say so. Pool B has no family tag (relconv_bare
and diverse20 seeds); it is reported as unmapped.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

SEEDS = Path("experiments/seedcorpus2/scenarios/seeds")
POOLS = {
    "pool A": "release/pool_a/dataset_pool_a_400.jsonl",
    "pool B": "release/pool_b/dataset_pool_b_100.jsonl",
}


def hill1(counts: Counter) -> float:
    n = sum(counts.values())
    return math.exp(-sum((c / n) * math.log(c / n) for c in counts.values() if c))


def main() -> None:
    fams = {}
    for p in SEEDS.glob("*.md"):
        m = re.search(r"^family:\s*(.+)$", p.read_text(), re.M)
        fams[p.stem] = m.group(1).strip() if m else None

    for name, path in POOLS.items():
        rows = [json.loads(x) for x in open(path)]
        seeds = Counter(r["seed_name"] for r in rows)
        print(f"== {name}: {len(rows)} items, {len(seeds)} distinct seeds,"
              f" max items/seed {max(seeds.values())} ==")
        fam = Counter(fams.get(r["seed_name"]) for r in rows)
        if fam.get(None, 0) == len(rows):
            print("   no family tag on any seed (unmapped pool)\n")
            continue
        for f, c in fam.most_common():
            print(f"   {f:<40} {c:>3}  {c / len(rows):.1%}")
        canon = Counter({f: c for f, c in fam.items()
                         if f and not f.startswith("other")})
        print(f"   canonical families seen (q0): {len(canon)} of 9")
        print(f"   effective families (q1): {hill1(canon):.2f}"
              f" · evenness {hill1(canon) / len(canon):.2f}"
              f" · max share {max(canon.values()) / sum(canon.values()):.1%}\n")


if __name__ == "__main__":
    assert abs(hill1(Counter({"a": 5, "b": 5})) - 2.0) < 1e-9
    assert abs(hill1(Counter({"a": 9})) - 1.0) < 1e-9
    main()
