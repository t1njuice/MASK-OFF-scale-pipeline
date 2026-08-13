# 10 — Wave scheduler

**What to build:** a Stage A loop where seeds advance independently. One seed
can be on wave 2 while another is still on wave 1, and a batch is in flight for
each stage at once rather than one batch at a time for the whole cohort.

**Blocked by:** 06, 09.

**Status:** ready-for-agent

## Why

One wave of the current loop issues up to six strictly sequential batch
round-trips for the whole cohort: generator, lint regeneration, panel votes, and
up to three vote resubmissions. Each is a full provider turnaround. The lint
barrier is the sharpest: a candidate that lints clean cannot start its panel
round until every dirty candidate has been regenerated, though it needs nothing
from that call.

Measured on p6, a wave costs 26 to 72 minutes whether 19 seeds or 5 seeds are in
it. Turnaround is set by the provider queue, not by the payload. That is what
makes this trade pay: splitting the cohort into smaller batches costs no extra
wall time.

## What to build

- A scheduler owning seed state, answering two questions: which requests should
  go out now, and how results change the state.
- Each stage submits a batch when it has work waiting and has no batch already
  in flight. Several stages therefore run concurrently, each carrying whichever
  seeds happen to be at that stage.
- No timer and no gathering window. Because a batch takes tens of minutes to
  return, seeds accumulate behind the one in flight and the next submission
  sweeps up everything that arrived meanwhile. The stage batches itself.

## Warnings

This is the largest ticket in the effort. If it does not fit one context window,
stop and split it rather than rushing the second half.

The accept, revise and exhaust policy must come out of the loop body as pure
state transitions. The real defects in this loop are ordering defects: which
seed advanced, which feedback was attached, whether the direction ruling carried
forward. Today those can only be observed by running a paid wave. After this
ticket they must be unit-testable.

Every durability property survives unchanged: the batch cache, the journal
written before polling, the drain at process start, the lock file, and the
replay-from-top resume. A scheduler that loses a paid batch is a worse pipeline
than a barrier that keeps it.

Cost accounting must not double-count when several waves are in flight. Ticket
11 owns the ledger; if it has not landed, keep the existing accumulator correct
rather than improving it here.

## Acceptance criteria

- [ ] Seeds advance independently: a test proves a clean candidate reaches the
      panel while a sibling is still regenerating.
- [ ] More than one stage can have a batch in flight at the same time.
- [ ] A stage never submits a second batch while its first is in flight.
- [ ] The accept, revise and exhaust policy is tested as state transitions, with
      no network and no monkeypatching of the batch runner.
- [ ] An interrupted run still resumes with no re-billing: kill the process
      mid-poll, restart, and confirm the drain folds the orphaned results into
      the cache and the replay reports hits rather than misses.
- [ ] A smoke run over at least 3 seeds accepts the same items the lockstep loop
      accepted.
- [ ] `uv run python -m pytest mask_off -q` passes.
