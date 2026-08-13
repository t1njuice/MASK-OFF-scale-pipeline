# 11 — Cost ledger

**What to build:** one module that answers every cost question about a run, so
the total printed when a run ends and the total in the metrics report cannot
disagree.

**Blocked by:** 03.

**Status:** ready-for-agent

## Why

Cost is counted in five places. The Stage A loop accumulates a running total in
a local variable; the evaluation stage does the same; the scale driver
re-derives the total from the run log with a deduplication key; the metrics
report derives it a fourth time; and the deleted cost report used a different
price table entirely.

The deduplication key is real, hard-won logic. It exists because the run log is
append-only and a replayed cohort re-logs every wave it already ran, carrying
the usage of the rehydrated cached message. That work was billed once. Counting
it twice inflates the projection and stops the cost ceiling early. That logic
lives in exactly one of the five places.

So the printed total and the reported total already disagree whenever a run is
resumed.

## What to build

- One ledger module reading the run log and answering: total, per stage, per
  model, per route.
- The deduplication rule stated once, inside it.
- The in-loop accumulators replaced by calls into it.
- The cost ceiling and the metrics report both sourced from it.

## Warnings

Deduplication must survive the wave scheduler. Its key today assumes a seed and
a wave identify a stage's spend uniquely. Ticket 10 lets several waves be in
flight; check the key still holds, and if ticket 10 has already landed, test
against a replayed run that had concurrent waves.

Do not change what anything costs. This ticket moves the counting, not the
prices. A run replayed before and after must report the same total.

An unpinned model still costs zero. Ticket 04 owns making that a preflight
failure; do not duplicate the check here.

## Acceptance criteria

- [ ] One module answers every cost question; no module keeps its own running
      total.
- [ ] The total printed at the end of a run and the total in the metrics report
      are the same number, including after a resume.
- [ ] A replayed run is not double-counted, covered by a test using a log with
      duplicate waves.
- [ ] Cost is reportable per stage, per model and per route.
- [ ] The reported total for the run logs in `docs/evidence/` is unchanged from
      today's figures.
- [ ] `uv run python -m pytest mask_off -q` passes.
