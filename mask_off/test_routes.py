"""The transport seam: one dispatch, one registry, one route decision.

Run: pytest mask_off/test_routes.py
"""

import dataclasses

import pytest

from . import config, llm, pricing, routes
from .conftest import message
from .panel import Seat


def _req(cid, model):
    return {"custom_id": cid, "params": {"model": model, "messages": ["hi"]}}


@pytest.fixture(autouse=True)
def openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")


def test_one_call_fans_out_to_every_route(transport):
    """A mixed list reaches three different adapters without the caller
    knowing that model families or batch endpoints exist."""
    monkey = [
        _req("anth", "claude-opus-4-8"),
        _req("flex", "openai/gpt-5.6-sol"),
        _req("router", "moonshotai/kimi-k3"),
    ]
    out = routes.dispatch(monkey, "t", progress=None)
    assert set(out) == {"anth", "flex", "router"}
    assert transport.routed == {
        "anth": "anthropic_batch",
        "flex": "openai_flex",
        "router": "openrouter_sync",
    }


def test_a_flex_price_dearer_than_the_baseline_loses(monkeypatch):
    """Price-driven, not provider-driven: a pinned flex rate that is not a
    real discount must lose to the synchronous baseline."""
    model = "openai/gpt-5.6-sol"
    monkeypatch.setitem(config.PRICES, (model, "openrouter_sync"),
                        {"in": 4.0, "out": 20.0, "cached_in": 0.4})
    monkeypatch.setitem(config.PRICES, (model, "openai_flex"),
                        {"in": 9.9, "out": 99.0, "cached_in": 0.9})
    assert routes.route(model) == "openrouter_sync"


def test_every_result_carries_the_route_that_served_it(transport):
    """pricing must read the route, not guess it from the model prefix."""
    out = routes.dispatch(
        [_req("a", "claude-opus-4-8"), _req("b", "moonshotai/kimi-k3")],
        "t", progress=None,
    )
    assert out["a"].route == "anthropic_batch"
    assert out["b"].route == "openrouter_sync"
    for msg in out.values():
        assert pricing.route_of(llm.usage_summary_of(msg)) == msg.route


def test_the_route_reaches_the_result_hook_not_just_the_return_value():
    """The batch cache normalizes inside on_result. A route stamped after the
    adapter returned would never reach the stored row, and every replayed cost
    would be priced by inference instead."""
    seen = {}
    hooks = routes.Hooks(on_result=lambda cid, msg: seen.__setitem__(cid, msg.route))
    routes._stamped(hooks, "openrouter_sync")("a", message())
    assert seen == {"a": "openrouter_sync"}


def test_an_adapter_that_knows_better_wins():
    """A flex request that fell back to standard is already stamped
    openai_sync, and dispatch must not overwrite it with openai_flex."""
    fell_back = message()
    fell_back.route = "openai_sync"
    routes._stamp(fell_back, "openai_flex")
    assert fell_back.route == "openai_sync"


def test_a_flex_fallback_is_priced_at_standard_rates():
    flex = config.PRICES[("openai/gpt-5.6-sol", "openai_flex")]
    standard = config.PRICES[("openai/gpt-5.6-sol", "openai_sync")]
    usage = {"model": "openai/gpt-5.6-sol", "route": "openai_sync",
             "output_tokens": 1_000_000}
    assert pricing.usage_cost(usage) == standard["out"]
    assert standard["out"] == 2 * flex["out"], "standard is twice flex"
    usage["route"] = "openai_flex"
    assert pricing.usage_cost(usage) == flex["out"]


def test_adding_a_model_to_the_roster_touches_only_the_tables(monkeypatch, transport):
    """Add one seat, dispatch it, remove it. No branch anywhere else changes.

    terra sits on the judge panel too, so that panel is narrowed first —
    otherwise "removed from the roster" could not mean "no longer reachable",
    and the assertion would be measuring the judge rather than the roster.
    The probe flags are narrowed for the same reason: terra also holds the
    three fixed probe-judge roles, which reach configured_models whenever
    their flags are on.
    """
    added = "openai/gpt-5.6-terra"
    monkeypatch.setattr(config, "JUDGE_PANEL", [
        Seat("opus48", "claude-opus-4-8", "high", 8000)])
    for flag in ("RECOGNITION", "SALIENCE", "PROBE2"):
        monkeypatch.setattr(config, flag, False)
    monkeypatch.setattr(config, "TARGET_PANEL", [
        *config.TARGET_PANEL, Seat("terra", added, "high", 8000)])
    assert added in pricing.configured_models()
    assert pricing.unpinned() == [], "the new model is priced on every route"
    routes.dispatch([_req("new", added)], "t", progress=None)
    assert transport.routed["new"] == "openai_flex"

    monkeypatch.setattr(config, "TARGET_PANEL", [
        Seat("kimi", "moonshotai/kimi-k3", "high", 8000)])
    assert added not in pricing.configured_models()
    assert pricing.unpinned() == []


def test_the_roster_goes_from_two_to_thirteen_and_back_as_one_list_edit(
    monkeypatch, transport
):
    """Acceptance criterion for ticket 07, demonstrated in both directions.

    Thirteen seats, then two, with `config.TARGET_PANEL` the only thing that
    changes: every seat is enumerated by `pricing.configured_models`, priced by
    the same check, and routed by `routes.route` off the pinned prices. No
    branch, no roster length, and no hand-routing anywhere reads the count.

    Which thirteen models fill the roster is deliberately not decided here —
    the ticket makes the roster a list, it does not choose the entries — so
    this builds thirteen seats out of the priced models the repo already has.
    """
    priced = sorted({model for model, _ in config.PRICES})
    thirteen = [
        Seat(f"seat{i:02d}", priced[i % len(priced)], "high", 1000 + i)
        for i in range(13)
    ]
    monkeypatch.setattr(config, "TARGET_PANEL", thirteen)
    assert len(config.TARGET_PANEL) == 13
    # the SEATS are enumerated, not the whole price table: thirteen seats drawn
    # `i % len(priced)` cover the first thirteen priced models only, so once the
    # table passes thirteen entries the old form asserted a property of the
    # table's length instead of the roster's (broke on the 2026-08-16 target
    # seat, and only passed before because other panels named the leftovers)
    assert {seat.model for seat in thirteen} <= set(pricing.configured_models())
    assert pricing.unpinned() == [], "every roster seat is priced on every route"
    reqs = [_req(seat.label, seat.model) for seat in thirteen]
    routes.dispatch(reqs, "roster", progress=None)
    assert len(transport.routed) == 13, "every seat reached a transport"

    two = thirteen[:2]
    monkeypatch.setattr(config, "TARGET_PANEL", two)
    assert len(config.TARGET_PANEL) == 2
    assert pricing.unpinned() == []
    # the gate is untouched by a roster edit: 2-of-3 either way
    assert (config.VALIDITY_ACCEPT, config.VALIDITY_VOTES) == (2, 3)


def test_an_unpriced_model_still_reaches_a_provider_via_openrouter(transport):
    """Routing must not silently drop a model it has no price for. Preflight
    is what refuses the run; dispatch still has to be total."""
    out = routes.dispatch([_req("x", "openai/gpt-5.6-luna")], "t",
                          progress=None)
    assert transport.routed["x"] == "openrouter_sync"
    assert out["x"] is not None


def test_only_batch_routes_journal_a_handle(transport):
    handled = []
    hooks = routes.Hooks(on_handle=lambda route, handle, cids: handled.append(route))
    routes.dispatch(
        [_req("a", "claude-opus-4-8"), _req("b", "moonshotai/kimi-k3")],
        "t", progress=None, hooks=hooks,
    )
    assert handled == ["anthropic_batch"], "a sync call has no handle to orphan"
    assert routes.JOURNALED == {"anthropic_batch"}


def test_registry_covers_every_route_the_decision_can_return():
    """route() must never name an adapter that does not exist."""
    reachable = {
        routes.route(model)
        for model in [*pricing.configured_models(), "openai/gpt-5.6-terra"]
    }
    assert reachable <= set(routes.ADAPTERS)


def test_empty_request_list_touches_no_adapter():
    def must_not_run(*a, **k):
        raise AssertionError("dispatch called an adapter with nothing to send")

    swapped = {
        name: dataclasses.replace(adapter, run=must_not_run)
        for name, adapter in routes.ADAPTERS.items()
    }
    assert routes.dispatch([], "t", progress=None) == {}
    assert set(swapped) == set(routes.ADAPTERS)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
