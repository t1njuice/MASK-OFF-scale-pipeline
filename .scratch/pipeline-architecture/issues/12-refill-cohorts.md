# 12 — Refill cohorts

**What to build:** a Stage A run that keeps a target number of seeds in flight
and tops the pool up as seeds finish, so a cohort goes back to being what the
glossary says it is — a checkpoint where state is written and metrics are
recorded, not a scheduling barrier.

**Blocked by:** 10, 08.

**Status:** ready-for-agent

## Why

`CONTEXT.md` defines a cohort as existing "for durability and reporting, not for
any modelling reason". The scale driver blocks on each cohort, so a cohort is
also a hard barrier. Cohort N+1's first seed cannot start until cohort N's last
straggler finishes, and by then the batch carries 5 requests at the same
turnaround it had at 200.

At 1,200 items that is six sequential cohorts, each ending in a long thin tail.

## Interacts with settled design — read this first

ADR-0001 and the pending-cohort contract assume one cohort is in flight at a
time: a pending cohort always finishes, even past the cost ceiling, so no paid
batch is stranded. A refill scheduler needs that invariant restated over a set
of in-flight seeds rather than over a cohort.

That is why this ticket is last. Tickets 09 and 10 shorten the tail without
touching the resume contract at all. Land them, measure what tail remains, and
only then decide whether this ticket is still worth its risk. Bring the restated
invariant to the user before implementing it.

## What to build

- A target number of seeds in flight, topped up as seeds finish.
- Cohort boundaries reduced to checkpoints: state written, cohort metrics
  recorded, yield updated.
- The resume contract restated over in-flight seeds, with the no-stranded-batch
  guarantee preserved and written into the map.
- The cost ceiling still checked at a boundary where stopping strands nothing.

## Warnings

Never discard batch work. Any design that abandons an in-flight seed to hit a
ceiling is wrong; the ceiling must wait for a safe point.

The stratified draw and the per-domain quota must keep working. Refilling one
seed at a time is not the same as drawing a stratified cohort, and a naive refill
can starve a domain whose gate is harsh — the exact failure the quota exists to
prevent.

The yield figure that sizes the next draw is currently computed per cohort. With
continuous refill there is no cohort to compute it over. Decide what replaces it
before changing the draw.

## Acceptance criteria

- [ ] A target number of seeds stays in flight; a finished seed is replaced
      without waiting for its neighbours.
- [ ] Per-domain quota behaviour is unchanged, covered by a test that starves a
      domain under the old code and does not under the new.
- [ ] The no-stranded-batch guarantee is restated in the map and holds: an
      interrupted run resumes with no re-billing.
- [ ] The cost ceiling stops the run only at a point where nothing is stranded.
- [ ] The replacement for per-cohort yield is agreed with the user and recorded.
- [ ] A drill run over at least 3 seeds survives a kill mid-poll and replays as
      cache hits.
- [ ] `uv run python -m pytest mask_off -q` passes.
