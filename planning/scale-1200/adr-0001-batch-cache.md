# Batch cache instead of a resume state machine

**Status:** accepted; implemented 2026-08-12 in `mask_off/batchcache.py`

Scaling to 1200 items means runs that span days and many invocations, so an
interrupted run must resume without re-billing work the provider already
completed. The obvious approach is a resume state machine: persist each seed's
phase, iteration, feedback, and locked fields, then reconstruct that state on
restart. We are instead putting a **request-level cache** in front of
`run_batch_retry`, keyed by `sha256(custom_id + canonical params)`, with batch
ids journalled to disk *before* polling begins so an orphaned batch can be
drained into the cache on resume. Resume then simply re-runs the cohort from the
top, and every request that already completed is a cache hit.

## Considered options

**Resume state machine.** Persist per-seed state and reconstruct it. This is the
conventional answer, and it is what a future reader will expect to find. It has
to be written once per stage — generation, validity, evaluation, seed authoring
— and each one has different state. Worse, it does not solve the actual money
problem: a batch submitted but never fetched is billed regardless of how well we
remembered which seed was on iteration three.

**Batch cache (chosen).** One module, two functions, serving all four stages. It
solves orphaned batches directly, which is the largest single loss at scale, and
resumability falls out as a side effect rather than being engineered separately.

## Consequences

- **Correctness depends on request determinism.** Replay only works because the
  same cohort regenerates identical request params. Anything non-deterministic in
  request construction — a timestamp in a prompt, an unsorted dict — silently
  turns every hit into a miss and re-bills the run. Request builders must stay
  deterministic, and this is not enforced by a type.
- **The cache stores a normalised four-field view, not an SDK `Message`.** Only
  `text_of`, `reasoning_summary_of`, `usage_summary_of`, and `.stop_reason` are
  valid on a rehydrated result. This is what lets the Anthropic and OpenRouter
  paths share one store, and it will bite the day something needs a real
  `Message`.
- **Re-running a cohort is cheap but not free.** Cache lookups, JSONL parsing,
  and re-execution of local logic all still happen. At 1200 items this is
  seconds, not minutes, but it is not zero.
- **There is deliberately no per-seed state on disk.** A future reader looking
  for it will not find it, and should not add it.
