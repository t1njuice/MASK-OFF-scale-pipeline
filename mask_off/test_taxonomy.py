"""The taxonomy, the balanced row draw, and the domain a seed carries.

The corpus is balanced across fourteen domains (CONTEXT.md, **Domain**), and
until now nothing in the code could see them. `seedgen author` wrote the
taxonomy into frontmatter; `seeds.load_seeds` strips frontmatter before
`harm_class` reads the body; so every authored seed classified as "other", the
per-domain quota became `quota = target`, and the stratified draw and the
interleave both did nothing. Silently — a run looked fine and was not balanced.

Run: pytest mask_off/test_taxonomy.py
"""

import random
from pathlib import Path

from . import taxonomy
from .seeds import Seed, harm_class, load_seeds


def test_the_taxonomy_is_fourteen_domains_of_forty_rows():
    """The shape design.md 7.1 plans against: 14 x 40 x SEEDGEN_SEEDS_PER_CALL
    is the 2,800 seeds it sizes the 1,200-item run from."""
    doms = taxonomy.domains()
    assert len(doms) == 14, sorted(doms)
    assert sum(len(rows) for rows in doms.values()) == 560


def test_every_domain_slug_is_distinct():
    """The slug is the stratification key. Two domains sharing one would merge
    two axes of the corpus into a single pool without any error."""
    slugs = [taxonomy.slug(d) for d in taxonomy.domains()]
    assert len(set(slugs)) == 14, sorted(slugs)


def test_no_row_belongs_to_two_domains():
    """A seed's domain is recovered from its row when it predates the `domain:`
    key, so a duplicated row would make that recovery ambiguous."""
    rows = [row for rows in taxonomy.domains().values() for row in rows]
    assert len(set(rows)) == len(rows)


def test_a_row_draw_spreads_across_domains_rather_than_draining_one():
    """The failure this replaces: a hand-written TSV, or any draw that takes
    rows in file order, authors forty rows of one domain before touching the
    next. At 81 rows for a 300-item run that is two domains of fourteen."""
    rows = taxonomy.balanced_rows(28, random.Random(1))
    counts = {}
    for domain, _ in rows:
        counts[domain] = counts.get(domain, 0) + 1
    assert len(counts) == 14, counts
    assert max(counts.values()) - min(counts.values()) <= 1, counts


def test_a_top_up_draws_rows_that_were_not_authored_before():
    """Authoring 20 rows and later wanting 30 must buy 10 NEW rows, not
    re-author and re-bill the first 20."""
    first = taxonomy.balanced_rows(20, random.Random(1))
    taken = {row for _, row in first}
    more = taxonomy.balanced_rows(10, random.Random(1), taken=taken)
    assert len(more) == 10
    assert not (taken & {row for _, row in more})


def test_the_draw_stops_at_the_taxonomy_instead_of_repeating_it():
    """Asking for more rows than exist returns every row once. Repeating rows
    would author duplicate scenarios at full price."""
    rows = taxonomy.balanced_rows(600, random.Random(1))
    assert len(rows) == 560
    assert len({row for _, row in rows}) == 560


def test_an_authored_seed_stratifies_by_its_frontmatter_domain(tmp_path):
    """The bug, stated directly. The seed carries its taxonomy in frontmatter
    and nothing in the body; before the fix it read as "other"."""
    seeds_dir = tmp_path / "corpus" / "scenarios" / "seeds"
    seeds_dir.mkdir(parents=True)
    (seeds_dir / "a_seed.md").write_text(
        "---\n"
        "subcategory: coastal wetland fill and mitigation\n"
        "domain: Environment\n"
        "---\n\n"
        "WORLD: a ferry desk.\nFACT: the culvert is undersized.\n",
        encoding="utf-8",
    )
    seed = load_seeds(tmp_path / "corpus")[0]
    assert seed.domain == "Environment"
    assert harm_class(seed) == "environment"


def test_a_seed_authored_before_the_domain_key_recovers_it_from_its_row(tmp_path):
    """experiments/seedpilot20b is in exactly this state: 20 seeds with a
    `subcategory:` and no `domain:`. Its row IS a taxonomy row, so the domain
    is recoverable and those seeds must not need re-authoring."""
    seeds_dir = tmp_path / "corpus" / "scenarios" / "seeds"
    seeds_dir.mkdir(parents=True)
    (seeds_dir / "b_seed.md").write_text(
        "---\nsubcategory: coastal wetland fill and mitigation\n---\n\nWORLD: x.\n",
        encoding="utf-8",
    )
    seed = load_seeds(tmp_path / "corpus")[0]
    assert harm_class(seed) == "environment"


def test_a_seed_whose_row_is_not_in_the_taxonomy_is_other(tmp_path):
    """An unknown row must not raise and must not invent a domain."""
    seeds_dir = tmp_path / "corpus" / "scenarios" / "seeds"
    seeds_dir.mkdir(parents=True)
    (seeds_dir / "c_seed.md").write_text(
        "---\nsubcategory: something nobody wrote down\n---\n\nWORLD: x.\n",
        encoding="utf-8",
    )
    assert harm_class(load_seeds(tmp_path / "corpus")[0]) == "other"


def test_the_kimi_corpus_still_reads_its_inline_tag():
    """kimi_100 carries no frontmatter domain and must keep classifying by the
    inline `MATERIAL FACT: ... [tag]`. The two vocabularies do not mix, and a
    change to the new path must not move the old corpus."""
    seeds = load_seeds(Path(__file__).resolve().parent.parent / "kimi_100")
    counts: dict[str, int] = {}
    for seed in seeds:
        counts[harm_class(seed)] = counts.get(harm_class(seed), 0) + 1
    assert counts == {"fiduciary": 39, "privacy": 9, "safety": 53}, counts


def test_harm_class_still_takes_bare_text():
    """Every existing caller passes `seed.text`, and a Seed with no domain must
    fall through to the body rather than answering "other" for both corpora."""
    body = "MATERIAL FACT: the wiring is unsafe [safety/rider]\n"
    assert harm_class(body) == "safety"
    assert harm_class(Seed("n", body, "src")) == "safety"
