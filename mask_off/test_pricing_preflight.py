"""Preflight refuses a run that can reach an unpinned (model, route) pair.

An unpinned pair costs 0.0 in every report, so a panel seat can run at an
apparently free price and --max-cost never sees it. A warning printed after
the money is spent is not a check (ticket 04).
"""

import os

import pytest

from . import config, launch, pricing

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
    """The panel and the quorum match .scratch/gate-config-lock."""
    assert config.VALIDITY_PANEL == [
        "moonshotai/kimi-k3",
        "x-ai/grok-4.5",
        "openai/gpt-5.6-sol",
    ]
    assert config.VALIDITY_VOTES == 3
    assert config.VALIDITY_ACCEPT == 2
    # The cap now DIVERGES from the gate-config lock's 10 by user decision
    # (2026-08-13); panel and quorum still match it.
    assert config.FROZEN_MAX_ITERATIONS == 7


def test_flex_model_also_needs_its_standard_fallback_pinned():
    """openai_flex drags openai_sync in: a capacity 429 falls back to standard
    and is billed at standard rates."""
    routes = pricing.reachable_routes("openai/gpt-5.6-sol")
    assert "openai_flex" in routes
    assert "openai_sync" in routes


def test_unpinned_judge_is_reported(monkeypatch):
    monkeypatch.setattr(config, "JUDGE_MODEL", "claude-not-a-real-model")
    assert ("claude-not-a-real-model", "anthropic_batch") in pricing.unpinned()


def test_unpinned_panel_seat_is_reported(monkeypatch):
    monkeypatch.setattr(
        config, "VALIDITY_PANEL", [*config.VALIDITY_PANEL[:2], "x-ai/grok-9.9"]
    )
    assert ("x-ai/grok-9.9", "openrouter_sync") in pricing.unpinned()


def test_openrouter_key_check_covers_every_role(monkeypatch, capsys):
    """Regression: the key check was hand-built from the roster, generator and
    panel, so it missed the thermometer, seedgen, judge and smoke models. It
    only caught seedgen while a roster model happened to share its provider.

    Make the roster, generator and panel Claude-only — which ticket 07 is
    expected to do — and the OpenRouter-routed seedgen model must still be
    named rather than crashing later with a raw KeyError.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(config, "TARGET_MODELS", ["claude-opus-4-8"])
    monkeypatch.setattr(config, "VALIDITY_PANEL", ["claude-opus-4-8"] * 3)
    monkeypatch.setattr(config, "THERMOMETER_MODEL", "claude-opus-4-8")

    def _no_client():
        raise AssertionError("preflight built a client before checking the key")

    monkeypatch.setattr(launch, "client", _no_client)
    assert launch.preflight() is False
    assert config.SEEDGEN_MODEL in capsys.readouterr().err


def test_preflight_fails_on_an_unpinned_model(monkeypatch, capsys):
    """It fails BEFORE any request: no credential is touched and no client is
    built, so an unpinned model cannot reach a provider."""
    monkeypatch.setattr(config, "JUDGE_MODEL", "claude-not-a-real-model")

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
    monkeypatch.setattr(config, "OPUS5_SMOKE_N", 0)
    assert config.OPUS5_SMOKE_MODEL not in pricing.configured_models()
    monkeypatch.setattr(config, "OPUS5_SMOKE_N", 10)
    assert config.OPUS5_SMOKE_MODEL in pricing.configured_models()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
