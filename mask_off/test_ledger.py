"""Tests for mask_off.ledger.

Two kinds of test here. The synthetic ones pin the deduplication rule — the
one piece of logic in the module that is not addition. The evidence ones pin
the dollar totals of the two published run logs, so a later refactor cannot
move a figure that `docs/evidence/README.md` quotes.
"""

import json
from pathlib import Path

import pytest

from . import ledger

EVIDENCE = Path(__file__).resolve().parent.parent / "docs" / "evidence"

# Two pinned (model, route) pairs, so every fixture dollar is exact:
#   claude-opus-4-8 / anthropic_batch : $2.50 in, $12.50 out per MTok
#   moonshotai/kimi-k3 / openrouter_sync : $3.00 in, $15.00 out per MTok
GEN = {"model": "claude-opus-4-8", "route": "anthropic_batch"}
VOTE = {"model": "moonshotai/kimi-k3", "route": "openrouter_sync"}
GEN_COST = 100_000 * 2.5 / 1e6 + 100_000 * 12.5 / 1e6  # $1.50
VOTE_COST = 100_000 * 3.0 / 1e6 + 100_000 * 15.0 / 1e6  # $1.80


def _usage(pair: dict) -> dict:
    return {**pair, "input_tokens": 100_000, "output_tokens": 100_000,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def _decision(seed: str, wave: int, votes: int = 2) -> dict:
    """A decision record: nested usage, no `stage` field."""
    return {
        "seed_name": seed, "iteration": wave, "accepted": False,
        "votes": [{"verdict": "revise"}] * votes,
        "usage": {"generator": _usage(GEN),
                  "votes": [_usage(VOTE) for _ in range(votes)]},
        "ts": "2026-08-12T00:00:00+00:00",
    }


DECISION_COST = GEN_COST + 2 * VOTE_COST


def _error(seed: str, wave: int, stage: str = "generator") -> dict:
    """An error record: one flat usage dict, and a `stage` field."""
    return {"seed_name": seed, "iteration": wave, "stage": stage,
            "error": "RuntimeError('boom')", "usage": _usage(GEN)}


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


# --- the deduplication rule -----------------------------------------------


def test_replayed_waves_are_not_double_counted(tmp_path):
    """The rule the module exists for.

    A resumed cohort replays from the top and re-logs every wave it already
    ran. When the batch cache rehydrates the earlier result the re-logged
    record carries the same usage numbers, and that work was billed once.
    """
    once = [_decision("s1", 1), _decision("s2", 1), _decision("s1", 2)]
    replayed = [*once, _decision("s1", 1), _decision("s2", 1), _decision("s1", 2),
                _decision("s1", 3)]
    first = ledger.total(ledger.entries(once))
    again = ledger.total(ledger.entries(replayed))
    assert first == pytest.approx(3 * DECISION_COST)
    assert again == pytest.approx(4 * DECISION_COST)  # the new wave only

    log = _write(tmp_path / "run_log.jsonl", replayed)
    assert ledger.run_total(tmp_path) == pytest.approx(again)
    assert ledger.total(ledger.log_entries(log)) == pytest.approx(again)


def test_dedup_key_survives_concurrent_waves(tmp_path):
    """Ticket 10 lets seeds advance independently, so records interleave.

    The key is per (seed, wave, stage) and reads nothing from the order of
    the log, so an interleaved log totals exactly like a lockstep one. A seed
    cannot have two waves in flight at once — wave N+1 needs wave N's
    feedback — so one seed's waves stay distinct keys, not a collision.
    """
    lockstep = [_decision("s1", 1), _decision("s2", 1),
                _decision("s1", 2), _decision("s2", 2)]
    # s2 runs ahead of s1, and its replayed wave 1 lands between them.
    interleaved = [_decision("s2", 1), _decision("s2", 2), _decision("s1", 1),
                   _decision("s2", 1), _decision("s1", 2)]
    assert ledger.total(ledger.entries(interleaved)) == pytest.approx(
        ledger.total(ledger.entries(lockstep)))
    assert len(ledger.entries(interleaved)) == 4 * 3  # 4 waves x (gen + 2 votes)


def test_stage_is_part_of_the_key(tmp_path):
    """Two records of one wave at different stages are two spends, not one.

    A lint regeneration and the decision it feeds are the same (seed, wave)
    but different money.
    """
    lint = {"seed_name": "s1", "iteration": 1, "stage": "lint",
            "regenerated": True, "usage": _usage(GEN)}
    rows = [lint, _decision("s1", 1)]
    assert ledger.total(ledger.entries(rows)) == pytest.approx(
        GEN_COST + DECISION_COST)


def test_a_relogged_record_without_usage_does_not_erase_a_priced_one():
    """Latest-wins would zero a wave if an empty re-log counted as a record."""
    rows = [_decision("s1", 1),
            {"seed_name": "s1", "iteration": 1, "usage": {}},
            {"seed_name": "s1", "iteration": 1}]
    assert ledger.total(ledger.entries(rows)) == pytest.approx(DECISION_COST)


# --- shapes ----------------------------------------------------------------


def test_error_record_flat_usage_is_priced():
    assert ledger.total(ledger.entries([_error("s3", 1)])) == pytest.approx(GEN_COST)


def test_stage_attribution_inside_a_decision_record():
    """A decision record carries no stage; its blocks still name theirs."""
    by_stage = ledger.by_stage(ledger.entries([_decision("s1", 1)]))
    assert by_stage["generator"] == pytest.approx(GEN_COST)
    assert by_stage["validity"] == pytest.approx(2 * VOTE_COST)


def test_usage_entries_price_a_stage_with_no_run_log():
    """Stage B writes no run log, so it hands the ledger its usage dicts."""
    entries = ledger.usage_entries([_usage(GEN), _usage(VOTE)], stage="eval")
    assert ledger.total(entries) == pytest.approx(GEN_COST + VOTE_COST)
    assert set(ledger.by_stage(entries)) == {"eval"}
    assert ledger.by_route(entries) == pytest.approx(
        {"anthropic_batch": GEN_COST, "openrouter_sync": VOTE_COST})


def test_unpinned_model_still_costs_zero():
    """Ticket 04 owns refusing this at preflight; the ledger just reports 0."""
    entries = ledger.usage_entries(
        [{"model": "nobody/unpinned-9", "route": "openrouter_sync",
          "output_tokens": 1_000_000}], stage="generator")
    assert ledger.total(entries) == 0.0
    assert ledger.by_model(entries) == {"nobody/unpinned-9": 0.0}


def test_missing_log_is_zero(tmp_path):
    assert ledger.run_total(tmp_path) == 0.0
    assert ledger.log_entries(tmp_path / "nope.jsonl") == []


def test_breakdowns_sum_to_the_total():
    entries = ledger.entries([_decision("s1", 1), _error("s2", 1)])
    total = ledger.total(entries)
    for grouped in (ledger.by_stage(entries), ledger.by_model(entries),
                    ledger.by_route(entries)):
        assert sum(grouped.values()) == pytest.approx(total)


# --- published figures -----------------------------------------------------


def test_p6_evidence_total_is_unchanged():
    """`docs/evidence/README.md` cap ladder, cap 10 row: $23.85."""
    entries = ledger.log_entries(EVIDENCE / "p6_gate_pilot_run_log.jsonl")
    assert round(ledger.total(entries), 2) == 23.85


def test_frozen_19_evidence_total_is_unchanged():
    """$24.59, not the README's $36.21: one legacy panel seat carries an
    unpinned (model, route) pair and prices at zero. Expected; see ticket 04."""
    entries = ledger.log_entries(EVIDENCE / "frozen_19_run_log.jsonl")
    assert round(ledger.total(entries), 2) == 24.59


def test_evidence_usage_block_count_matches_summarize():
    """186 blocks, the figure docs/evidence/summarize.py asserts. The ledger
    must see every block that script sees, priced or not."""
    entries = ledger.log_entries(EVIDENCE / "frozen_19_run_log.jsonl")
    assert len(entries) == 186


def test_metrics_report_prints_the_ledger_total(tmp_path):
    """The acceptance criterion: one number, and it survives a resume.

    The report is fed a log whose waves are logged twice, as a resumed run
    logs them, and must print the deduplicated total.
    """
    from .metrics import report

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rows = [_decision("s1", 1), _decision("s2", 1)]
    _write(run_dir / "run_log.jsonl", rows + rows)
    text = report(run_dir).read_text(encoding="utf-8")
    assert f"${2 * DECISION_COST:.2f}" in text
    assert f"${4 * DECISION_COST:.2f}" not in text
    # per stage, per model, per route all present
    assert "generator" in text and "validity" in text
    assert "anthropic_batch" in text and "openrouter_sync" in text


def test_p6_breakdowns_sum_to_its_total():
    entries = ledger.log_entries(EVIDENCE / "p6_gate_pilot_run_log.jsonl")
    total = ledger.total(entries)
    assert sum(ledger.by_stage(entries).values()) == pytest.approx(total)
    assert sum(ledger.by_model(entries).values()) == pytest.approx(total)
    assert sum(ledger.by_route(entries).values()) == pytest.approx(total)
    # p6 ran the locked panel, so the validity stage is the bulk of the bill.
    assert set(ledger.by_stage(entries)) == {"generator", "validity"}


# --- money the run log cannot see yet ---------------------------------------


def _cache_row(custom_id: str, out_tokens: int = 10000) -> dict:
    return {"custom_id": custom_id, "key": custom_id, "kind": "message",
            "payload": {"usage": {"model": "claude-opus-4-8",
                                  "route": "anthropic_batch",
                                  "input_tokens": 0,
                                  "output_tokens": out_tokens}}}


def _write_cache(run_dir, rows):
    (run_dir / "_results.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_the_cache_is_priced_by_seed_and_wave_from_the_request_id(tmp_path):
    """A Stage A id is `{seed}__w{n}` with `__lint` and `__vote{i}` inheriting
    it, so the cache can be attributed to the same (seed, wave, stage) the log
    uses — which is what makes deduplication against the log possible."""
    _write_cache(tmp_path, [
        _cache_row("a_seed__w1"), _cache_row("a_seed__w1__lint"),
        _cache_row("a_seed__w1__vote0"), _cache_row("b_seed__w3__vote2"),
    ])
    got = ledger.cache_entries(tmp_path)
    assert {(e.seed, e.wave, e.stage) for e in got} == {
        ("a_seed", 1, "generator"), ("a_seed", 1, "lint"),
        ("a_seed", 1, "validity"), ("b_seed", 3, "validity"),
    }


def test_a_stage_b_request_does_not_move_a_stage_a_ceiling(tmp_path):
    """Stage B ids carry no wave marker. Counting them would let evaluation
    spend close Stage A's admission."""
    _write_cache(tmp_path, [_cache_row("maskoff-3f2a1b__target0")])
    assert ledger.cache_entries(tmp_path) == []


def test_committed_counts_a_wave_the_log_has_not_recorded(tmp_path):
    """The defect this exists for: a record reaches the run log only when a
    WAVE tallies, so through a whole first wave the log reads $0.00 while
    requests land and are billed. `--max-cost` read that zero."""
    (tmp_path / "run_log.jsonl").write_text("", encoding="utf-8")
    _write_cache(tmp_path, [_cache_row("a_seed__w1"), _cache_row("a_seed__w1__vote0")])
    assert ledger.run_total(tmp_path) == 0.0
    assert ledger.committed_total(tmp_path) == pytest.approx(0.25)  # 20k out @ 12.5/M


def test_a_tallied_wave_is_not_billed_twice(tmp_path):
    """Once a wave tallies, its record carries every block it bought and the
    same requests are still in the cache. Deduplication is by (seed, wave):
    counting per request would double the bill of every completed wave."""
    (tmp_path / "run_log.jsonl").write_text(json.dumps({
        "seed_name": "a_seed", "iteration": 1,
        "usage": {"generator": {"model": "claude-opus-4-8",
                                "route": "anthropic_batch",
                                "input_tokens": 0, "output_tokens": 10000},
                  "votes": []},
    }) + "\n", encoding="utf-8")
    _write_cache(tmp_path, [_cache_row("a_seed__w1"), _cache_row("a_seed__w2")])

    logged = ledger.run_total(tmp_path)
    assert logged == pytest.approx(0.125)
    # wave 1 is in the log and must not be counted again; wave 2 is not
    assert ledger.committed_total(tmp_path) == pytest.approx(0.25)
    assert {(e.seed, e.wave) for e in ledger.untallied(tmp_path)} == {("a_seed", 2)}


def test_committed_equals_the_log_when_there_is_no_cache(tmp_path):
    """No cache file at all — an older run directory, or Stage B — must read
    exactly the log rather than raising or zeroing."""
    (tmp_path / "run_log.jsonl").write_text(json.dumps({
        "seed_name": "s", "iteration": 1,
        "usage": {"generator": {"model": "claude-opus-4-8",
                                "route": "anthropic_batch",
                                "input_tokens": 0, "output_tokens": 8000},
                  "votes": []},
    }) + "\n", encoding="utf-8")
    assert ledger.cache_entries(tmp_path) == []
    assert ledger.committed_total(tmp_path) == pytest.approx(ledger.run_total(tmp_path))
