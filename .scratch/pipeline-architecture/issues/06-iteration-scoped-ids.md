# 06 — Iteration-scoped custom ids

**What to build:** request identifiers that name the wave they belong to, so two
waves of the same seed can be in flight at once without their results colliding.
Behaviour is unchanged; this is the prefactor that makes ticket 10 possible.

**Blocked by:** 03.

**Status:** ready-for-agent

## Why

A Stage A request is identified today by the seed alone, and a panel vote by the
seed plus the vote slot. Nothing names the wave. That is safe only because the
current loop advances every seed in lockstep, so exactly one wave exists at a
time.

Ticket 10 removes that guarantee. Once a seed can be on wave 2 while a sibling
is on wave 1, results keyed by seed alone overwrite each other, and the failure
is silent: the wrong candidate gets judged.

Doing this separately keeps it landable. It touches the batch cache key, and a
cache-key change deserves its own review rather than riding inside a scheduler
rewrite.

## What to build

- Every Stage A custom id carries the wave it belongs to: the generator request,
  the lint regeneration, and each panel vote.
- The results of one wave cannot be read as the results of another.
- The cache-key consequence is stated in the map: the key is a hash of the
  custom id plus the canonical parameters, so this change makes every Stage A
  request a cache miss exactly once. Existing run directories replay from the
  top and re-bill their Stage A work.

## Warnings

That last point is the whole risk of this ticket. Confirm with the user before
landing it if any live run directory matters. A drill directory is fine to
sacrifice; a partially complete 300-item run is not.

The lint regeneration already uses a distinct identifier so the cache cannot
serve a linted draft back as its own replacement. Keep that property.

Do not change the resubmission identifiers to make them unique per attempt.
Resubmission deliberately reuses the identifier and passes a refresh set, so the
stale cached row is superseded rather than accumulated.

## Acceptance criteria

- [ ] Every Stage A request identifier contains the wave number.
- [ ] A test proves two waves of one seed produce disjoint identifiers.
- [ ] A test proves the resubmission path still supersedes a cached
      unparseable vote rather than creating a second row.
- [ ] Behaviour under the current lockstep loop is unchanged: a smoke run
      accepts the same items it accepted before.
- [ ] The cache-invalidation consequence is recorded in the map, and the user
      has confirmed no live run directory is harmed.
- [ ] `uv run python -m pytest mask_off -q` passes.
