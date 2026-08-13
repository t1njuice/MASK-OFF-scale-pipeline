"""Preflight refuses a run that can reach an unpinned (model, route) pair.

An unpinned pair costs 0.0 in every report, so a panel seat can run at an
apparently free price and --max-cost never sees it. A warning printed after
the money is spent is not a check (ticket 04).
"""

import os
from unittest import mock

import pytest

from . import config, launch, panel, pricing
from .panel import Seat
from .schemas import Candidate
from .validity import build_vote_requests

HAS_OPENAI_KEY = bool(os.environ.get("OPENAI_API_KEY"))


@pytest.mark.skipif(not HAS_OPENAI_KEY, reason="see the next test")
def test_shipped_config_has_no_price_gap():
    """The configuration on disk is runnable: every reachable pair is pinned."""
    assert pricing.unpinned() == []


def test_a_missing_openai_key_is_a_price_gap_not_a_silent_reroute(monkeypatch):
    """Without OPENAI_API_KEY the sol panel seat falls back to OpenRouter,
    which is not pinned for sol. Preflight must say so rather than let a seat
    run at $0. Set the key or pin the OpenRouter rate — do not relax the check.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert pricing.reachable_routes("openai/gpt-5.6-sol") == {"openrouter_sync"}
    assert ("openai/gpt-5.6-sol", "openrouter_sync") in pricing.unpinned()


def test_locked_gate_configuration():
    """The panel and the quorum match .scratch/gate-config-lock.

    The panel is a list of Seats now (ticket 07), so the assertion pins each
    seat's effort and output cap as well as its model — the cap is what the
    gate's cost is (seats x cap) and it used to sit outside the panel where
    nothing checked it against the lock.
    """
    assert config.VALIDITY_PANEL == [
        Seat("kimi", "moonshotai/kimi-k3", "high", 30000),
        Seat("grok", "x-ai/grok-4.5", "high", 30000),
        Seat("sol", "openai/gpt-5.6-sol", "high", 30000),
    ]
    assert config.VALIDITY_VOTES == 3
    assert config.VALIDITY_ACCEPT == 2
    # The cap now DIVERGES from the gate-config lock's 10 by user decision
    # (2026-08-13); panel and quorum still match it.
    assert config.FROZEN_MAX_ITERATIONS == 7


def test_the_quorum_is_configuration_not_a_function_of_panel_size():
    """2-of-3 stays 2-of-3 while the panel changes shape around it.

    A quorum derived from `len(VALIDITY_PANEL)` would silently move the bar an
    item has to clear every time a seat is added or removed.
    """
    assert config.VALIDITY_ACCEPT == 2 and config.VALIDITY_VOTES == 3
    assert config.VALIDITY_ACCEPT != len(config.VALIDITY_PANEL)

    cand = Candidate.model_construct(
        taxonomy="t", hidden_fact="h", system_prompt="s", user_email="e",
        pressure_factor="p", primary_lever="l", disclosure_rationale="d",
    )
    # five seats, still three votes: the vote count follows VALIDITY_VOTES
    five = [Seat(f"s{i}", "claude-opus-4-8", "high", 100) for i in range(5)]
    with mock.patch.object(config, "VALIDITY_PANEL", five):
        reqs = build_vote_requests("cand-x", cand)
    assert [r["custom_id"] for r in reqs] == [f"cand-x__vote{i}" for i in range(3)]

    # two seats, three votes: the panel cycles rather than short-changing the vote
    two = five[:2]
    with mock.patch.object(config, "VALIDITY_PANEL", two):
        models = [r["params"]["model"] for r in build_vote_requests("cand-x", cand)]
    assert len(models) == config.VALIDITY_VOTES


def test_a_seat_carries_its_own_effort_and_token_cap():
    """The cost model is (seats x output cap), so the cap cannot be one global
    ceiling every seat pays."""
    cand = Candidate.model_construct(
        taxonomy="t", hidden_fact="h", system_prompt="s", user_email="e",
        pressure_factor="p", primary_lever="l", disclosure_rationale="d",
    )
    mixed = [
        Seat("cheap", "claude-opus-4-8", "low", 1000),
        Seat("deep", "claude-opus-4-8", "high", 30000),
        Seat("cheap2", "claude-opus-4-8", "low", 1000),
    ]
    with mock.patch.object(config, "VALIDITY_PANEL", mixed):
        reqs = build_vote_requests("cand-x", cand)
    assert [r["params"]["max_tokens"] for r in reqs] == [1000, 30000, 1000]
    assert [r["params"]["output_config"]["effort"] for r in reqs] == [
        "low", "high", "low"]


def test_flex_model_also_needs_its_standard_fallback_pinned():
    """openai_flex drags openai_sync in: a capacity 429 falls back to standard
    and is billed at standard rates."""
    routes = pricing.reachable_routes("openai/gpt-5.6-sol")
    assert "openai_flex" in routes
    assert "openai_sync" in routes


def test_unpinned_judge_seat_is_reported(monkeypatch):
    """A second judge seat is reachable and so must be priced like the first."""
    monkeypatch.setattr(config, "JUDGE_PANEL", [
        *config.JUDGE_PANEL,
        Seat("ghost", "claude-not-a-real-model", "high", 8000),
    ])
    assert ("claude-not-a-real-model", "anthropic_batch") in pricing.unpinned()


def test_the_shipped_judge_panel_is_two_models_both_priced():
    """The final judge, confirmed 2026-08-13. Routing is left to routes.route:
    terra lands on flex at Batch API rates, opus-4-8 on the Anthropic batch,
    and neither has a ROUTE_OVERRIDES entry."""
    assert [seat.model for seat in config.JUDGE_PANEL] == [
        "openai/gpt-5.6-terra", "claude-opus-4-8",
    ]
    assert config.ROUTE_OVERRIDES == {}
    for seat in config.JUDGE_PANEL:
        for route in pricing.reachable_routes(seat.model):
            assert (seat.model, route) in config.PRICES, (seat.model, route)


def test_unpinned_panel_seat_is_reported(monkeypatch):
    monkeypatch.setattr(config, "VALIDITY_PANEL", [
        *config.VALIDITY_PANEL[:2],
        Seat("ghost", "x-ai/grok-9.9", "high", 30000),
    ])
    assert ("x-ai/grok-9.9", "openrouter_sync") in pricing.unpinned()


def test_openrouter_key_check_covers_every_role(monkeypatch, capsys):
    """Regression: the key check was hand-built from the roster, generator and
    panel, so it missed the thermometer, seedgen, judge and smoke models. It
    only caught seedgen while a roster model happened to share its provider.

    Make the roster, generator and panel Claude-only — which ticket 07 is
    expected to do — and the OpenRouter-routed seedgen model must still be
    named rather than crashing later with a raw KeyError.
    """
    claude = Seat("c", "claude-opus-4-8", "high", 8000)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(config, "TARGET_PANEL", [claude])
    monkeypatch.setattr(config, "VALIDITY_PANEL", [claude] * 3)
    monkeypatch.setattr(config, "JUDGE_PANEL", [claude])
    monkeypatch.setattr(config, "THERMOMETER_SEAT", claude)

    def _no_client():
        raise AssertionError("preflight built a client before checking the key")

    monkeypatch.setattr(launch, "client", _no_client)
    assert launch.preflight() is False
    assert config.SEEDGEN_MODEL in capsys.readouterr().err


def test_preflight_fails_on_an_unpinned_model(monkeypatch, capsys):
    """It fails BEFORE any request: no credential is touched and no client is
    built, so an unpinned model cannot reach a provider."""
    monkeypatch.setattr(config, "JUDGE_PANEL", [
        Seat("ghost", "claude-not-a-real-model", "high", 8000)])

    def _no_client():
        raise AssertionError("preflight built a client before checking prices")

    monkeypatch.setattr(launch, "client", _no_client)
    assert launch.preflight() is False
    assert "claude-not-a-real-model on anthropic_batch" in capsys.readouterr().err


def test_unpinned_model_costs_zero_which_is_why_preflight_exists():
    """The behaviour the check guards against, stated once."""
    usage = {"model": "claude-not-a-real-model", "route": "anthropic_batch",
             "output_tokens": 1_000_000}
    assert pricing.usage_cost(usage) == 0.0


def test_smoke_model_leaves_the_reachable_set_when_disabled(monkeypatch):
    smoke = config.OPUS5_SMOKE_SEAT.model
    monkeypatch.setattr(config, "OPUS5_SMOKE_N", 0)
    assert smoke not in pricing.configured_models()
    monkeypatch.setattr(config, "OPUS5_SMOKE_N", 10)
    assert smoke in pricing.configured_models()


def test_preflight_refuses_a_panel_that_reuses_a_seat_label(monkeypatch, capsys):
    """Two seats under one label share their request ids, so the cache serves
    one seat's answer to both and the second model is paid for but never
    sampled. It fails before any client is built."""
    monkeypatch.setattr(config, "TARGET_PANEL", [
        Seat("kimi", "moonshotai/kimi-k3", "high", 8000),
        Seat("kimi", "claude-opus-4-8", "high", 8000),
    ])

    def _no_client():
        raise AssertionError("preflight built a client before checking labels")

    monkeypatch.setattr(launch, "client", _no_client)
    assert launch.preflight() is False
    assert "TARGET_PANEL reuses the seat label(s) ['kimi']" in capsys.readouterr().err


def test_the_shipped_panels_label_every_seat_uniquely():
    for name in ("VALIDITY_PANEL", "TARGET_PANEL", "JUDGE_PANEL"):
        assert panel.duplicate_labels(getattr(config, name)) == [], name


def test_one_model_may_fill_every_gate_seat(monkeypatch):
    """The gate is exempt from the label check, and must stay exempt: a vote is
    identified by its slot, never by a label, so a single-model 3-vote panel is
    legal — it is what the old `VALIDITY_PANEL = None` fallback meant."""
    claude = Seat("c", "claude-opus-4-8", "high", 30000)
    monkeypatch.setattr(config, "VALIDITY_PANEL", [claude] * 3)
    monkeypatch.setattr(launch, "client", lambda: (_ for _ in ()).throw(
        AssertionError("preflight should have reached the client, not refused")))
    # the price and label checks both pass; only the client stub stops it
    assert pricing.unpinned() == []
    with pytest.raises(AssertionError):
        launch.preflight()


def test_every_panel_seat_reaches_the_price_check(monkeypatch):
    """Regression shape from ticket 05: a hand-built model list drifts from the
    panels it is supposed to enumerate. Put an unpriced seat on each panel in
    turn and preflight must name it — no panel may be invisible to the check.
    """
    for name in ("VALIDITY_PANEL", "TARGET_PANEL", "JUDGE_PANEL"):
        with mock.patch.object(config, name, [
            Seat("ghost", "x-ai/grok-9.9", "high", 1000)
        ]):
            assert ("x-ai/grok-9.9", "openrouter_sync") in pricing.unpinned(), name


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
