"""The manifest builder: pure rows in, the frozen stratified 300 out.

The manifest is a commitment — its sha256 is recorded before Stage B submits
anything, so the cut must be a deterministic pure function: largest-remainder
quotas across domains, acceptance order within a domain, hard errors instead
of silent shortfalls, and a rehearsal draw that is a fixed-seed subset of the
exact corpus the paper uses.

Run: pytest mask_off/test_manifest.py
"""

import pytest

from .manifest import (
    DOMAIN_FIELD,
    REHEARSAL_SEED,
    build_manifest,
    dump_jsonl,
    rehearsal_draw,
)


def make_rows(counts: dict[str, int]) -> list[dict]:
    """Synthetic accepted rows, interleaved round-robin so acceptance order
    mixes domains the way a real run's accepted.jsonl does."""
    pools = {
        domain: [
            {"result_id": f"{domain}-{i}", DOMAIN_FIELD: domain, "hidden_fact": f"fact {i}"}
            for i in range(count)
        ]
        for domain, count in counts.items()
    }
    rows = []
    while any(pools.values()):
        for domain in counts:
            if pools[domain]:
                rows.append(pools[domain].pop(0))
    return rows


def domain_counts(rows):
    counts = {}
    for row in rows:
        counts[row[DOMAIN_FIELD]] = counts.get(row[DOMAIN_FIELD], 0) + 1
    return counts


def test_proportionality_matches_largest_remainder_exactly():
    """The ticket's worked case: 161/107/54 accepted over 3 domains. Exact
    shares of 300 are 150.0 / 99.69 / 50.31; floors leave one seat, and the
    largest remainder (b's .69) takes it."""
    rows = make_rows({"a": 161, "b": 107, "c": 54})
    manifest = build_manifest(rows)
    assert len(manifest) == 300
    assert domain_counts(manifest) == {"a": 150, "b": 100, "c": 50}


def test_two_calls_produce_identical_bytes():
    """The sha256 is committed before Stage B; a cut that shifts between
    invocations would make the recorded hash unreproducible."""
    rows = make_rows({"a": 161, "b": 107, "c": 54})
    assert dump_jsonl(build_manifest(rows)) == dump_jsonl(build_manifest(rows))


def test_within_a_domain_earlier_acceptance_wins():
    """First accepted, first in: the items a domain loses to its quota are
    exactly its latest accepts, never a reshuffle."""
    rows = make_rows({"a": 161, "b": 107, "c": 54})
    manifest = build_manifest(rows)
    for domain, quota in {"a": 150, "b": 100, "c": 50}.items():
        kept = [r["result_id"] for r in manifest if r[DOMAIN_FIELD] == domain]
        assert kept == [f"{domain}-{i}" for i in range(quota)]


def test_fewer_than_300_rows_is_a_hard_error():
    """A short corpus must stop the run, not ship a silently smaller paper
    corpus under the same filename."""
    rows = make_rows({"a": 150, "b": 149})
    with pytest.raises(ValueError):
        build_manifest(rows)


def test_a_row_missing_its_domain_is_a_hard_error():
    """A domainless row cannot be stratified; dropping it would be a silent
    shortfall and binning it as 'other' would invent a fifteenth domain."""
    rows = make_rows({"a": 200, "b": 101})
    del rows[57][DOMAIN_FIELD]
    with pytest.raises(ValueError):
        build_manifest(rows)


def test_rehearsal_draw_is_a_stratified_deterministic_subset():
    """n=20 from the manifest: same largest-remainder quotas at n=20, same
    subset on every call under the recorded seed, and every drawn row is a
    manifest row — the rehearsal exercises the paper's corpus, nothing else."""
    manifest = build_manifest(make_rows({"a": 161, "b": 107, "c": 54}))
    drawn = rehearsal_draw(manifest)
    assert len(drawn) == 20
    # 20 * (150, 100, 50) / 300 is exact: 10 / 6.67 / 3.33 -> 10 / 7 / 3.
    assert domain_counts(drawn) == {"a": 10, "b": 7, "c": 3}
    assert drawn == rehearsal_draw(manifest, seed=REHEARSAL_SEED)
    ids = {r["result_id"] for r in manifest}
    assert all(r["result_id"] in ids for r in drawn)
