# 07 — Panel and Seat

**What to build:** one way to express "a set of model seats that vote or sample
on one artifact", used by the validity gate, the target roster and the judge
alike. Delivers the 13-model target roster that shrinks to two by editing a
list, and the two-model final judge.

**Blocked by:** 04 — a judge or roster model with no pinned price must fail at
preflight before this ticket can add models.

**Status:** ready-for-agent

## Why

The same concept is expressed three incompatible ways today. The validity panel
is a list indexed by vote slot. The target roster is a list with a derived gate
model. The judge and the thermometer are bare scalars.

The planned design needs all three to change at once: a 13-model roster that
stays easy to shrink, and a final judge of two models, terra on a batch and
opus-4.8 on a batch. The judge change alone reaches the request builder, the
identifier scheme, the un-blinding map and the summary — which reports a single
judge model as a string.

## What to build

- One panel value: an ordered list of seats, each carrying a label, a model, an
  effort and a token cap. Per-seat token caps matter, because the cost model
  multiplies the panel size by the output cap and today one global ceiling
  applies to every seat.
- One helper expanding a panel into requests with collision-free identifiers.
- The validity gate, the target roster and the judge all built from panels.
- A judge panel of more than one model: each judge scores every response, the
  identifiers cannot collide, the un-blinding stays correct per judge, and the
  summary reports per-judge results rather than one model name.
- Panel and Seat added to `CONTEXT.md`, with the `_Avoid_` list the other
  entries carry.

## Warnings

Model blinding is a measurement property, not a detail. The judge sees responses
under anonymous identifiers and the mapping is reversed afterwards. With two
judges the mapping is per judge; getting this wrong corrupts every rate in the
paper without failing any test. Cover it with a test that uses two judges and
distinguishable responses.

Reasoning traces are never passed to the judge. That rule survives.

Do not change the accept rule while changing its shape. The gate is 2-of-3 and
stays 2-of-3; the quorum must stay configuration, never a constant derived from
the panel length.

## Acceptance criteria

- [ ] One panel type expresses the validity gate, the target roster and the
      judge.
- [ ] Changing the target roster between 2 and 13 models is a single list edit,
      with no other file touched. Demonstrate both.
- [ ] The judge runs two models, and a test with distinguishable responses
      proves each judgment is attributed to the right response and the right
      judge.
- [ ] The evaluation summary reports per-judge results, not one judge model
      string.
- [ ] Panel and Seat are defined in `CONTEXT.md`.
- [ ] The quorum stays configuration and is not derived from the panel length.
- [ ] `uv run python -m pytest mask_off -q` passes.
