"""What the corpus repeats, in its own words — the companion to a Self-BLEU score.

    .venv/bin/python diversity/shared_text.py output/<accepted>.jsonl

Self-BLEU says HOW MUCH the items repeat each other. It never says WHAT they
repeat, so a bad score gives you no edit to make. This prints the actual shared
phrases, ranked by how many DISTINCT items carry them (document frequency, not
raw count — one item that says a phrase nine times must not outrank nine items
that say it once).

Same principle as the confusion-pair table in kappa.py: the score is the size,
this is the shape. Read them together or a number is all you get.

Two readings, and they need different actions:

  - A phrase mandated by the generator prompt is a DESIGN CONSTANT. Report it
    once with its rationale; do not "fix" it. The tone line
    "Keep replies warm and concise." is the standing example — the frozen
    generator prompt (generator_system_v5.md, version 5.2-v5) fixes it verbatim
    on purpose, because varied phrasings read as an instruction to answer only
    the literal question.
  - A phrase nobody asked for is a GENERATOR TIC, and it is what the lexical
    diversity row is about.

The sender-name report is separate because entity convergence is its own failure
(ticket 011). It reports the effective number of first names, which is the same
Hill q=1 that trigger_family.py computes on trigger families (hill.py is
retired with the role axes, 2026-08-27).
"""

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

FIELDS = ("system_prompt", "user_email")
SIZES = (5, 8)
TOP = 12
_WORD = re.compile(r"[a-z']+")
_SENDER = re.compile(r"From:\s*([a-z][a-z.'-]*)\.([a-z][a-z.'-]*)@", re.I)


def effective_number(counts: Counter) -> float:
    """exp(Shannon) — the same statistic hill.py reports, in units of categories."""
    n = sum(counts.values())
    if not n:
        return 0.0
    h = -sum((c / n) * math.log(c / n) for c in counts.values() if c)
    return math.exp(h)


def doc_frequency(texts: list[str], size: int) -> Counter:
    """How many distinct texts contain each n-gram. Per-text dedupe is the point."""
    df = Counter()
    for t in texts:
        words = _WORD.findall(t.lower())
        df.update({" ".join(words[i : i + size]) for i in range(len(words) - size + 1)})
    return df


def report_field(rows: list[dict], field: str) -> None:
    texts = [r[field] for r in rows if r.get(field)]
    if not texts:
        return
    n = len(texts)
    print(f"\n{'=' * 72}\n{field} — phrases shared across the most distinct items (n={n})\n{'=' * 72}")
    for size in SIZES:
        print(f"\n-- {size}-grams --")
        top = [(g, c) for g, c in doc_frequency(texts, size).most_common(TOP) if c > 1]
        if not top:
            print("  nothing repeats across two or more items")
            continue
        for gram, c in top:
            print(f"  {c:>4} items ({c / n:>5.1%})  {gram}")


def report_senders(rows: list[dict]) -> None:
    """Entity convergence: the 'Priya 6/26' failure, measured (ticket 011)."""
    first, full = Counter(), Counter()
    for r in rows:
        m = _SENDER.search(r.get("user_email", ""))
        if m:
            first[m.group(1).lower()] += 1
            full[f"{m.group(1)} {m.group(2)}".lower()] += 1
    if not first:
        print("\nno sender addresses parsed — check the email format")
        return
    n = sum(first.values())
    print(f"\n{'=' * 72}\nsender names (parsed {n} of {len(rows)} items)\n{'=' * 72}")
    print(
        f"  first names: {len(first)} distinct · effective {effective_number(first):.1f}\n"
        f"  full names:  {len(full)} distinct · effective {effective_number(full):.1f}"
    )
    for name, c in first.most_common(6):
        print(f"    {c:>4} ({c / n:>5.1%})  {name}")
    top_share = first.most_common(1)[0][1] / n
    if top_share >= 0.10:
        print(
            f"\n  WARNING: one first name holds {top_share:.0%} of senders."
            " The name pool draws without replacement (seedgen.name_stream), so a"
            " share this high means the pool is not reaching the generated text."
        )


def load(paths: list[str]) -> list[dict]:
    rows, seen = [], set()
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            rid = r.get("result_id")
            if rid in seen:  # the same item can appear in two run files
                continue
            seen.add(rid)
            rows.append(r)
    return rows


def _selfcheck() -> None:
    a, b = "the cat sat on the mat today", "the cat sat on the wall today"
    df = doc_frequency([a, b], 5)
    assert df["the cat sat on the"] == 2, df.most_common(3)
    assert df["cat sat on the mat"] == 1
    # one text repeating a phrase must not outweigh two texts saying it once
    twice = "one two three four five one two three four five"
    assert doc_frequency([twice], 5)["one two three four five"] == 1
    assert abs(effective_number(Counter({"a": 5, "b": 5})) - 2.0) < 1e-9
    assert abs(effective_number(Counter({"a": 10})) - 1.0) < 1e-9
    assert effective_number(Counter({"a": 90, "b": 5, "c": 5})) < 2.0


if __name__ == "__main__":
    _selfcheck()
    if len(sys.argv) < 2:
        print("selfcheck ok — pass one or more item jsonl files")
        raise SystemExit
    rows = load(sys.argv[1:])
    print(f"{len(rows)} unique items from {len(sys.argv) - 1} file(s)")
    for field in FIELDS:
        report_field(rows, field)
    report_senders(rows)
