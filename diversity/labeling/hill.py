"""Role-facet diversity numbers from any axis-label JSONL.

    .venv/bin/python diversity/labeling/hill.py out/scan/judge_axes_scan209_*.jsonl

Per axis: the count table, coverage, and the effective number of options
(exp of Shannon entropy — "equivalent to N evenly used options"). Then the joint
grid: populated cells and the joint effective number, because 120 cells cannot be
read as a table and a populated-cell count alone rewards singletons.

Evenness = effective number / coverage. Use it to compare axes, since an axis
with 4 options cannot score above 4.
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

AXIS_KEYS = ["beneficiary", "institution", "standing"]
# option counts excluding the "other" escape; standing has no escape
SUBSTANTIVE = {"beneficiary": 5, "institution": 6, "standing": 4}


def effective_number(counts: Counter) -> float:
    """exp(Shannon). 1.0 when one option takes everything; k when k are even."""
    n = sum(counts.values())
    if not n:
        return 0.0
    h = -sum((c / n) * math.log(c / n) for c in counts.values() if c)
    return math.exp(h)


def report(rows: list[dict]) -> None:
    """Diversity is measured over the substantive options only.

    "other" is an escape meaning "no option fits", not a role. Counting it as a
    category would let unclassified items inflate coverage and the effective
    number. It is reported on its own line instead, where a rising other-rate is
    visible as the menu problem it is.
    """
    n = len(rows)
    print(f"n = {n}\n")
    for axis in AXIS_KEYS:
        if axis not in rows[0]:
            continue
        counts = Counter(r[axis] for r in rows)
        other = counts.pop("other", 0)
        if not counts:
            print(f"{axis} — every row used the 'other' escape\n")
            continue
        eff = effective_number(counts)
        print(
            f"{axis} — coverage {len(counts)} of {SUBSTANTIVE[axis]}"
            f" · effective {eff:.2f} · evenness {eff / len(counts):.2f}"
            + (f" · other {other}/{n} ({other / n:.1%}, excluded)" if other else "")
        )
        for opt, c in counts.most_common():
            bar = "#" * round(40 * c / n)
            print(f"    {opt:<14} {c:>4} {c / n:>6.1%} {bar}")
        print()

    if all(a in rows[0] for a in AXIS_KEYS):
        clean = [r for r in rows if not any(r[a] == "other" for a in AXIS_KEYS)]
        dropped = n - len(clean)
        if not clean:
            print("joint grid — every row used an 'other' escape")
            return
        joint = Counter("+".join(r[a] for a in AXIS_KEYS) for r in clean)
        reachable = math.prod(SUBSTANTIVE[a] for a in AXIS_KEYS)
        eff = effective_number(joint)
        print(
            f"joint grid — {len(joint)} combinations seen of {reachable} possible"
            f" · effective {eff:.2f}"
            + (f" · {dropped} rows dropped for 'other'" if dropped else "")
        )
        print(f"    singletons: {sum(1 for c in joint.values() if c == 1)} of {len(joint)}")
        for combo, c in joint.most_common(5):
            print(f"    {combo:<44} {c:>4} {c / len(clean):>6.1%}")
        print(
            "\nReachable cells are the full product. Some combinations are"
            " implausible rather than missing — declare the reachable set before"
            " claiming coverage of it."
        )


def _selfcheck() -> None:
    assert abs(effective_number(Counter({"a": 10})) - 1.0) < 1e-9
    assert abs(effective_number(Counter({"a": 5, "b": 5, "c": 5, "d": 5})) - 4.0) < 1e-9
    # concentration must pull the effective number far below the option count
    skewed = Counter({"a": 18, "b": 2, "c": 2, "d": 2, "e": 2})
    assert 2.5 < effective_number(skewed) < 3.2, effective_number(skewed)
    assert effective_number(skewed) < effective_number(Counter({k: 5 for k in "abcde"}))
    assert effective_number(Counter()) == 0.0


if __name__ == "__main__":
    _selfcheck()
    if len(sys.argv) < 2:
        print("selfcheck ok — pass one axis-label jsonl")
    else:
        for path in sys.argv[1:]:
            print(f"=== {path}")
            report([json.loads(x) for x in Path(path).read_text().splitlines()])
