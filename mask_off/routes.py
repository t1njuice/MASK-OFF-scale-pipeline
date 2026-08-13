"""One place that answers "how does this request reach a model".

A caller hands `dispatch` a list of requests and gets back results keyed by
custom id, without knowing that model families, providers or batch endpoints
exist. Four adapters exist in fact, so the seam is real, not hypothetical:

| Route             | Transport                        | Journals a handle |
| ----------------- | -------------------------------- | ----------------- |
| `anthropic_batch` | Anthropic Message Batches        | yes               |
| `openai_batch`    | OpenAI Batch API, 24h window     | yes               |
| `openai_flex`     | OpenAI sync at Batch API rates   | no                |
| `openrouter_sync` | OpenRouter chat completions      | no                |

`route()` is the only place the decision is made. It reads the pinned prices
in `config.PRICES` and the latency class — never which lab owns the model. So
adding a model to a roster is a table edit, not a branch edit.

Latency class (ADR-0002 §3):

- `"wave"` is a sequential iteration turn, the Stage A generator and validity
  loop. A 24-hour-window route is never eligible: five waves through a 24h
  window is five days. That rule lives in `Adapter.day_only`.
- `"day"` is Stage B cells and seed authoring. Every route is eligible and
  the cheapest wins.

Flex is eligible at both classes because it carries Batch API rates on a
synchronous call.

Concurrency is a property of a route too (`Adapter.concurrency`), because two
providers do not share a rate limit and one shared literal throttled the
generous one to the strict one's ceiling. Only the synchronous adapters run a
thread pool; a batch adapter has no per-request fan-out to limit.

Every adapter stamps the route it served onto each message before the result
hooks see it, so `pricing` reads the route rather than guessing it from the
model prefix. A flex request that falls back to standard reports
`openai_sync`, because that is the tier that billed it.
"""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from rich.progress import Progress

from . import config


@dataclass(frozen=True)
class Hooks:
    """Durability callbacks a caller passes through dispatch.

    `on_handle(route, handle, custom_ids)` fires on a batch route after the
    provider accepts a submission and BEFORE polling begins, so a process
    death leaves an orphan that `drain_orphans` can re-poll. A synchronous
    adapter has no server-side handle to journal and never calls it. The
    OpenAI batch adapter calls it twice: once with `batch_id` None right after
    the input file uploads, then again with the real id, so a lost create
    response still leaves the billed batch findable (ADR-0002 §9/F6).

    `on_result(custom_id, msg)` fires as each result lands, before it appears
    in the return value.
    """

    on_result: Callable | None = None
    on_handle: Callable | None = None
    cancel_on_interrupt: bool = True


@dataclass(frozen=True)
class Adapter:
    name: str
    run: Callable
    # True -> the provider processes on a 24-hour window, so the route is
    # ineligible inside a wave (ADR-0002 §3).
    day_only: bool = False
    # How many requests this route may have in flight from this process. The
    # limit belongs to the route because providers do not share a rate limit:
    # throttling a generous one to match a strict one is what a single shared
    # literal did. None means no request pool exists on this route — a batch
    # adapter hands the whole group to the provider, which fans it out
    # server-side, so there is no number here to choose. Its polls are
    # interleaved instead (`batch_providers.poll_all_until_done`).
    concurrency: int | None = None


def _stamp(msg, route_name: str):
    """Record the route on a message, unless the adapter already knows better.

    The flex adapter sets `openai_sync` on a fallback, and that must win: the
    standard tier is what billed the request.
    """
    from .llm import _attach

    if msg is not None and getattr(msg, "route", None) is None:
        _attach(msg, "route", route_name)
    return msg


def _stamped(hooks: Hooks, route_name: str) -> Callable | None:
    """`hooks.on_result`, with the route stamped first.

    Stamping has to happen before the hook runs, not after the adapter
    returns: the batch cache's `on_result` normalizes the message straight
    into `_results.jsonl`, so a route stamped afterwards would never reach the
    stored row and every replayed cost would be priced by inference.
    """
    def on_result(custom_id: str, msg) -> None:
        _stamp(msg, route_name)
        if hooks.on_result is not None:
            hooks.on_result(custom_id, msg)

    return on_result


# --- adapters -------------------------------------------------------------


def _run_anthropic(requests, label, progress, hooks: Hooks) -> dict:
    from . import llm

    def on_submit(batch_id: str, custom_ids: list[str]) -> None:
        if hooks.on_handle is not None:
            hooks.on_handle("anthropic_batch", {"batch_id": batch_id}, custom_ids)

    return llm.run_anthropic_batch(
        requests, label, progress,
        on_submit=on_submit,
        on_result=_stamped(hooks, "anthropic_batch"),
        cancel_on_interrupt=hooks.cancel_on_interrupt,
    )


def _run_openai_batch(requests, label, progress, hooks: Hooks) -> dict:
    from . import batch_providers

    def on_submit(handle: dict, custom_ids: list[str]) -> None:
        if hooks.on_handle is not None:
            hooks.on_handle("openai_batch", handle, custom_ids)

    def on_upload(slug: str, file_id: str, custom_ids: list[str]) -> None:
        if hooks.on_handle is not None:
            hooks.on_handle(
                "openai_batch",
                {"batch_id": None, "input_file_id": file_id, "slug": slug},
                custom_ids,
            )

    return batch_providers.run_openai_batch(
        requests, label, progress, on_submit,
        _stamped(hooks, "openai_batch"), on_upload,
    )


def _run_openai_flex(requests, label, progress, hooks: Hooks) -> dict:
    from . import batch_providers

    return batch_providers.run_openai_flex(
        requests, label, progress, _stamped(hooks, "openai_flex")
    )


def _run_openrouter(requests, label, progress, hooks: Hooks) -> dict:
    from . import llm

    return llm.run_openrouter(
        requests, label, progress, _stamped(hooks, "openrouter_sync")
    )


ADAPTERS: dict[str, Adapter] = {
    "anthropic_batch": Adapter("anthropic_batch", _run_anthropic),
    "openai_batch": Adapter("openai_batch", _run_openai_batch, day_only=True),
    # UNMEASURED. Both numbers are the single literal 8 that used to sit in two
    # files, moved here and not yet replaced by evidence. The flex tier is
    # reported at 1M tokens and 5,000 requests per minute, far above 8
    # concurrent calls, so the ceiling that actually binds this pipeline is
    # unknown and 8 is a guess in either direction. Raising it on a guess is
    # the mistake this field exists to fix: a flex 429 falls back to standard,
    # which bills at twice the flex rate, so a stampede of fallbacks doubles
    # the price of the stage. Measure a route's throughput first — one
    # timed Stage B cohort at two limits, wall time and per-route error count
    # both recorded — then edit its number here and nowhere else.
    "openai_flex": Adapter("openai_flex", _run_openai_flex, concurrency=8),
    "openrouter_sync": Adapter("openrouter_sync", _run_openrouter, concurrency=8),
}

# Routes that write a handle to the journal before polling, so an orphan
# survives process death. Derived from the adapters that take on_handle.
JOURNALED = frozenset({"anthropic_batch", "openai_batch"})

# Preference order among the discounted OpenAI routes. Flex first at both
# latency classes: it carries Batch API rates on a synchronous call, and
# prompt caching stacks on top. Measured on a real gate vote 2026-08-13, flex
# 187s against standard 286s, 11,473 of 11,476 prompt tokens cached on a
# repeat call.
_OPENAI_PREFERENCE = ("openai_flex", "openai_batch")


def route(model: str, latency: str) -> str:
    """The route for one model at one latency class, from the pinned prices.

    `config.ROUTE_OVERRIDES[model]` forces a route and skips the comparison.
    The case it exists for: a Stage B fan-out large enough that flex would hit
    the synchronous tokens-per-minute ceiling belongs on `openai_batch`.
    """
    if model.startswith("claude"):
        return "anthropic_batch"
    override = config.ROUTE_OVERRIDES.get(model)
    if override:
        return override
    if not (model.startswith("openai/") and os.environ.get("OPENAI_API_KEY")):
        return "openrouter_sync"
    baseline = config.PRICES.get((model, "openrouter_sync"))
    for name in _OPENAI_PREFERENCE:
        if ADAPTERS[name].day_only and latency != "day":
            continue
        rates = config.PRICES.get((model, name))
        # price-driven, not provider-driven: the discount must be real
        if rates is not None and (baseline is None or rates["out"] < baseline["out"]):
            return name
    return "openrouter_sync"


def partition(requests: list[dict], latency: str) -> dict[str, list[dict]]:
    """{route name: requests}, in a stable order."""
    groups: dict[str, list[dict]] = {}
    for request in requests:
        groups.setdefault(route(request["params"]["model"], latency), []).append(request)
    return groups


def dispatch(
    requests: list[dict],
    label: str,
    progress: "Progress | None" = None,
    latency: str = "wave",
    hooks: Hooks | None = None,
) -> dict:
    """The only way a request reaches a provider. {custom_id: message | None}.

    None means the request errored, expired, or was canceled.
    """
    if not requests:
        return {}
    hooks = hooks or Hooks()
    if progress is None:
        from .llm import batch_progress

        with batch_progress() as owned:
            return dispatch(requests, label, owned, latency, hooks)

    groups = partition(requests, latency)
    # A 24-hour-window route hands back a handle and nothing else: the results
    # arrive hours later, in some later process. Submitting one with no
    # `on_handle` would pay for a batch that no journal records, and a process
    # death would then strand it with no way to harvest — the standing rule is
    # never to discard batch work. The pre-seam code enforced this by never
    # selecting a batch route outside the cache; say so out loud instead.
    if hooks.on_handle is None:
        orphanable = sorted(n for n in groups if ADAPTERS[n].day_only)
        if orphanable:
            raise RuntimeError(
                f"{orphanable} needs a journal and this dispatch has no "
                f"on_handle hook, so a paid batch would be unrecoverable if "
                f"this process died. Run under a run directory "
                f"(batchcache.policy(run_dir=...)), or drop the "
                f"config.ROUTE_OVERRIDES entry that forced the batch route."
            )

    out = {}
    # ponytail: route groups run one after another. Every batch route
    # processes server-side in parallel anyway, so this costs only the tail.
    # The tail that mattered was inside one group — a Stage B fan-out puts
    # every openai/* model on `openai_batch` at once — and that is now
    # interleaved by `batch_providers.poll_all_until_done`. Crossing route
    # groups too would need a shared progress display and thread-safe hooks;
    # measure that it costs something before paying for it.
    for name, group in sorted(groups.items()):
        results = ADAPTERS[name].run(group, label, progress, hooks)
        for msg in results.values():
            # Belt and braces: a message that never passed through on_result
            # still gets its route before the caller prices it.
            _stamp(msg, name)
        out.update(results)
    return out
