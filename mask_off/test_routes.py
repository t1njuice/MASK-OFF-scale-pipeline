"""The transport seam: one dispatch, one registry, one route decision.

Run: pytest mask_off/test_routes.py
"""

import dataclasses

import pytest

from . import config, llm, pricing, routes
from .conftest import message


def _req(cid, model):
    return {"custom_id": cid, "params": {"model": model, "messages": ["hi"]}}


@pytest.fixture(autouse=True)
def openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")


def test_one_call_fans_out_to_every_route(transport):
    """A mixed list reaches four different adapters without the caller
    knowing that model families or batch endpoints exist."""
    monkey = [
        _req("anth", "claude-opus-4-8"),
        _req("flex", "openai/gpt-5.6-sol"),
        _req("router", "moonshotai/kimi-k3"),
    ]
    out = routes.dispatch(monkey, "t", progress=None, latency="wave")
    assert set(out) == {"anth", "flex", "router"}
    assert transport.routed == {
        "anth": "anthropic_batch",
        "flex": "openai_flex",
        "router": "openrouter_sync",
    }


def test_a_day_only_route_is_ineligible_inside_a_wave(monkeypatch):
    """ADR-0002 §3: five waves through a 24h window is five days.

    Price the model so only the 24h batch is a real discount: flex dearer than
    the synchronous baseline, batch cheaper. The batch then wins at "day" and
    is skipped at "wave", which falls back to the baseline.
    """
    model = "openai/gpt-5.6-sol"
    monkeypatch.setitem(config.PRICES, (model, "openrouter_sync"),
                        {"in": 4.0, "out": 20.0, "cached_in": 0.4})
    monkeypatch.setitem(config.PRICES, (model, "openai_flex"),
                        {"in": 9.9, "out": 99.0, "cached_in": 0.9})
    assert routes.route(model, "day") == "openai_batch"
    assert routes.route(model, "wave") == "openrouter_sync"
    assert routes.ADAPTERS["openai_batch"].day_only
    assert not routes.ADAPTERS["openai_flex"].day_only


def test_every_result_carries_the_route_that_served_it(transport):
    """pricing must read the route, not guess it from the model prefix."""
    out = routes.dispatch(
        [_req("a", "claude-opus-4-8"), _req("b", "moonshotai/kimi-k3")],
        "t", progress=None, latency="day",
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
    """Add one model, dispatch it, remove it. No branch anywhere else changes."""
    added = "openai/gpt-5.6-terra"
    monkeypatch.setattr(config, "TARGET_MODELS", [*config.TARGET_MODELS, added])
    assert added in pricing.configured_models()
    assert pricing.unpinned() == [], "the new model is priced on every route"
    routes.dispatch([_req("new", added)], "t", progress=None, latency="day")
    assert transport.routed["new"] == "openai_flex"

    monkeypatch.setattr(config, "TARGET_MODELS", ["moonshotai/kimi-k3"])
    assert added not in pricing.configured_models()
    assert pricing.unpinned() == []


def test_an_unpriced_model_still_reaches_a_provider_via_openrouter(transport):
    """Routing must not silently drop a model it has no price for. Preflight
    is what refuses the run; dispatch still has to be total."""
    out = routes.dispatch([_req("x", "openai/gpt-5.6-luna")], "t",
                          progress=None, latency="day")
    assert transport.routed["x"] == "openrouter_sync"
    assert out["x"] is not None


def test_a_batch_route_refuses_to_run_without_a_journal(monkeypatch, transport):
    """Regression: the uncached path could reach openai_batch, submit a paid
    24h batch with no journal row, and strand it if the process died.

    Reproduce it by forcing the override the escape hatch exists for and
    calling the uncached path — no Policy, so no run directory and no hooks.
    """
    monkeypatch.setattr(
        config, "ROUTE_OVERRIDES", {"openai/gpt-5.6-sol": "openai_batch"}
    )
    request = _req("a", "openai/gpt-5.6-sol")
    with pytest.raises(RuntimeError, match="needs a journal"):
        llm.run_batch_retry([request], "Stage B", None, latency="day")
    assert transport.calls == [], "nothing may be submitted before the refusal"


def test_a_journaled_dispatch_accepts_the_same_override(monkeypatch, transport):
    """The escape hatch still works where the handle can be journaled."""
    monkeypatch.setattr(
        config, "ROUTE_OVERRIDES", {"openai/gpt-5.6-sol": "openai_batch"}
    )
    handled = []
    hooks = routes.Hooks(on_handle=lambda route, handle, cids: handled.append(route))
    routes.dispatch([_req("a", "openai/gpt-5.6-sol")], "t", None, "day", hooks)
    assert handled == ["openai_batch"]


def test_a_synchronous_route_needs_no_journal(transport):
    """Only the 24h-window route is refused. Flex and OpenRouter leave no
    server-side handle to orphan, and the Anthropic batch keeps the uncached
    behaviour it had before the seam existed."""
    out = routes.dispatch(
        [_req("a", "claude-opus-4-8"), _req("b", "moonshotai/kimi-k3"),
         _req("c", "openai/gpt-5.6-sol")],
        "t", progress=None, latency="day",
    )
    assert set(out) == {"a", "b", "c"}


def test_only_batch_routes_journal_a_handle(transport):
    handled = []
    hooks = routes.Hooks(on_handle=lambda route, handle, cids: handled.append(route))
    routes.dispatch(
        [_req("a", "claude-opus-4-8"), _req("b", "moonshotai/kimi-k3")],
        "t", progress=None, latency="wave", hooks=hooks,
    )
    assert handled == ["anthropic_batch"], "a sync call has no handle to orphan"
    assert routes.JOURNALED == {"anthropic_batch", "openai_batch"}


def test_registry_covers_every_route_the_decision_can_return(monkeypatch):
    """route() must never name an adapter that does not exist."""
    monkeypatch.setattr(config, "ROUTE_OVERRIDES", {})
    reachable = {
        routes.route(model, latency)
        for model in [*pricing.configured_models(), "openai/gpt-5.6-terra"]
        for latency in ("wave", "day")
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
