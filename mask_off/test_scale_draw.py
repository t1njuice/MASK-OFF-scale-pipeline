"""Stage A draw, sizing, fingerprint, keepers, and replay checks. No API calls.

Run: pytest mask_off/test_scale_draw.py
"""
import json
import random

import pytest

from . import batchcache, config, llm, scale
from .seeds import Seed, harm_class


def _seed(name, domain="safety"):
    text = f"MATERIAL FACT: fact for {name} [{domain}]\nSETTING/ROLE: office"
    return Seed(name=name, text=text, source="test")


def _corpus():
    return [
        _seed(f"{d}_{i}", d)
        for d in ("safety", "privacy", "care")
        for i in range(4)
    ]


def test_harm_class_reads_the_test_seed_format():
    assert harm_class(_seed("x", "privacy").text) == "privacy"


def test_draw_is_stratified_and_skips_met_domains():
    seeds = _corpus()
    counts = {"safety": 4, "privacy": 0, "care": 0}  # safety met its quota of 4
    launch = scale.draw(seeds, set(), counts, quota=4, size=4, rng=random.Random(1))
    domains = [harm_class(s.text) for s in launch]
    assert "safety" not in domains
    assert domains.count("privacy") == 2 and domains.count("care") == 2


def test_draw_redistributes_when_below_quota_pools_run_dry():
    seeds = _corpus()
    # privacy is below quota but its pool is consumed; safety pool must fill in
    consumed = {f"privacy_{i}" for i in range(4)} | {f"care_{i}" for i in range(4)}
    launch = scale.draw(seeds, consumed, {"safety": 4}, quota=4, size=3,
                        rng=random.Random(1))
    assert len(launch) == 3
    assert all(harm_class(s.text) == "safety" for s in launch)


def test_draw_never_repeats_consumed_seeds():
    seeds = _corpus()
    first = scale.draw(seeds, set(), {}, quota=4, size=6, rng=random.Random(1))
    consumed = {s.name for s in first}
    second = scale.draw(seeds, consumed, {}, quota=4, size=6, rng=random.Random(2))
    assert not consumed & {s.name for s in second}
    assert len(first) + len(second) == len(seeds)


def test_cohort_size_adapts_and_clamps():
    assert scale.cohort_size(1200, None) == config.COHORT_BASE
    assert scale.cohort_size(3, None) == 3, "a small target must not launch COHORT_BASE"
    assert scale.cohort_size(50, 0.5) == 100  # ceil(50 / 0.5)
    assert scale.cohort_size(5, 0.9) == config.COHORT_MIN
    assert scale.cohort_size(10_000, 0.1) == config.COHORT_MAX


def test_quota_keeps_drawing_a_harsh_domain_and_reports_shortfall(
    tmp_path, monkeypatch, capsys
):
    """DoD quota demo: one domain's gate rejects everything. That domain keeps
    drawing until its pool is empty; the run ends with a reported shortfall."""
    seeds = _corpus()
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)

    def care_rejects_all(n, seeds_path, out_stem, launch=None, log_path=None,
                        items_path=None):
        with open(items_path, "a", encoding="utf-8") as f:
            for s in launch:
                if harm_class(s.text) != "care":
                    f.write(json.dumps(
                        {"seed_name": s.name, "seed_source": s.source}) + "\n")
        return [], items_path

    monkeypatch.setattr(scale.frozen_pipeline, "run", care_rejects_all)
    run_dir = tmp_path / "run"
    state = scale.generate(run_dir, tmp_path, target=12)
    assert set(state["consumed"]) == {s.name for s in seeds}, \
        "every pool, including the harsh domain's, must be fully drawn"
    assert len(scale._accepted_items(run_dir)) == 8
    out = capsys.readouterr().out
    assert "shortfall" in out and "'care': 4" in out


def _write_state(run_dir, fp):
    scale.save_state(run_dir, {
        "draw_seed": 7, "fingerprint": fp, "target": 10,
        "consumed": [], "yield_ema": None, "cohort": 0, "pending": None,
    })


def test_fingerprint_mismatch_aborts_and_force_stamps(tmp_path, monkeypatch):
    seeds = [_seed("a")]
    fp = scale.fingerprint(seeds)
    stale = dict(fp, GENERATOR_MODEL="claude-something-else")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_state(run_dir, stale)
    (run_dir / "accepted.jsonl").write_text("")  # target 0 -> no cohort runs

    def no_seeds(path):
        return seeds

    monkeypatch.setattr(scale, "load_seeds", no_seeds)
    with pytest.raises(SystemExit, match="GENERATOR_MODEL"):
        scale.generate(run_dir, tmp_path, target=0)

    scale.generate(run_dir, tmp_path, target=0, force=True)
    state = scale.load_state(run_dir)
    assert state["fingerprint"] == fp
    assert state["fingerprint_history"][0]["changed"] == ["GENERATOR_MODEL"]


def test_prompt_content_edit_changes_the_fingerprint(tmp_path, monkeypatch):
    seeds = [_seed("a")]
    before = scale.fingerprint(seeds)
    prompt = tmp_path / config.FROZEN_GENERATOR_PROMPT
    prompt.write_text("edited contents")
    (tmp_path / "validity_reviewer.md").write_text(
        (config.PROMPTS_DIR / "validity_reviewer.md").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(config, "PROMPTS_DIR", tmp_path)
    after = scale.fingerprint(seeds)
    assert scale.fingerprint_diff(before, after).keys() == {"generator_prompt_sha"}


def test_seed_keepers_restricts_the_draw(tmp_path, monkeypatch):
    seeds = _corpus()
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    keepers = tmp_path / "keepers.json"
    keepers.write_text(json.dumps(["safety_0", "privacy_1"]))
    launched = []

    def fake_run(n, seeds_path, out_stem, launch=None, log_path=None, items_path=None):
        launched.extend(s.name for s in launch)
        with open(items_path, "a", encoding="utf-8") as f:
            for s in launch:
                f.write(json.dumps({"seed_name": s.name, "seed_source": s.source}) + "\n")
        return [], items_path

    monkeypatch.setattr(scale.frozen_pipeline, "run", fake_run)
    run_dir = tmp_path / "run"
    scale.generate(run_dir, tmp_path, target=2, seed_keepers=keepers)
    assert sorted(launched) == ["privacy_1", "safety_0"]


def test_resume_replays_the_recorded_pending_cohort(tmp_path, monkeypatch):
    seeds = _corpus()
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_state(run_dir, scale.fingerprint(seeds))
    state = scale.load_state(run_dir)
    state["pending"] = {"cohort": 1, "seeds": ["care_2", "privacy_0"]}
    scale.save_state(run_dir, state)
    launches = []

    def fake_run(n, seeds_path, out_stem, launch=None, log_path=None, items_path=None):
        launches.append([s.name for s in launch])
        with open(items_path, "a", encoding="utf-8") as f:
            for s in launch:
                f.write(json.dumps({"seed_name": s.name, "seed_source": s.source}) + "\n")
        return [], items_path

    monkeypatch.setattr(scale.frozen_pipeline, "run", fake_run)
    scale.generate(run_dir, tmp_path, target=2)
    assert launches[0] == ["care_2", "privacy_0"], "resume must not redraw"
    assert scale.load_state(run_dir)["pending"] is None


def test_max_cost_stops_at_the_cohort_boundary(tmp_path, monkeypatch, capsys):
    """The ceiling stops BEFORE launching a new cohort; it never kills one
    mid-flight (design.md §7.6)."""
    seeds = _corpus()
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    launches = []

    def costly_run(n, seeds_path, out_stem, launch=None, log_path=None,
                   items_path=None):
        launches.append(len(launch))
        with open(items_path, "a", encoding="utf-8") as f:
            for s in launch[:1]:  # low yield forces a second cohort
                f.write(json.dumps({"seed_name": s.name, "seed_source": s.source}) + "\n")
        with open(log_path, "a", encoding="utf-8") as f:
            for s in launch:  # $0.0125 of opus-4-8 batch output per seed
                f.write(json.dumps({"seed_name": s.name, "usage": {"generator": {
                    "model": "claude-opus-4-8", "output_tokens": 1000}}}) + "\n")
        return [], items_path

    monkeypatch.setattr(scale.frozen_pipeline, "run", costly_run)
    scale.generate(tmp_path / "run", tmp_path, target=6, max_cost=0.01)
    assert len(launches) == 1, "the second cohort must not launch over the ceiling"
    assert "cost ceiling" in capsys.readouterr().out


def test_fill_reruns_only_missing_and_empty_cells(tmp_path, transport):
    """DoD: deleted (uncached) cells and empty-text cells re-run under --fill;
    filled cells stay free cache hits."""
    from types import SimpleNamespace

    from .evaluate import _fill_holes

    batchcache._CACHES.clear()

    def msg(text):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason="end_turn", model="claude-opus-4-8",
            usage=SimpleNamespace(input_tokens=0, output_tokens=0,
                                  cache_creation_input_tokens=0,
                                  cache_read_input_tokens=0),
        )

    reqs = [
        {"custom_id": cid, "params": {"model": "claude-opus-4-8", "user": cid}}
        for cid in ("full", "empty", "deleted")
    ]
    for req, text in ((reqs[0], "a real answer"), (reqs[1], "")):
        batchcache.append_result(
            tmp_path, batchcache.request_key(req), req["custom_id"],
            batchcache.normalize(msg(text)),
        )
    transport.respond = lambda r: msg("refilled")
    submitted = transport.calls
    with batchcache.policy(run_dir=tmp_path):
        out = llm.run_batch_retry(reqs, "Samples", None)
        assert submitted == [["deleted"]], "only the uncached cell is a miss"
        _fill_holes(reqs, out, "Samples", None)
    assert submitted == [["deleted"], ["empty"]], \
        "fill must refresh exactly the empty-text cell"
    assert llm.text_of(out["empty"]) == "refilled"
    assert llm.text_of(out["full"]) == "a real answer"


def test_unparseable_cached_vote_is_resubmitted_via_refresh(tmp_path, transport):
    """DoD: a cached vote that fails parse_vote goes through the refresh set,
    not served from cache (the resubmit_votes + cache composition)."""
    from types import SimpleNamespace

    from .frozen_pipeline import resubmit_votes

    batchcache._CACHES.clear()

    def unparseable():
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="not json")],
            stop_reason="end_turn", model="claude-opus-4-8",
            usage=SimpleNamespace(input_tokens=0, output_tokens=0,
                                  cache_creation_input_tokens=0,
                                  cache_read_input_tokens=0),
        )

    req = {"custom_id": "cand-x__vote0", "params": {"model": "claude-opus-4-8"}}
    # seed the cache with the unparseable-but-"successful" vote
    batchcache.append_result(
        tmp_path, batchcache.request_key(req), "cand-x__vote0",
        batchcache.normalize(unparseable()),
    )
    transport.respond = lambda r: unparseable()
    submitted = transport.calls
    with batchcache.policy(run_dir=tmp_path):
        first = llm.run_batch_retry([req], "Validity gate", None)
        assert submitted == [], "the bad vote is a cache hit on the first pass"
        resubmit_votes([req], first, progress=None)
    assert len(submitted) == 3, "refresh must force real resubmission, 3 passes"


def test_resubmission_supersedes_the_cached_row_under_one_key(tmp_path, transport):
    """Wave-scoped ids must not become per-attempt ids (ticket 06).

    Resubmission reuses the vote's identifier and passes a `refresh` set, so
    each attempt lands on the SAME cache key and supersedes the stale row
    (latest-wins, ADR-0002 §9/F1 rule 3). An id made unique per attempt would
    leave a second key behind and the supersession would silently stop working.
    """
    from types import SimpleNamespace

    from .frozen_pipeline import resubmit_votes

    batchcache._CACHES.clear()

    def unparseable():
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="not json")],
            stop_reason="end_turn", model="claude-opus-4-8",
            usage=SimpleNamespace(input_tokens=0, output_tokens=0,
                                  cache_creation_input_tokens=0,
                                  cache_read_input_tokens=0),
        )

    req = {"custom_id": "seed_x__w1__vote0",
           "params": {"model": "claude-opus-4-8"}}
    batchcache.append_result(
        tmp_path, batchcache.request_key(req), req["custom_id"],
        batchcache.normalize(unparseable()),
    )
    transport.respond = lambda r: unparseable()
    with batchcache.policy(run_dir=tmp_path):
        first = llm.run_batch_retry([req], "Validity gate", None)
        resubmit_votes([req], first, progress=None)

    rows = [json.loads(line) for line
            in (tmp_path / "_results.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) > 1, "the resubmitted vote was never stored"
    assert {row["key"] for row in rows} == {batchcache.request_key(req)}, \
        "an attempt landed on a second cache key instead of superseding"
    assert {row["custom_id"] for row in rows} == {req["custom_id"]}
    # latest-wins: the loaded cache holds one entry, the newest attempt
    batchcache._CACHES.clear()
    assert len(batchcache._cache(tmp_path)) == 1
