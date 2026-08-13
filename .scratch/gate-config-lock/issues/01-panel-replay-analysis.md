# 01 — Panel replay analysis

Type: task
Status: resolved

## Question

Which panel candidate wins on cost per accepted item, and is kimi's vote ever decisive?

Replay the existing run logs (output/gatepilot_p1, p2, p3, p6, p7) without new API calls:

1. For each gate iteration, recompute the quorum outcome under each candidate: grok+sol 2-of-2, kimi+grok+terra 2-of-3 (terra unknown — mark iterations where the outcome depends on the unknown seat), kimi+grok+sol 2-of-3 baseline.
2. Count the iterations where removing kimi flips the outcome (kimi-decisive iterations). If near zero, kimi is not needed.
3. Compute cost per accepted item for each candidate from the usage records and config.PRICES, with terra priced at 1.0/6.0 per MTok.
4. Report per-reviewer accept rate and pairwise agreement per run, so the p6 pattern (sol-grok joint rejection, kimi lenient) is confirmed or contradicted across model families.

## Answer

Method: replayed all six gatepilot run logs (p1, p2, p3, p4, p6, p7). Per seed, a candidate accepts at the first iteration where its quorum is met on the recorded verdicts; cost counts the generator plus only that candidate's seats up to that iteration. Script: scratchpad replay.py (session 2026-08-13).

**1. Kimi is needed. Dropping it collapses yield.** Sol and grok agree 71-88% of the time, but almost always on *reject* — they jointly accept rarely. Replay of grok+sol 2-of-2:

| Run | Actual 2-of-3 (with kimi) | grok+sol 2-of-2 replay |
|---|---|---|
| p6 | 14/19 accepted, $3.92/item | 3/19 accepted, $15.53/item |
| p7 | 10/10 accepted (2of3 replay), $2.34/item | 3/10, $11.71/item |
| p4 | 6/10 (2of3 replay), $4.97/item | 0/10, no accepts |
| p2 (opus48 as third seat) | 11/19, $5.35/item | 1/19, $42.34/item |

Kimi's leniency (accept rate 51-75% across runs, vs grok 2-28% and sol 3-9%) is what lets the 2-of-3 quorum reach acceptance: most accepts are kimi + exactly one strict seat. The naive "kimi-decisive" count (iterations where sol and grok split: 11/99 in p6) understates this; the replay is the correct test. Verdict: **keep kimi in any 2-of-3 panel; do not run a strict-duo panel.**

**2. The strictness pattern is stable across all runs, so it is a model property, not a seed artifact.** Grok strict everywhere (0.02-0.28), sol strict everywhere (0.03-0.09), kimi lenient everywhere (0.51-0.75), opus-4.8 mid (0.44-0.64). Sol-grok pairwise agreement 0.71-0.88 in every run that contains both.

**3. kimi+grok+terra 2-of-3 cannot be decided by replay.** With the terra seat unknown, the outcome is determined only where kimi and grok agree: 40% of p6 iterations, 37% of p4, 51% of p7. The other half depends on terra's verdict, so the confirmation pilot (ticket 07) is the only test. Cost projection if terra's token profile matches sol's: the p6 OpenAI seat drops from $18.35 to $7.34, run total $59.77 → $48.76, **$3.48/item at unchanged yield** (~18% saving). If terra is more lenient than sol, yield rises and $/item falls further; if stricter, the panel degenerates toward the strict-duo failure above.

**4. Cheapest observed config is the p1 panel (opus48+kimi+grok 2-of-3): 18/19 accepted at $2.18/item** — 44% cheaper per item than p6. It replaces the expensive OpenAI seat with the generator's own family (opus-4.8, batch-priced 2.5/12.5). Two caveats: (a) generator and one reviewer share a model family — self-review risk, same disclosure class as the terra circularity; (b) it is the most lenient panel, so its accepted items may be weaker — the pooled eval (0.745 omission) does not separate items by source run. That split is answerable from existing eval + accepted jsonls; filed as ticket 08.

**Recommendation for ticket 06:** the live candidates are kimi+grok+terra 2-of-3 (pilot required) and opus48+kimi+grok 2-of-3 (already run as p1; needs ticket 08's quality split, not a new run). grok+sol 2-of-2 is dead. The baseline kimi+grok+sol 2-of-3 stays as fallback at $3.92/item.

## Comments

Correction from ticket 04: the gatepilot runs paid OpenRouter sync (5/25) for the generator, not batch (2.5/12.5) as this replay assumed, so absolute pilot dollars are understated by the generator share (~2x on that component; p6 real total ≈ $77). Rankings and per-candidate comparisons are unaffected (generator cost is common), and the scale-ladder projections correctly use the batch rate.
