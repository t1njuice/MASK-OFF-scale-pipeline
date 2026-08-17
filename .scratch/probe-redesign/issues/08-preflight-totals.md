# 08 — Preflight totals

**Status:** resolved pending review
**Type:** task
**Blocked by:** 02, 03, 04, 05

## Problem

The redesign changes the cost shape: probes fan out 13-fold, the salience
probe and its judging are new, and the gate adds a pass. The user decided
in round 1: compute the preflight total before any spend decision. The
existing preflight enforces pinned prices; it must now count the new
request classes.

## Decisions

- Extend the existing preflight (the launch-time check that reads pinned
  prices) to enumerate every Stage B request class from (manifest size ×
  roster × config): roleplay K=5; recognition 1 + harm-judge on the
  clean-YES subset (bound it by assuming all clean-YES — an upper bound is
  the honest preflight number); salience 2 + up to 2 judge calls; variant
  1 + gate 1 (+1 regeneration upper bound); direct-ask 2 per seat + panel
  judging; competence rides existing judge calls at zero extra requests.
- Output: request count and dollar upper bound per stage and in total,
  before anything submits. Missing price for any seat in any role stays a
  hard failure (existing behavior).
- Respect the flags: a disabled instrument contributes zero to the total.

## Tests

Pure-function seam over synthetic prices and a synthetic manifest/roster.
Prior art: `test_pricing_preflight`.

- Counts: 2 items × 2 seats with all flags on → exact expected request
  count per class (hand-computed in the test).
- Flags off remove their classes from the count.
- A seat missing a price in any role fails hard.

## Out of scope

Actually gating the real run; price updates.

## Comments

**2026-08-16, from ticket 02's review — one addition to this ticket:**
The request-id scheme's collision-freedom rests on seat labels containing
no `__` and not colliding with reserved id segments. Add a preflight
guard: fail hard if any seat label contains `__` or equals a reserved
segment (`variant`, `recognition`, `salience`, `p2`, `main`). Test it.

**2026-08-16, from ticket 04's review — second addition:** recognition and
salience SAMPLE requests are not ledgered (`cost_by_stage` undercounts ~26
requests/item at 13 seats; roleplay and variant are ledgered, probe samples
are not). Add ledger usage entries for both probe sample classes under a
stage the by-stage table reports, and pin with a test.

**2026-08-16, implementer — resolved.**

*Where it lives.* `launch.stage_b_totals(n_items, targets, smoke_n, probes)`
is the pure seam (returns `{"stages": {name: {requests, dollars}}, requests,
dollars}`); `launch.print_stage_b_totals` is the printing wrapper returning
False on any hard failure. Wired at the two operator entry points, after
`preflight()` and before anything submits: `evaluate.main` (thermometer
defaults, matching what `evaluate()` will run) and `scale.main`'s evaluate
branch (the roster at `TARGET_K`). Not wired inside `evaluate()` itself: the
seam-1 tests call it with panels whose route depends on OPENAI_API_KEY, and a
hard price failure there would make the suite env-dependent.

*Request-class enumeration* (S seats, J judge seats, n items):
- `roleplay` n x sum(K per seat); `smoke` min(smoke_n, n).
- `roleplay_judge` n x J — ONE request per judge per item, as `_judge_reqs`
  actually batches (all samples of an item ride one request as input).
- `recognition` n x S; `recognition_judge` n x S upper bound (all clean-YES).
- `salience` n x S x SALIENCE_K; `salience_judge` same count upper bound
  (no literal NONE).
- `variant` 2n (1 + 1 regeneration); `variant_gate` 2n (gate + re-gate).
- `probe2` n x S x PROBE2_K; `probe2_judge` n x J (batched like roleplay).
- Competence: zero extra requests (rides `roleplay_judge`).
- A flag that is off REMOVES its classes (absent, not zero rows).
- Scale path smoke bound: the smoke test runs per cohort, so `scale.main`
  passes `cohorts x OPUS5_SMOKE_N`; `min()` against n_items keeps it an
  upper bound when the last cohort is short.

*Token assumptions (documented upper bound).* Input =
`launch.PREFLIGHT_INPUT_TOKENS` = 4000 per request (material well under
1.5K tokens, the four-label rubric ~1.7K, scaffolding a few hundred), PLUS,
for judge-class requests, the output caps of the response texts the request
carries (roleplay judge: sum K x cap over sampled seats + smoke cap for the
first smoke_n items; p2 judge: VARIANT_MAX_TOKENS + PROBE2_K x cap per
seat; harm/salience judges: the responding seat's cap; gate:
VARIANT_MAX_TOKENS; p2 samples: VARIANT_MAX_TOKENS). Output = the seat's
full max_tokens. Priced at the model's most expensive PINNED reachable
route (flex can fall back to standard), with input at
`max(in, cache_write)` where a write rate is pinned. Any reachable
(model, route) pair missing from PRICES raises ValueError — hard failure
preserved.

*Seat-label guard.* `launch.RESERVED_ID_SEGMENTS` = {variant, recognition,
salience, p2, main, harm_match, salience_judge, variant_gate,
variant_retry, variant_gate_retry} — the ticket's five plus the five
"also consider" segments. `launch.seat_label_problems` flags `__` or a
reserved label; `preflight()` refuses (check 1b, before any client) over
TARGET_PANEL + JUDGE_PANEL + THERMOMETER_SEAT + OPUS5_SMOKE_SEAT (when
smoke is on); `stage_b_totals` also refuses for programmatic targets that
never pass through config. VALIDITY_PANEL stays exempt (votes are
slot-identified, labels never reach ids).

*Ledger fix.* Recognition, salience, AND probe-2 direct-ask sample
responses now write `ledger.usage_entries(..., stage="probe")` —
**deviation, disclosed**: the ticket routed recognition+salience only, but
the wave-2 direct-ask samples had the identical gap (billed, never
ledgered), so all three probe sample classes land under one "probe" row.
Stage names in `cost_by_stage` after this ticket: target, smoke (variant
rewrites — pre-existing naming, untouched), probe, judge.

*Tests.* test_pricing_preflight: exact per-class counts for 2 items x 2
seats all flags on (64 total), flags-off class removal, hand-computed
dollars over synthetic prices, missing-price ValueError, guard fires on
`a__p2` (preflight and pure seam) and on `variant`, clean labels pass.
test_probe_flags: muse priced at $1M/MTok so each fake message costs
exactly $3 — `cost_by_stage["probe"] == 15.0` (1 recognition + 2 salience
+ 2 direct-ask samples), `target == 3.0`. Suite: 335 passed, 1 failed —
the failure is the KNOWN standing conflict
(test_the_shipped_judge_panel_is_two_models_both_priced vs the user's
uncommitted terra-only JUDGE_PANEL pilot edit), untouched per instruction.

**2026-08-16 (orchestrator):** Reviewer verdict was needs-changes; all three
findings fixed inline and pinned:
1. The printed table now states the retry exclusion and prints the ~2x
   worst case beside the total (bad finals resubmit once per wave; --fill
   resubmits empties again); documented in stage_b_totals' docstring.
2. New preflight check 1c refuses duplicate labels ACROSS the sampling
   seats (target panel + smoke seat share one wave-1 id space) — the
   opus5-target-vs-smoke-seat collision the reviewer constructed; test
   added (test_preflight_refuses_a_target_labeled_like_the_smoke_seat).
3. The three fixed judge seats (HARM/SALIENCE/GATE) are now in
   pricing.configured_models, flag-gated, so the API-key checks cover a
   seat routed somewhere the roster doesn't reach.
Suite: 336 passed + the known standing failure.
