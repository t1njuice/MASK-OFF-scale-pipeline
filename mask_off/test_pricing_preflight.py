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


@pytest.fixture()
def _empty_evalaware_panel(monkeypatch):
    # For tests that build minimal one-seat worlds by patching every panel
    # they know about; EVALAWARE_PANEL (eval-awareness ablation) postdates
    # them and would leak its unpatched seats into configured_models. NOT
    # autouse (review I4): the shipped-config gap test must see the real
    # panel, or an unpinned ablation seat ships unnoticed.
    monkeypatch.setattr(config, "EVALAWARE_PANEL", [])

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
    terra lands on flex at Batch API rates, opus-4-8 on the Anthropic batch."""
    assert [seat.model for seat in config.JUDGE_PANEL] == [
        "openai/gpt-5.6-terra", "claude-opus-4-8",
    ]
    for seat in config.JUDGE_PANEL:
        for route in pricing.reachable_routes(seat.model):
            assert (seat.model, route) in config.PRICES, (seat.model, route)


def test_unpinned_panel_seat_is_reported(monkeypatch):
    monkeypatch.setattr(config, "VALIDITY_PANEL", [
        *config.VALIDITY_PANEL[:2],
        Seat("ghost", "x-ai/grok-9.9", "high", 30000),
    ])
    assert ("x-ai/grok-9.9", "openrouter_sync") in pricing.unpinned()


@pytest.mark.usefixtures("_empty_evalaware_panel")
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


@pytest.mark.usefixtures("_empty_evalaware_panel")
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


def test_preflight_probes_an_anthropic_model_not_the_generator(monkeypatch):
    """The credential probe was hardwired to GENERATOR_MODEL on the Anthropic
    client, which held only while the generator was a claude-* id. A
    non-Claude generator — the ablation table's cross-generator row — 404s a
    model that is perfectly reachable on openrouter_sync."""
    flash = "deepseek/deepseek-v4-flash-0731"
    seat = Seat("f", flash, "medium", 8000)
    monkeypatch.setattr(config, "GENERATOR_MODEL", flash)
    monkeypatch.setattr(config, "VALIDITY_PANEL", [seat] * 3)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")

    probed = []

    class _Client:
        class messages:
            @staticmethod
            def create(model, **kw):
                probed.append(model)

    monkeypatch.setattr(launch, "client", lambda: _Client())
    assert launch.preflight() is True
    assert probed, "preflight never proved the Anthropic credential"
    assert probed[0].startswith("claude"), f"probed a non-Anthropic model: {probed[0]}"


# --- Stage B preflight totals (ticket 08) ----------------------------------
# The pure seam: synthetic targets and panels on models whose route does not
# depend on the environment (claude-* is always anthropic_batch, an OpenRouter
# slug always openrouter_sync), so the counts and dollars are deterministic.

KIMI_A = Seat("a", "moonshotai/kimi-k3", "high", 1000)
OPUS_B = Seat("b", "claude-opus-4-8", "high", 2000)
JUDGE_J = Seat("j", "claude-opus-4-8", "high", 8000)


def _all_flags(monkeypatch, recognition=True, salience=True, probe2=True):
    monkeypatch.setattr(config, "RECOGNITION", recognition)
    monkeypatch.setattr(config, "SALIENCE", salience)
    monkeypatch.setattr(config, "PROBE2", probe2)
    monkeypatch.setattr(config, "JUDGE_PANEL", [JUDGE_J])
    # the fixed judge roles are terra in the shipped config, whose route
    # depends on OPENAI_API_KEY — pin them to a stable route for the test
    stable = Seat("terra", "moonshotai/kimi-k3", "high", 8000)
    monkeypatch.setattr(config, "HARM_JUDGE_SEAT", stable)
    monkeypatch.setattr(config, "SALIENCE_JUDGE_SEAT", stable)
    monkeypatch.setattr(config, "GATE_JUDGE_SEAT", stable)


def test_stage_b_totals_counts_every_request_class(monkeypatch):
    """2 items x 2 seats, all flags on, K=5: every class hand-computed.

    The data-dependent classes are UPPER bounds on purpose (the honest
    preflight number): harm-judge assumes all clean-YES, salience-judge
    assumes no literal NONE, the variant assumes every rewrite fails its
    gate once (so variant and gate each count twice per item).
    """
    _all_flags(monkeypatch)
    got = launch.stage_b_totals(
        2, [(KIMI_A, 5), (OPUS_B, 5)], smoke_n=0)
    counts = {name: entry["requests"] for name, entry in got["stages"].items()}
    assert counts == {
        "roleplay": 20,          # 2 items x 2 seats x K=5
        "roleplay_judge": 4,     # 2 items x 1 judge x 2 seat-chunks (B1)
        "recognition": 4,        # 2 items x 2 seats x 1
        "recognition_judge": 4,  # upper bound: every response clean-YES
        "salience": 8,           # 2 items x 2 seats x SALIENCE_K=2
        "salience_judge": 8,     # upper bound: no response is a NONE
        "variant": 4,            # 2 items x (1 + 1 regeneration)
        "variant_gate": 4,       # 2 items x (1 gate + 1 re-gate)
        "probe2": 8,             # 2 items x 2 seats x PROBE2_K=2
        "probe2_judge": 4,       # 2 items x 1 judge x 2 seat-chunks (B1)
    }
    assert got["requests"] == 68
    assert got["dollars"] > 0
    assert got["dollars"] == sum(
        entry["dollars"] for entry in got["stages"].values())


def test_a_flag_that_is_off_removes_its_classes(monkeypatch):
    """A disabled instrument contributes ZERO requests: its classes are
    absent from the table, not present at zero."""
    _all_flags(monkeypatch, recognition=False, salience=False, probe2=False)
    got = launch.stage_b_totals(2, [(KIMI_A, 5), (OPUS_B, 5)], smoke_n=0)
    assert set(got["stages"]) == {"roleplay", "roleplay_judge"}
    assert got["requests"] == 24  # 20 roleplay + 2 items x 1 judge x 2 chunks

    _all_flags(monkeypatch, recognition=True, salience=False, probe2=False)
    got = launch.stage_b_totals(2, [(KIMI_A, 5), (OPUS_B, 5)], smoke_n=0)
    assert set(got["stages"]) == {
        "roleplay", "roleplay_judge", "recognition", "recognition_judge"}

    _all_flags(monkeypatch, recognition=False, salience=False, probe2=True)
    got = launch.stage_b_totals(2, [(KIMI_A, 5), (OPUS_B, 5)], smoke_n=0)
    assert set(got["stages"]) == {
        "roleplay", "roleplay_judge", "variant", "variant_gate",
        "probe2", "probe2_judge"}


def test_stage_b_totals_prices_one_pass_at_a_time(monkeypatch):
    """Review M6: the go/no-go number is the pass's real cost — the sample
    pass shows no judge dollars, the judge pass no roleplay dollars, and
    the two passes sum to the census (both-pass) bound."""
    _all_flags(monkeypatch, recognition=False, salience=False, probe2=False)
    sample = launch.stage_b_totals(2, [(KIMI_A, 5)], smoke_n=0, judge=False)
    assert set(sample["stages"]) == {"roleplay"}
    judged = launch.stage_b_totals(2, [(KIMI_A, 5)], smoke_n=0, judge=True)
    assert set(judged["stages"]) == {"roleplay_judge"}
    both = launch.stage_b_totals(2, [(KIMI_A, 5)], smoke_n=0)
    assert both["dollars"] == pytest.approx(
        sample["dollars"] + judged["dollars"])


def test_stage_b_totals_dollars_are_hand_computable(monkeypatch):
    """The dollar bound is (input assumption x worst input rate + output cap
    x output rate) per request, over synthetic prices. The judge's input
    additionally carries the response caps it batches, and its input prices
    at the cache-write rate where one is pinned (the more expensive side)."""
    _all_flags(monkeypatch, recognition=False, salience=False, probe2=False)
    monkeypatch.setattr(config, "JUDGE_PANEL", [
        Seat("j", "claude-opus-4-8", "high", 500)])
    monkeypatch.setattr(config, "PRICES", {
        ("moonshotai/kimi-k3", "openrouter_sync"):
            {"in": 1.0, "out": 2.0, "cached_in": 0.1},
        ("claude-opus-4-8", "anthropic_batch"):
            {"in": 2.0, "out": 4.0, "cache_write": 6.0, "cached_in": 0.2},
    })
    monkeypatch.setattr(launch, "PREFLIGHT_INPUT_TOKENS", 0)
    got = launch.stage_b_totals(3, [(KIMI_A, 2)], smoke_n=0)
    # roleplay: 6 requests x 1000 out-cap x $2/MTok = $0.012
    assert got["stages"]["roleplay"]["requests"] == 6
    assert got["stages"]["roleplay"]["dollars"] == pytest.approx(0.012)
    # judge: 3 requests x (2000 carried response tokens x $6 cache-write
    # + 500 out-cap x $4) / 1e6 = $0.042
    assert got["stages"]["roleplay_judge"]["requests"] == 3
    assert got["stages"]["roleplay_judge"]["dollars"] == pytest.approx(0.042)


def test_stage_b_totals_fails_hard_on_a_missing_price(monkeypatch):
    """A seat missing a price in any role is a hard failure, never a $0 row."""
    _all_flags(monkeypatch)
    ghost = Seat("g", "x-ai/grok-9.9", "high", 1000)
    with pytest.raises(ValueError, match=r"x-ai/grok-9\.9 on openrouter_sync"):
        launch.stage_b_totals(2, [(ghost, 5)], smoke_n=0)


def test_stage_b_totals_fails_hard_on_an_unusable_target_label(monkeypatch):
    """The guard also covers programmatic targets that never pass through
    config: the pure function refuses them itself."""
    _all_flags(monkeypatch, recognition=False, salience=False, probe2=False)
    bad = Seat("a__p2", "claude-opus-4-8", "high", 1000)
    with pytest.raises(ValueError, match="a__p2"):
        launch.stage_b_totals(2, [(bad, 5)], smoke_n=0)


def test_preflight_refuses_a_seat_label_containing_the_id_delimiter(
    monkeypatch, capsys
):
    """`a__p2` would parse as (item a, seat p2) — or as a probe-2 id segment —
    so the run must refuse before any request id is minted."""
    monkeypatch.setattr(config, "TARGET_PANEL", [
        Seat("a__p2", "claude-opus-4-8", "high", 8000)])

    def _no_client():
        raise AssertionError("preflight built a client before checking labels")

    monkeypatch.setattr(launch, "client", _no_client)
    assert launch.preflight() is False
    assert "a__p2" in capsys.readouterr().err


def test_preflight_refuses_a_reserved_seat_label(monkeypatch, capsys):
    """A seat labelled `variant` makes `{rid}__variant` both an item's rewrite
    request and that seat's id prefix: one id, two meanings."""
    monkeypatch.setattr(config, "JUDGE_PANEL", [
        Seat("variant", "claude-opus-4-8", "high", 8000)])

    def _no_client():
        raise AssertionError("preflight built a client before checking labels")

    monkeypatch.setattr(launch, "client", _no_client)
    assert launch.preflight() is False
    assert "'variant' is a reserved id segment" in capsys.readouterr().err


def test_clean_seat_labels_pass_the_guard():
    """The shipped labels — and any label without `__` that is not a reserved
    segment — produce no findings."""
    shipped = [seat.label for seat in (
        *config.TARGET_PANEL, *config.JUDGE_PANEL,
        config.THERMOMETER_SEAT, config.OPUS5_SMOKE_SEAT)]
    assert launch.seat_label_problems(shipped) == []
    assert launch.seat_label_problems(["muse", "grok", "opus48"]) == []


@pytest.mark.usefixtures("_empty_evalaware_panel")
def test_preflight_skips_anthropic_entirely_when_nothing_routes_there(monkeypatch):
    """No Anthropic seat means no Anthropic credential is required."""
    flash = "deepseek/deepseek-v4-flash-0731"
    seat = Seat("f", flash, "medium", 8000)
    monkeypatch.setattr(config, "GENERATOR_MODEL", flash)
    monkeypatch.setattr(config, "VALIDITY_PANEL", [seat] * 3)
    monkeypatch.setattr(config, "TARGET_PANEL", [seat])
    monkeypatch.setattr(config, "JUDGE_PANEL", [seat])
    monkeypatch.setattr(config, "THERMOMETER_SEAT", seat)
    monkeypatch.setattr(config, "VARIANT_MODEL", flash)
    monkeypatch.setattr(config, "SEEDGEN_MODEL", flash)
    monkeypatch.setattr(config, "CHEAP_AUDIT_MODEL", flash)
    monkeypatch.setattr(config, "OPUS5_SMOKE_N", 0)  # else its seat pulls opus-5 in
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")

    def _no_client():
        raise AssertionError("preflight demanded Anthropic creds with no Anthropic seat")

    monkeypatch.setattr(launch, "client", _no_client)
    assert launch.preflight() is True


def test_preflight_refuses_a_target_labeled_like_the_smoke_seat(
    monkeypatch, capsys
):
    """A roster seat labeled `opus5` and the smoke seat mint the same wave-1
    ids (`{rid}__opus5_0`) on two DIFFERENT models: the cache clobbers one,
    both are billed, and the response column silently merges two seats. The
    target panel and the smoke seat share one id space, so preflight refuses
    the duplicate before a client exists (ticket 08 review, finding 2)."""
    smoke = config.OPUS5_SMOKE_SEAT
    monkeypatch.setattr(config, "OPUS5_SMOKE_N", 10)
    monkeypatch.setattr(config, "TARGET_PANEL", [
        Seat(smoke.label, "meta/muse-spark-1.2", "high", 8000)])

    def _no_client():
        raise AssertionError("preflight built a client before checking labels")

    monkeypatch.setattr(launch, "client", _no_client)
    assert launch.preflight() is False
    assert smoke.label in capsys.readouterr().err
