"""The run dashboard reads artifacts and never touches the run.

Run: pytest mask_off/test_dashboard.py
"""

import json
import os
from pathlib import Path

import pytest

from . import dashboard

P6_LOG = Path(__file__).resolve().parent.parent / "docs/evidence/p6_gate_pilot_run_log.jsonl"


def _write(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


@pytest.fixture
def run_dir(tmp_path):
    rows = [json.loads(x) for x in P6_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    _write(tmp_path / "run_log.jsonl", rows)
    _write(tmp_path / "accepted.jsonl", [r for r in rows if r.get("accepted")])
    (tmp_path / "state.json").write_text(json.dumps({
        "target": 300, "cohort": 1, "consumed": ["a", "b"], "run_yield": 0.737,
        "in_flight": ["b"],
    }), encoding="utf-8")
    return tmp_path


def test_snapshot_reports_the_run(run_dir):
    snap = dashboard.snapshot(run_dir)
    assert snap["items"] == 14
    assert snap["target"] == 300
    assert snap["replay"]["waves"] == 102
    assert round(snap["cost"], 2) == 23.85
    assert snap["pid"] == 0, "no live process wrote the lock"


def test_a_missing_run_directory_renders_instead_of_raising(tmp_path):
    snap = dashboard.snapshot(tmp_path / "nope")
    assert snap["exists"] is False
    dashboard.render(snap)  # must not raise


def test_an_empty_run_directory_renders(tmp_path):
    """A run that has been created but has not written a record yet."""
    snap = dashboard.snapshot(tmp_path)
    assert snap["items"] == 0 and snap["replay"] == {}
    dashboard.render(snap)


def test_a_batch_in_flight_is_counted_until_its_results_are_cached(tmp_path):
    """The in-flight test is the one drain_orphans applies: a handle whose
    every key is stored has landed, anything else is paid for and outstanding.
    """
    _write(tmp_path / "_batches.jsonl", [
        {"kind": "handle", "route": "anthropic_batch", "batch_id": "b1",
         "custom_ids": ["a"], "keys": {"a": "k1"}},
        {"kind": "handle", "route": "openai_flex", "batch_id": "b2",
         "custom_ids": ["b"], "keys": {"b": "k2"}},
    ])
    assert dashboard.batches(tmp_path)["open"] == {"anthropic_batch": 1, "openai_flex": 1}

    _write(tmp_path / "_results.jsonl", [{"key": "k1", "custom_id": "a", "payload": {}}])
    assert dashboard.batches(tmp_path)["open"] == {"openai_flex": 1}, "b1 has landed"


def test_a_drained_batch_is_not_in_flight(tmp_path):
    _write(tmp_path / "_batches.jsonl", [
        {"kind": "handle", "route": "anthropic_batch", "batch_id": "b1",
         "custom_ids": ["a"], "keys": {"a": "k1"}, "refresh_ids": ["a"]},
        {"kind": "drained", "batch_id": "b1"},
    ])
    counted = dashboard.batches(tmp_path)
    assert counted["open"] == {} and counted["drained"] == 1


def test_a_refresh_batch_stays_in_flight_despite_a_cached_key(tmp_path):
    """A refresh resubmits under keys the STALE rows already occupy, so the
    cache can never prove it completed. Only a drained marker can."""
    _write(tmp_path / "_batches.jsonl", [
        {"kind": "handle", "route": "anthropic_batch", "batch_id": "b1",
         "custom_ids": ["a"], "keys": {"a": "k1"}, "refresh_ids": ["a"]},
    ])
    _write(tmp_path / "_results.jsonl", [{"key": "k1", "custom_id": "a", "payload": {}}])
    assert dashboard.batches(tmp_path)["open"] == {"anthropic_batch": 1}


def test_reading_a_run_directory_does_not_write_to_it(run_dir):
    before = {p.name: p.stat().st_mtime_ns for p in run_dir.iterdir()}
    dashboard.snapshot(run_dir)
    after = {p.name: p.stat().st_mtime_ns for p in run_dir.iterdir()}
    assert before == after, "the dashboard must be safe against a live run"


@pytest.fixture
def seeds_dir(tmp_path):
    out = tmp_path / "seeds_300"
    (out / "scenarios" / "seeds").mkdir(parents=True)
    for i in range(23):
        (out / "scenarios" / "seeds" / f"seed_{i}.md").write_text("body\n")
    _write(out / "author_log.jsonl", [
        {"row": f"row {i}", "domain": f"Domain {i % 3}",
         "usage": {"model": "deepseek/deepseek-v4-flash-0731",
                   "route": "openrouter_sync",
                   "input_tokens": 4000, "output_tokens": 2300},
         "ts": f"2026-08-13T10:{i:02d}:00+00:00",
         **({"error": "boom"} if i == 4 else {"seeds": [f"seed_{i}"]})}
        for i in range(6)
    ])
    _write(tmp_path / "seeds_300_cheap.jsonl", [
        {"seed_name": f"seed_{i}", "audit": {"verdict": i % 3 != 0}}
        for i in range(18)
    ])
    return out


def test_seed_snapshot_counts_seeds_rows_and_failures(seeds_dir):
    snap = dashboard.seed_snapshot(seeds_dir)
    assert snap["seeds_on_disk"] == 23
    assert snap["rows_attempted"] == 6
    assert snap["rows_failed"] == 1, "a failed row is logged and never retried"
    assert snap["domains"] == ["Domain 0", "Domain 1", "Domain 2"]
    assert snap["audited"] == 18
    assert snap["audit_passed"] == 12
    assert snap["cost"] > 0, "authoring is cheap, not free"
    dashboard.render_seeds(snap)


def test_seed_costs_show_below_a_cent(seeds_dir):
    """Authoring runs at fractions of a cent. Two decimals report it as free,
    which is how a cost stops being watched."""
    snap = dashboard.seed_snapshot(seeds_dir)
    assert dashboard._money(snap["cost"]) != "$0.00"
    assert dashboard._money(1234.5) == "$1,234.50"


def test_a_directory_with_no_authoring_renders(tmp_path):
    snap = dashboard.seed_snapshot(tmp_path / "nothing")
    assert snap["exists"] is False
    dashboard.render_seeds(snap)


def test_both_stages_render_together(run_dir, seeds_dir):
    dashboard.screen(run_dir, seeds_dir)
    dashboard.screen(run_dir, None)
    dashboard.screen(None, seeds_dir)


def test_age_reads_at_a_glance():
    assert dashboard._age(38) == "38s"
    assert dashboard._age(12 * 60) == "12m"
    assert dashboard._age(4 * 3600 + 7 * 60) == "4h 07m"
    assert dashboard._age(50 * 3600) == "2d 2h"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def _text(renderable) -> str:
    """A renderable as the plain text a terminal would show."""
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    Console(file=buf, width=200, no_color=True).print(renderable)
    return buf.getvalue()


# --- what a run has bought before its first wave tallies --------------------


def test_the_dashboard_shows_spend_the_run_log_cannot_see_yet(tmp_path):
    """A record reaches the run log only when a WAVE tallies — generator, lint
    and all three votes together. On the 20-seed run this was written for that
    took 39 minutes, and the dashboard read $0.00 for all of it while $10.57
    was billed. The cache holds each result the moment it lands, with its usage
    and its route, so it can be priced request by request.
    """
    _write(tmp_path / "_results.jsonl", [
        {"custom_id": "s0__w1", "key": "k0", "kind": "message", "payload": {
            "usage": {"model": "claude-opus-4-8", "route": "anthropic_batch",
                      "input_tokens": 1000, "output_tokens": 10000}}},
    ])
    (tmp_path / "run_log.jsonl").write_text("", encoding="utf-8")
    snap = dashboard.snapshot(tmp_path)

    assert snap["cost"] == 0.0, "the run log is genuinely empty"
    # 1000 in at $2.50/M + 10000 out at $12.50/M
    assert snap["committed"] == pytest.approx(0.0025 + 0.125)
    assert "already bought" in _text(dashboard.render(snap))


def test_a_run_whose_waves_have_tallied_does_not_double_report(run_dir):
    """`committed` is shown only while it is ahead of the log. Once the waves
    tally, the log is the authority and the extra line goes away."""
    snap = dashboard.snapshot(run_dir)
    assert snap["cost"] > 0
    assert snap["committed"] == 0.0, "no cache in this fixture"


def test_a_live_run_is_not_reported_as_cap_exhausted(tmp_path, monkeypatch):
    """The dashboard defect, end to end. Every seed at wave 1 of a live run
    reads `cap_exhausted` under inference, because the deepest wave reached IS
    the inferred cap. A live run reports only what it recorded.
    """
    rows = [
        {"seed_name": f"s{i}", "iteration": 1, "accepted": False,
         "seed_defect": False, "n_votes": 3, "n_accept": 0,
         "stop_rule": {"failed_constraints": ["inference_distance"]},
         "ts": "2026-08-13T13:24:56+00:00"}
        for i in range(16)
    ]
    _write(tmp_path / "run_log.jsonl", rows)
    (tmp_path / "state.json").write_text(json.dumps(
        {"target": 20, "cohort": 1, "consumed": [f"s{i}" for i in range(16)],
         "in_flight": [], "run_yield": 0.0}), encoding="utf-8")
    (tmp_path / "_scale.pid").write_text(str(os.getpid()), encoding="utf-8")

    snap = dashboard.snapshot(tmp_path)
    assert snap["pid"] == os.getpid(), "the fixture must look alive"
    assert snap["replay"]["stop_reasons"] == {"running": 16}

    # and a dead run directory infers exactly as it always did
    (tmp_path / "_scale.pid").unlink()
    dead = dashboard.snapshot(tmp_path)
    assert dead["replay"]["stop_reasons"] == {"cap_exhausted": 16}
