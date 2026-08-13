# Map: pipeline-architecture

Label: wayfinder:map

## Destination

A lean `mask_off` package on a clean trunk, where the cost of a scale run is set
by a measured stop rule rather than a hand-edited cap, the wall time is not set
by a cohort barrier, and adding a model is a table edit. The 13-model target
roster and the two-model final judge run without touching pipeline code.

## Why this effort exists

Two measurements from the 2026-08-13 architecture review:

- **Cost is output tokens, not prompts.** Over `frozen_19` (186 usage blocks):
  2,517,397 output tokens = $31.47, against 736,419 input tokens = $1.84.
  Output is 89% of the bill. Only the number of rounds bought moves it.
- **Half the spend bought nothing.** In p6 (19 seeds, cap 10): 51 of 103 rounds
  went to the 5 seeds that never accepted, and those same 5 seeds are the
  1 h 31 m tail after the last acceptance. Cost sink and clock tail are the
  same seeds.

The 1h prompt cache was checked and is NOT a problem: 6.59 cache reads per
write, $2.91 against $8.29 uncached. Do not spend a ticket there.

## Context-rot rules for this effort

1. **The working tree is the context budget.** Ticket 01 cuts 4,199 tracked
   files to roughly 250. Every later ticket assumes it landed.
2. **Evidence lives in `docs/evidence/`.** No ticket needs the results tree.
3. **One ticket = one fresh context window = one verification command.** The
   command is `uv run python -m pytest mask_off -q`. Baseline: 79 passed.
4. **This map is the shared memory.** Record every closed ticket below in one
   line, so the next agent does not re-derive what the last one settled.

## Notes

- Domain vocabulary is fixed by `CONTEXT.md` (seed, item, cohort, wave, quota,
  route, cell, batch cache, config fingerprint). Panel and Seat are new terms
  introduced by ticket 07 and must be added to `CONTEXT.md` there.
- Settled decisions live in `planning/scale-1200/` (ADR-0001 batch cache,
  ADR-0002 native batch adapters, design.md). Do not re-litigate them. Ticket
  12 is the only one that touches an ADR invariant, and it says so.
- The locked gate configuration is kimi-k3 + grok-4.5 + gpt-5.6-sol, 2-of-3,
  sol on flex with standard-sync fallback, generator opus-4.8 on
  anthropic_batch. See `.scratch/gate-config-lock/map.md`.
- The direction-lock fix for inference-distance oscillation landed 2026-08-13
  and is UNVALIDATED. Every cap number measured before it is stale. This is why
  ticket 09 instruments rather than picks a new cap.
- Standing user rules: never discard batch work (harvest before any
  cancel/resubmit); run reports end with the output artifact paths; define
  jargon before use; prize minimal diffs.
- The clean branch becomes the new trunk (user decision, 2026-08-13). `docs/`
  survives whole.

## Decisions so far

<!-- one line per closed ticket -->

## Not yet specified

- Where the iteration cap belongs after the direction-lock fix. Ticket 09
  produces the instrumentation; the next pilot produces the number.
- Which 13 models fill the target roster. Ticket 07 makes the roster a list;
  it does not choose the entries.
- Whether `test_seed_diversity.py` is a real regression or a stale fixture. It
  errors at collection today. Ticket 01 records it; nobody has diagnosed it.

## Out of scope

- Prompt content. `mask_off/prompts/*` is frozen; no ticket edits it.
- Choosing a new cap value, judge model, or panel member. This effort changes
  the mechanisms, not the settings.
- Rewriting the batch cache or the journal. ADR-0001 and ADR-0002 hold.
