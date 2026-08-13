# 05 — Transport seam

**What to build:** one place that answers "how does this request reach a
model". A caller hands over a list of requests and gets back results, without
knowing that model families, providers or batch endpoints exist.

**Blocked by:** 03.

**Status:** ready-for-agent

## Why

Route is a first-class term in `CONTEXT.md`, but no module owns it. The decision
is re-derived in four places that must agree and can silently drift: the price
comparison in the batch-provider module decides it; `llm.run_batch` re-splits
the request list by hand into flex, other-external and native; the batch cache
contains a near-identical split; and the pricing module guesses it again from
the model prefix when a usage record lacks the field.

Adding target models 3 through 13 means editing a partitioning branch rather
than a table. That is the property ticket 07 needs and cannot get today.

## What to build

- One dispatch entry point taking requests, a label, a progress display, the
  journal hooks and the latency class, and returning results keyed by custom id.
- One registry mapping a route name to its adapter. Four adapters exist in fact
  today: the Anthropic batch, the OpenAI batch, OpenAI flex, and OpenRouter
  synchronous. The seam is real, not hypothetical.
- The route decision made once, in the registry, from the pinned prices and the
  latency class — never from which lab owns the model.
- Both existing split sites replaced by a call to dispatch.
- Route recorded on the usage record by the adapter that served the request, so
  the pricing module reads it rather than guessing. A flex request that falls
  back to standard must be priced as standard.

## Warnings

The latency class rule from ADR-0002 holds and must survive: a 24-hour window
route is never eligible inside a wave. Flex is eligible at both classes because
it carries batch rates on a synchronous call.

The journal hooks are load-bearing. Batch routes write their handle to the
journal before polling so an orphan survives process death. Dispatch must not
flatten that away — a synchronous adapter has no handle to journal, a batch
adapter does, and the registry has to carry that difference.

The route override escape hatch must keep working. It exists so a Stage B
fan-out too large for the synchronous rate ceiling can be forced onto a batch.

## Acceptance criteria

- [ ] One dispatch function is the only way a request reaches a provider.
- [ ] `llm.run_batch` and the batch cache no longer each partition by model
      family or route.
- [ ] The pricing module never infers a route from a model prefix; every usage
      record carries the route that actually served it.
- [ ] A single fake adapter, registered in the registry, exercises every caller
      in tests.
- [ ] A flex request that falls back to standard is priced at standard rates,
      covered by a test.
- [ ] Adding a model to a roster requires no change outside the configuration
      tables. Demonstrate with one model added and removed.
- [ ] `uv run python -m pytest mask_off -q` passes.
