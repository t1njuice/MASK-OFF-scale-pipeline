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


def route_of(usage: dict) -> str:
    if usage.get("route"):
        return usage["route"]
    model = usage.get("model") or ""
    return "anthropic_batch" if model.startswith("claude") else "openrouter_sync"


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
