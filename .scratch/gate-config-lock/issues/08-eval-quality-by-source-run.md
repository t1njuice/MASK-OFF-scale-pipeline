# 08 — Eval quality split by source run

Type: task
Status: resolved

## Question

Do items accepted by lenient panels score worse on the omission eval than items accepted by strict panels?

The pooled eval (output/gatepilot_all_2026-08-12_222713Z_..., 17 items, 0.745 kimi omission) mixes items from several gatepilot runs. Join eval result_ids back to each run's accepted jsonl and report mean omission per source run/panel. The load-bearing comparison: p1 (opus48+kimi+grok 2-of-3, most lenient, $2.18/item) vs p6 (kimi+grok+sol 2-of-3 baseline). If p1's items hold the 0.745±5pt floor, the p1 panel becomes a pilot-free cheap candidate for ticket 06; if they score worse, leniency costs quality and the strict OpenAI seat earns its price.

Added by ticket 02: the p1 run log holds 64 error rows in 119, all `RuntimeError('generator batch returned no message')`; only 55 rows carry votes. Check whether those failed generator calls billed tokens, and whether they distort p1's $2.18/item or its accepted-item mix. If p1's cheapness is an artifact of failed calls, the candidate dies here rather than at ticket 06.

## Answer

**Yes — leniency costs quality, decisively. The p1 panel is dead as a candidate.**

Join: eval summary items → result_id → each run's accepted jsonl. All result_ids matched.

| Source run (panel) | n items | kimi omission | opus48 omission |
|---|---|---|---|
| p1 opus48+kimi+grok 2-of-3 (lenient) | 18 | **0.389** | 0.389 |
| p2 opus48+grok+sol 2-of-3 | 11 | 0.606 | 0.424 |
| p3 opus48+grok 2-of-2 | 6 | 0.722 | 0.389 |
| p6 kimi+grok+sol 2-of-3 (baseline) | 14 | **0.786** | 0.476 |
| p7 kimi+grok+sol 3-of-3 | 3 | 0.556 | 0.778 |

The floor is 0.745−5pts = 0.695 on the kimi target. p1's items sit at 0.389 — half the baseline, nowhere near the floor. The gradient runs monotonically with panel strictness on the kimi-omission axis (p1 0.389 → p2 0.606 → p3 0.722 → p6 0.786): the strict OpenAI seat earns its price by filtering weak items, exactly what the sol/grok "joint rejection" behavior buys. Note the 0.745 pooled baseline decomposes as p6 items 0.786 + p7 items 0.556.

Caveats: the p1/p2/p3 items and the p6/p7 items were scored in two separate eval runs (151334Z and 222713Z) on the same target+judge harness; sample sizes are small (n=3-18); each item scored by 3 responses per target.

**p1 error rows**: 64 of 119 rows are generator errors ('generator batch returned no message'); their usage dicts are empty, so no tokens are recorded and the $2.18/item figure is not inflated by logged failed calls. (If the provider billed those failures, the log cannot see it — moot, since quality kills the candidate regardless.)

**Consequence for ticket 06**: the cheap-seat-by-leniency route is closed. The live options are kimi+grok+terra 2-of-3 (the budgeted pilot) and the kimi+grok+sol baseline with flex routing (~$3.92/item, no pilot risk). Terra's open risk flips sign: a terra *stricter* than sol was the yield worry; this result says stricter is survivable on quality, and *lenient* terra is now the quality worry.
