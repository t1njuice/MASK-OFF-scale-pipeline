"""The seed taxonomy: fourteen domains, forty rows each.

`seed_subcategories.md` at the repo root is the corpus's axis of balance —
CONTEXT.md's **Domain** is one of its fourteen headings, and a **row** is one
subcategory under a heading. Every seed is authored for exactly one row.

This module is the one reader of that file. It exists because the draw was not
written down anywhere the code could reach: `seedgen author` took a TSV a human
typed, while `design.md` §7.1 planned against "the 560-request authoring batch"
and 2,800 seeds. Fourteen domains times forty rows times five seeds a row IS
that batch; nothing produced it.

A domain's **slug** is the first word of its heading, lowercased. All fourteen
are distinct, so the slug is a key and not a lossy summary.

The slugs are NOT `seeds._HARM_CLASSES`. That set normalises the inline
`[tag]` the kimi_100 corpus carries, and its aliases deliberately collapse
distinctions this taxonomy keeps — `immigration` to `status`, `data` to
`privacy`, `finance` to `fiduciary`. Two corpora, two vocabularies. Do not
stratify one run across both.
"""

import functools
import re
from pathlib import Path

# Repo root, not PROMPTS_DIR: the taxonomy is a corpus artifact a human edits,
# not a prompt the generator is shown.
TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "seed_subcategories.md"


@functools.lru_cache(maxsize=1)
def domains() -> dict[str, list[str]]:
    """{domain heading: [row, ...]}, in file order.

    A heading may carry a parenthesised gloss that scopes who the sender is;
    it is part of the prompt's meaning, not of the domain's identity, so it is
    cut here and the heading is the text before it.
    """
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in TAXONOMY_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            current = line[2:].split(" (")[0].strip()
            out.setdefault(current, [])
        elif line.startswith("- ") and current is not None:
            out[current].append(line[2:].strip())
    return out


def slug(domain: str) -> str:
    """The stratification key for a domain heading: its first word, lowercased.

    Distinct across all fourteen headings, checked by test. A heading this
    module has never seen still slugs rather than raising, so a corpus authored
    against an edited taxonomy stratifies instead of collapsing to "other".
    """
    return re.split(r"[ /]", domain.strip())[0].lower()


@functools.lru_cache(maxsize=1)
def _row_index() -> dict[str, str]:
    """{row: domain heading}. Rows are unique across the file; a duplicate row
    would make a seed's domain ambiguous, so the test pins uniqueness."""
    return {row: domain for domain, rows in domains().items() for row in rows}


def domain_of_row(row: str) -> str:
    """The domain heading a row belongs to, or "" when the row is unknown.

    This is how a seed authored before `domain:` was written into frontmatter
    still finds its domain: its `subcategory:` line IS the row.
    """
    return _row_index().get(row.strip(), "")


def rows() -> list[tuple[str, str]]:
    """Every (domain, row) pair in the taxonomy, in file order."""
    return [(domain, row) for domain, rs in domains().items() for row in rs]


def balanced_rows(n: int, rng, taken: set[str] = frozenset()) -> list[tuple[str, str]]:
    """`n` (domain, row) pairs spread as evenly as possible across domains.

    Rows in `taken` are skipped, so authoring 80 rows and later topping up to
    120 draws 40 NEW rows rather than re-authoring what is already on disk.

    Even means round-robin over domains sorted by how many rows each has left
    unauthored — a domain that fell behind catches up, and a domain whose rows
    are exhausted drops out instead of starving the ones after it. This is the
    same rule `scale.draw` uses for seeds, for the same reason.
    """
    pools = {d: [r for r in rs if r not in taken] for d, rs in domains().items()}
    for pool in pools.values():
        rng.shuffle(pool)
    drawn: dict[str, int] = {}
    out: list[tuple[str, str]] = []
    while len(out) < n:
        eligible = [d for d in sorted(pools) if pools[d]]
        if not eligible:
            break
        domain = min(eligible, key=lambda d: (drawn.get(d, 0), d))
        out.append((domain, pools[domain].pop()))
        drawn[domain] = drawn.get(domain, 0) + 1
    return out
