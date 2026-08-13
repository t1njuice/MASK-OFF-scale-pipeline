# 08 — Per-route concurrency

**What to build:** concurrency that belongs to the route rather than to a
literal written twice. Stage B stops being gated by a number nobody chose for
it.

**Blocked by:** 05 — the route registry is where concurrency belongs.

**Status:** ready-for-agent

## Why

Both synchronous fan-outs run eight threads, written as a literal in two files.
Nothing relates that number to any provider's rate limit. The flex tier was
measured at 1M tokens per minute and 5,000 requests per minute, and the code
gives it the same 8 it gives OpenRouter.

At two target models this is invisible. At the 13-model roster it becomes the
dominant term in the Stage B wall time. For 300 items at K=3, with roughly 9 of
13 models on a synchronous route, the non-Anthropic share is about 8,100 cells.
At 8 threads that is roughly 25 hours. The Anthropic share is unaffected because
a batch is parallel server-side.

## What to build

- Concurrency as a property of a route in the registry, beside its prices.
- A separate limit per route, so a generous provider is not throttled to match a
  strict one.
- The batch polls interleaved rather than sequential. A Stage B fan-out across
  many models polls them one after another today; the code carries a note saying
  this only costs the tail, and the 13-model roster is what turns that tail into
  a real cost.
- The alternative lever documented in the map: Stage B is latency class "day",
  so the OpenAI share can be forced onto a batch route instead, trading a
  24-hour window for half the price and no rate ceiling. Both levers should be
  available; the ticket does not choose between them.

## Warnings

Raising concurrency raises the rate of 429 responses. The flex adapter already
treats an unavailable-resource 429 as a capacity signal, retries with backoff
and falls back to standard. Confirm that path still holds under real
concurrency before raising any limit, because a fallback is billed at standard
rates and a silent stampede of fallbacks doubles the price of the stage.

Measure before choosing a number. A limit picked from a documentation page and a
limit picked from a measurement are not the same quality of evidence, and this
ticket exists precisely because the last number was picked without one.

## Acceptance criteria

- [ ] No `max_workers` literal remains in the package.
- [ ] Each route carries its own concurrency limit in the registry.
- [ ] Batch polls across several models interleave rather than run in sequence.
- [ ] A measured throughput figure for at least one synchronous route is
      recorded in the map, with the sample size it came from.
- [ ] A rate-limited response still retries, falls back and is priced at the
      tier that actually served it, covered by a test.
- [ ] `uv run python -m pytest mask_off -q` passes.
