# 04 — Generator batch-route billing check

Type: task
Status: resolved

## Question

Do scale runs actually bill the opus-4.8 generator on the anthropic_batch route (2.5/12.5), not sync (5/25)?

The p6 usage records show route: null and zero cache reads for the generator. Check mask_off/frozen_pipeline.py and mask_off/scale.py to confirm which route the generator takes in a scale run, and whether the costing uses the batch price. Answer records the code path and any discrepancy.

## Answer

**Yes for scale runs; no for the gatepilot pilots — and that skews the pilot cost figures.**

Code path: `config.GENERATOR_MODEL = "claude-opus-4-8"` (native id, mask_off/config.py:20). Both routers send claude-prefixed ids to the batch route: `mask_off/pricing.py:20` (`route_of`: claude-* → anthropic_batch) and `mask_off/batch_providers.py:56-58` (`route`: claude-* → anthropic_batch). PRICES pins ("claude-opus-4-8", "anthropic_batch") at 2.5/12.5. So a scale run bills the generator at the batch rate. Confirmed.

Discrepancy found: the gatepilot experiments overrode the generator to `"anthropic/claude-opus-4.8"` — OpenRouter sync — with the comment "batch queue congested" (experiments/seedcraft/gatepilot_p1.py:13, same in p4 and gatepilot_resume.py). Two consequences:

1. That (model, route) pair is not pinned in PRICES, so `usage_cost` bills those generator rows at $0 with a one-time warning. Any pricing.py-based report over the gatepilot logs silently omits the generator.
2. Ticket 01's replay priced the pilot generator at batch 2.5/12.5. The pilots actually paid OpenRouter sync (Anthropic sync rate 5/25), so pilot generator dollars are ~2x the replay figures (p6 real total ≈ $77, not $59.77). The candidate *ranking* is unchanged — the generator cost is identical across candidates — and the *scale-ladder* projections are correctly built on the batch rate, since scale runs use it.

Action for the follow-up implementation effort (not this map): pin ("anthropic/claude-opus-4.8", "openrouter_sync") in config.PRICES if pilot-style sync runs recur, so --max-cost sees them.
