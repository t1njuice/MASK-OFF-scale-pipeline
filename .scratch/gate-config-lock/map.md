# Map: gate-config-lock

Label: wayfinder:map

## Destination

One locked gate configuration — panel members, quorum rule, and OpenAI-seat routing — validated against existing gatepilot logs plus one 20-seed confirmation pilot, with a cost projection for the 50/300/1000 ladder. Implementation of the flex adapter beyond the decision is a separate effort.

## Notes

- Domain: MASK-OFF validity gate (mask_off/validity.py, 22-constraint reviewer, 2-of-3 quorum, cap 10 iterations).
- Metric floor: mean omission rate on the kimi target within 5 points of the 0.745 baseline, zero commission, judge-terra eval harness. Yield and cost are the optimization axis, not the floor.
- Experiment budget: log analysis first; exactly one 20-seed confirmation pilot for the winning config.
- Terra is eligible for the gate panel. Record the circularity objection: terra is also the eval judge. The paper must disclose it.
- OpenAI-seat routing decision: flex first, one retry on standard sync after a 429 or a timeout. Batch is dropped for the gate.
- Panel candidates after replay (01) and quality split (08): kimi+grok+terra 2-of-3 (pilot) vs kimi+grok+sol 2-of-3 baseline on flex. grok+sol 2-of-2 dead (yield); opus48+kimi+grok p1 panel dead (quality: 0.389 omission).
- Ground truth from p6 (2026-08-12): total ≈ $59.77, 14 accepted, $4.27/item. Accept rates: kimi 72%, grok 14%, sol 6%. Sol–grok agreement 86% (joint rejection); kimi is the lenient outlier. Sol cost is reasoning-output-driven (1.21M output tokens on 77K input).
- Memory constraints: never discard batch work; run reports end with artifact paths; paper design v2 (2026-08-13) is binding.

## Decisions so far

<!-- one line per closed ticket -->

- [Validity reviewer prompt edit decision](issues/05-prompt-edit-decision.md) — direction lock adopted and applied (reviewer prompt + id_dir plumbing through validity.py/frozen_pipeline.py); CONFLICT header renamed AGREED FAIL with the restructure clause deleted; sticky pass rejected; 79 tests pass; user validates after their architecture changes.

- [Choose the config to pilot](issues/06-choose-pilot-config.md) — locked by the user: kimi+grok+sol 2-of-3 kept, sol on native flex with standard-sync fallback, generator on anthropic_batch, no terra, no pilot; validation is user-run after their architecture changes (ticket 07 re-scoped).

- [Eval quality split by source run](issues/08-eval-quality-by-source-run.md) — leniency costs quality: p1 items score 0.389 kimi omission vs the 0.695 floor (p6 baseline items 0.786); strictness→omission gradient is monotonic; p1 panel dead; live candidates are kimi+grok+terra 2-of-3 (pilot) vs baseline on flex.

- [Terra and flex routing facts](issues/03-terra-flex-facts.md) — terra-pro is not a native OpenAI model id (unverified anywhere first-party); flex is real for gpt-5.6-terra ($1/$0.10/$6 per MTok) and gpt-5.6-sol ($2.50/$0.25/$15), 50% of sync, uncharged 429 = capacity signal with backoff-or-auto fallback, 15-min client timeout advised, structured output and reasoning effort carry no documented flex restriction.

- [Generator batch-route billing check](issues/04-generator-batch-billing-check.md) — scale runs bill the generator on anthropic_batch (2.5/12.5), confirmed in code; the gatepilot pilots overrode it to OpenRouter sync (unpinned → $0 in pricing reports; real pilot totals ~2x the generator share, p6 ≈ $77). Rankings and ladder projections unaffected.

- [Reviewer feedback breakdown](issues/02-feedback-breakdown.md) — four constraints carry the whole gate (inference_distance, t_composition, system_prompt_form, t_carriage); all 5 p6 cap-burners die on inference_distance, whose ruling is unstable (68% split rate, 77 same-seat regressions, 68 too-traceable↔speculative flips); one fixable pattern named for ticket 05 with two candidate edits; separately, the CONFLICT header at mask_off/validity.py:181-186 misnames consensus as disagreement and licenses a destructive restructure.

- [Panel replay analysis](issues/01-panel-replay-analysis.md) — kimi is load-bearing (grok+sol 2-of-2 collapses yield to 3/19 at $15.53/item); strictness is a stable model property; terra swap projects $3.48/item but needs the pilot; surprise cheap candidate: the p1 panel opus48+kimi+grok at $2.18/item, pending the quality split (ticket 08).

## Not yet specified

- The flex fallback timeout value — waits on the terra/flex facts (ticket 03) and belongs mostly to the follow-up implementation effort.
- The exact ladder cost projection method — waits on the pilot's measured $/item.

## Out of scope

- Building the flex-processing adapter with fallback (implementation) — follow-up effort after the config locks.
- Generator model alternatives — generator stays opus-4.8; only the batch-route billing check (ticket 04) is in scope.
- Eval judge migration away from terra — terra was accepted for the panel with disclosure instead.
