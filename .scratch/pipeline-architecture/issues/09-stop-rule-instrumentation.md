# 09 — Stop-rule seam and round instrumentation

**What to build:** a named decision point that answers "does this seed still
deserve money", and a run log that records enough per wave for that decision to
be fitted from data afterwards. This is the top recommendation of the review.

**Blocked by:** 03.

**Status:** ready-for-agent

## Why

A seed leaves the Stage A loop on exactly two conditions: the panel accepts it,
or it hits the iteration cap. There is no third condition, and nothing measures
whether the waves in between were worth buying.

The cap is also the largest term in the cost model. Measured on the p6 gate
pilot, 51 of 103 waves went to the 5 seeds that never accepted — half the spend,
producing nothing — and those same 5 seeds are the 1 hour 31 minute tail after
the last acceptance. The cost sink and the wall-clock tail are the same seeds.
The evidence is in `docs/evidence/`.

## Do not pick a new cap in this ticket

The direction-lock fix for inference-distance oscillation landed on 2026-08-13
and is unvalidated. It targets exactly the failure mode that produced those 5
cap-burners, so every cap number measured before it is stale. On the pre-fix
data a cap of 6 would have cost zero items and a cap of 5 would have lost 2 of
14 — a one-wave-wide window between free and expensive. That window must be
re-measured, not guessed.

Build the seam and the instrumentation. The next pilot supplies the number.

## What to build

- A stop-rule module whose whole interface answers, from one seed's history,
  whether to continue and if not why. The iteration cap becomes one
  implementation of that interface rather than the only mechanism.
- Enough recorded per wave to fit a rule offline: which constraints failed,
  whether the failing set is shrinking between waves, and the direction ruling
  that wave carried.
- The stop reason recorded on the seed's final log record, so a later analysis
  can separate accepted, stopped-early and cap-exhausted without inference.

## Warnings

The loop today mixes the stop decision into three branches inside a long body,
interleaved with network calls, JSON parsing, cost accumulation and logging.
Move the decision out; do not move the I/O in. The value of this ticket is that
the rule becomes testable from a list of records with no network at all.

Do not add a rule that fires on the pre-fix evidence. Ship the cap as the only
active implementation, and leave the seam ready for the rule the next pilot
justifies.

Reuse what exists. The failing inference-distance direction is already computed
and already carried between waves; it is recorded but never used for a stop
decision.

## Acceptance criteria

- [ ] A stop-rule module exists, and the Stage A loop asks it rather than
      testing the cap inline.
- [ ] The rule is tested from a list of wave records, with no network and no
      monkeypatching of the batch runner.
- [ ] Each wave record names the failed constraints and the direction ruling.
- [ ] Each seed's final record names why it stopped: accepted, stopped early, or
      cap exhausted.
- [ ] Replaying the p6 log in `docs/evidence/` through the analysis reproduces
      the published figures: 103 waves, 51 on seeds that never accepted, latest
      accepting wave 6.
- [ ] The active behaviour is unchanged — the cap is still the only rule that
      fires.
- [ ] `uv run python -m pytest mask_off -q` passes.
