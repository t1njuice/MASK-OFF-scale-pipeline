# Evidence

Two run logs. The architecture-review tickets in `.scratch/pipeline-architecture/`
cite them. They live here so no ticket needs the results tree.

Both files are append-only JSONL. One line is one record. A record with an
`accepted` key is a decision record — one wave of one seed. A record with a
`stage` key is an error record or a lint record.

## `p6_gate_pilot_run_log.jsonl`

Source: `output/gatepilot_p6_gen-opus-4-8_gate-kimi+grok+sol2of3cap10_seeds-e2e20_2026-08-12_161138Z_run_log.jsonl`

What it measured: the locked gate configuration (kimi-k3 + grok-4.5 +
gpt-5.6-sol, 2-of-3) over 19 seeds at an iteration cap of 10, on 2026-08-12.

What it shows — the cost sink and the wall-clock tail are the same 5 seeds:

| Figure | Value |
| --- | --- |
| Log records | 103 |
| Waves (distinct seed + iteration) | 102 |
| Seeds launched | 19 |
| Seeds accepted | 14 |
| Seeds that never accepted | 5 |
| Waves spent on those 5 seeds | 50 |
| Latest wave that accepted a seed | 6 |
| Wall clock, first record to last | 5 h 17 m |
| Wall clock after the last acceptance | 1 h 35 m |

Each of the 5 never-accepting seeds burned the full cap of 10 waves. Half the
waves of the run bought nothing.

Reconciliation note: the review text quotes "103 waves, 51 on seeds that never
accepted". Those are record counts, not wave counts. The log holds 103 records
but 102 waves, because one record is a lint record that shares its wave with a
decision record. Cite 102 and 50.

Reproduce every figure above with:

```bash
uv run python docs/evidence/summarize.py
```

The same wave figures, per seed and with the stop reason each seed left on —
`mask_off.stoprule` replays any run log through the stop rule, inferring the
reason for logs written before the reason was recorded:

```bash
uv run python -m mask_off.stoprule docs/evidence/p6_gate_pilot_run_log.jsonl
```

That command also prints the cap ladder below and the occupancy figure. It
reports what the log contains: p6 ran at a cap of 10, and its figures do not
move when `config.FROZEN_MAX_ITERATIONS` changes.

**What each cap would have cost this run.** Waves and dollars are what p6 would
have spent under that cap; items lost are accepted items it would not have
reached. Dollars carry the same caveat as `frozen_19` below — two seats predate
the route field and price at zero, so every row is a floor, and the ratios
between rows are the usable part.

| Cap | Waves | Dollars | Items lost |
| --- | --- | --- | --- |
| 5 | 75 | 17.59 | 2 of 14 |
| 6 | 82 | 19.18 | 0 |
| **7** (configured) | 87 | 20.43 | 0 |
| 10 (what p6 ran) | 102 | 23.85 | 0 |

The window between free and expensive is one wave wide, and p6 is PRE-fix data:
the direction-lock fix landed after it. A seed the fix recovers could accept
later than wave 6, so this ladder is re-measured on the next pilot, not reused.

**Occupancy — the cohort tail, in one number.** p6 bought 102 seed-waves
against 19 slots held open for 10 rounds, so 54% of the slot time bought a
wave. The other 46% is slots idling after their seed accepted, waiting on the
cohort's 5 cap-burners. Ticket 12 removes the boundary this was measurable
across; `stoprule.flight` computes it from per-seed enter/leave times instead,
so it survives the change.

## `frozen_19_run_log.jsonl`

Source: `output/frozen_19_gen-opus-4-8_gate-opus-4-8_seeds-e2e20_2026-08-06_151137Z_run_log.jsonl`

What it measured: 19 seeds through the frozen validity-only pipeline on
2026-08-06, under the pre-lock panel (opus-4-8 x2 + grok-4.5).

What it shows — output tokens are the bill:

| Figure | Tokens | Rate, $/MTok | Dollars |
| --- | --- | --- | --- |
| Output | 2,517,397 | 12.50 | 31.47 |
| Input | 736,419 | 2.50 | 1.84 |
| Cache write | 437,066 | 5.00 | 2.19 |
| Cache read | 2,879,996 | 0.25 | 0.72 |
| **Total** | | | **36.21** |

186 usage blocks. The rates are the `claude-opus-4-8` on `anthropic_batch`
entry in `config.PRICES`.

Output is 87% of the bill. Only the number of waves bought moves it.

Reconciliation note: the review text quotes 89%. That is the output share of
output plus input alone. Against the whole bill, cache write and cache read
included, the share is 87%. The conclusion does not change.

The 1-hour prompt cache is not a problem and no ticket should spend effort
there: 2,879,996 cache-read tokens against 437,066 written is 6.59 reads per
write, and the two together cost $2.91 where the same tokens uncached would
cost $8.29.

Reproduce every figure above with the same command:

```bash
uv run python docs/evidence/summarize.py
```

Caution: this log predates the route field on the usage record, so one panel
seat carries the model id `anthropic/claude-opus-4.8` with no pinned
`(model, route)` entry. `mask_off.pricing.usage_cost` prices that seat at zero
and reports $24.59 for the run. Ticket 04 turns that silent zero into a
preflight failure.
