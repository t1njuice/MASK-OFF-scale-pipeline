"""Per-model per-route cost accounting (ADR-0002 §9/F4).

Usage dicts follow convention U: `input_tokens` excludes cached tokens on
every route, `cached_in` is the rate cache-read tokens bill at, and
`cache_write` applies only where the provider bills cache writes. `model` is
mandatory in every usage dict; `route` is optional and inferred from the model
when absent (claude-* runs the native batch route, everything else runs
OpenRouter sync — the two routes that exist before the openai_batch adapter).
"""

from . import config

_warned: set = set()


def configured_models() -> list[str]:
    """Every model a run can reach from a panel, seat or model setting.

    Read from config at call time, not at import, so a test that patches a
    setting sees its change. Every panel is enumerated seat by seat, so growing
    a roster or adding a judge extends this set without touching this function
    — which is the whole reason preflight can promise that no configured model
    runs at an unpinned price.
    """
    panels = (config.VALIDITY_PANEL, config.TARGET_PANEL, config.JUDGE_PANEL)
    return [
        config.GENERATOR_MODEL,
        *(seat.model for panel in panels for seat in panel),
        config.THERMOMETER_SEAT.model,
        config.VARIANT_MODEL,
        config.SEEDGEN_MODEL,
        config.CHEAP_AUDIT_MODEL,
        *([config.OPUS5_SMOKE_SEAT.model] if config.OPUS5_SMOKE_N else []),
    ]


def reachable_routes(model: str) -> set[str]:
    """Every route one model can actually be served on.

    Both latency classes, because Stage A runs at "wave" and Stage B at "day"
    and a model can route differently at each. `openai_flex` drags
    `openai_sync` in with it: the flex adapter falls back to standard after a
    capacity 429, and a fallback is billed at standard rates.
    """
    from . import routes as route_registry

    routes = {route_registry.route(model, latency) for latency in ("wave", "day")}
    if "openai_flex" in routes:
        routes.add("openai_sync")
    return routes


def unpinned() -> list[tuple[str, str]]:
    """Sorted (model, route) pairs a run can reach that config.PRICES misses.

    An unpinned pair costs 0.0 in every report, so `--max-cost` cannot see it
    and a whole panel seat can run at an apparently free price. Preflight
    refuses on a non-empty result — a warning printed after the money is spent
    is not a check.
    """
    return sorted(
        (model, route)
        for model in set(configured_models())
        for route in reachable_routes(model)
        if (model, route) not in config.PRICES
    )


def route_of(usage: dict) -> str:
    """The route that served this usage record.

    Every record produced since ticket 05 carries it: the adapter stamps the
    route it served before any result hook sees the message, so a flex request
    that fell back to standard reports `openai_sync` and is billed at standard
    rates.

    The prefix guess below is the legacy path, for run logs and `_results.jsonl`
    rows written before the route field existed. It is wrong for anything that
    ran on flex or on a native OpenAI batch, which is exactly why new records
    do not use it. Do not extend it.
    """
    if usage.get("route"):
        return usage["route"]
    model = usage.get("model") or ""
    guess = "anthropic_batch" if model.startswith("claude") else "openrouter_sync"
    if ("legacy", model) not in _warned:
        _warned.add(("legacy", model))
        print(f"[pricing] {model!r} usage carries no route; guessing {guess!r} "
              f"from the model prefix. Records written before the route field "
              f"existed price wrong if they ran on flex or a native batch.")
    return guess


def usage_cost(usage: dict) -> float:
    """Dollars for one usage dict; 0.0 with a one-time warning when the
    (model, route) pair is not pinned in config.PRICES."""
    model = usage.get("model")
    route = route_of(usage)
    rates = config.PRICES.get((model, route))
    if rates is None:
        if (model, route) not in _warned:
            _warned.add((model, route))
            print(f"[pricing] no pinned price for {model!r} on {route!r}; "
                  f"its usage costs 0 in every report until pinned in config.PRICES")
        return 0.0
    return (
        usage.get("input_tokens", 0) * rates["in"]
        + usage.get("output_tokens", 0) * rates["out"]
        + usage.get("cache_creation_input_tokens", 0)
        * rates.get("cache_write", rates["in"])
        + usage.get("cache_read_input_tokens", 0) * rates["cached_in"]
    ) / 1e6
