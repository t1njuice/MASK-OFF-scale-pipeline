# Map: pipeline-architecture

Label: wayfinder:map

## Destination

A lean `mask_off` package on a clean trunk, where the cost of a scale run is set
by a measured stop rule rather than a hand-edited cap, the wall time is not set
by a cohort barrier, and adding a model is a table edit. The 13-model target
roster and the two-model final judge run without touching pipeline code.

## Why this effort exists

Two measurements from the 2026-08-13 architecture review:

- **Cost is output tokens, not prompts.** Over `frozen_19` (186 usage blocks):
  2,517,397 output tokens = $31.47, against 736,419 input tokens = $1.84.
  Output is 89% of the bill. Only the number of rounds bought moves it.
- **Half the spend bought nothing.** In p6 (19 seeds, cap 10): 51 of 103 rounds
  went to the 5 seeds that never accepted, and those same 5 seeds are the
  1 h 31 m tail after the last acceptance. Cost sink and clock tail are the
  same seeds.

The 1h prompt cache was checked and is NOT a problem: 6.59 cache reads per
write, $2.91 against $8.29 uncached. Do not spend a ticket there.

## Context-rot rules for this effort

1. **The working tree is the context budget.** Ticket 01 cuts 4,199 tracked
   files to roughly 250. Every later ticket assumes it landed.
2. **Evidence lives in `docs/evidence/`.** No ticket needs the results tree.
3. **One ticket = one fresh context window = one verification command.** The
   command is `uv run python -m pytest mask_off -q`. Baseline: 79 passed.
4. **This map is the shared memory.** Record every closed ticket below in one
   line, so the next agent does not re-derive what the last one settled.

## Notes

- Domain vocabulary is fixed by `CONTEXT.md` (seed, item, cohort, wave, quota,
  route, cell, batch cache, config fingerprint). Panel and Seat are new terms
  introduced by ticket 07 and must be added to `CONTEXT.md` there.
- Settled decisions live in `planning/scale-1200/` (ADR-0001 batch cache,
  ADR-0002 native batch adapters, design.md). Do not re-litigate them. Ticket
  12 is the only one that touches an ADR invariant, and it says so.
- The locked gate configuration is kimi-k3 + grok-4.5 + gpt-5.6-sol, 2-of-3,
  sol on flex with standard-sync fallback, generator opus-4.8 on
  anthropic_batch. See `.scratch/gate-config-lock/map.md`.
- The direction-lock fix for inference-distance oscillation landed 2026-08-13
  and is UNVALIDATED. Every cap number measured before it is stale. This is why
  ticket 09 instruments rather than picks a new cap.
- Standing user rules: never discard batch work (harvest before any
  cancel/resubmit); run reports end with the output artifact paths; define
  jargon before use; prize minimal diffs.
- The clean branch becomes the new trunk (user decision, 2026-08-13). `docs/`
  survives whole.

## Decisions so far

<!-- one line per closed ticket -->

- **01 closed.** Branch `clean-trunk`, forked from `frozen-design-restore` at
  4305a0c. 4,223 tracked files cut to 313 with `git rm`; every deleted path is
  recoverable. `design/` moved to `docs/design/` rather than deleted — it is
  design record, but at the root it sent agents to the retired v1 loop.
  `petri_bloom/` held zero real files and nothing imports it, so the
  `petri-bloom`, `inspect-petri` and `inspect-ai` dependencies were dropped
  from `pyproject.toml` too. Evidence in `docs/evidence/`, with
  `summarize.py` asserting every published figure.
- **Both root collection errors are closed, not deferred.**
  `test_pipeline_waves.py` was deleted with the v1 test files.
  `test_seed_diversity.py` was a **stale fixture, not a regression**: it pinned
  two subcategory label strings that a rewrite of `seed_subcategories.md`
  removed. Both assertions now read their labels out of the file. The root
  suite reports 92 passed, 59 subtests passed.
- **02 closed.** `AGENTS.md` rewritten around the two stages and the two
  `mask_off.scale` commands. `README.md` replaced too — 225 lines of Petri
  Bloom setup and `mask_off.pipeline --mode smoke`, every command dead. A
  README that contradicts the brief defeats the brief.
- **03 closed.** `pipeline.py` (1,469 lines) and `cost_report.py` deleted. The
  three survivors — `preflight`, `run_timestamp`, `select_seeds` — live in
  `mask_off/launch.py`, named for what a run needs before its first request.
  `reviewer.py`, `target.py`, `lessons.py` and `extract_samples.py` went too:
  nothing but `pipeline.py` imported them, so they became unreachable and
  nothing absorbed their loss. Package: 8,558 to 6,525 lines. Suite: 77 passed.
- **The ticket's dead-knob list was wrong in both directions.** `TAXONOMY` and
  `LEVERS` are **live**, not dead: `generator.py` snaps every generated
  `taxonomy` and `primary_lever` onto them, so deleting them would break the
  generator. Five knobs the ticket missed were dead and went: `REVIEWER_MODEL`,
  `REVIEWER_EFFORT`, `REVIEW_MAX_TOKENS`, `RUN_LOG`, `LESSONS_PATH`. Twelve
  removed in total. Check readers with a scan, not with a list.
- **04 closed.** The panel on disk now matches the locked gate:
  kimi-k3 + grok-4.5 + gpt-5.6-sol, 2-of-3, cap 10. Panel and cap are both
  fingerprint fields, so every existing run directory will refuse to resume
  without `--force`. That is the gate working; no bypass was added.
  `launch.preflight` now fails before the first request when any reachable
  `(model, route)` pair is unpinned, via `pricing.unpinned()`.
- **The ticket named the wrong terra.** `openai/gpt-5.6-terra-pro` is not a
  priced OpenAI model id and appears nowhere on their pricing page; pinning it
  on a native route would have sent it to an endpoint where it does not exist,
  because `route()` prefers a native route as soon as one is pinned. Pinned
  `openai/gpt-5.6-terra` instead, on sync, batch and flex. Its flex rate
  ($1 / $0.10 / $6) matches the figure the gate-config lock measured
  independently. `diversity/labeling/judge_labels.py` still calls terra-pro as
  an OpenRouter slug; that path does not use `mask_off.pricing`, so it is
  unaffected, but it is worth a look in the diversity effort.
- **`claude-opus-5` is pinned now, at the same rates as opus-4-8.** It was
  deliberately unpinned as "smoke-test volume only", which is exactly the
  silent-zero the ticket exists to remove. Rates verified against Anthropic's
  pricing page; the two batch cache cells apply that page's stated
  2x-write / 0.1x-read multipliers to the discounted batch input.
- **The price check is environment-dependent, by design.** Without
  `OPENAI_API_KEY`, the sol seat reroutes to OpenRouter, where sol is not
  pinned, and preflight refuses. Set the key or pin the OpenRouter rate; do
  not relax the check. A test covers both directions.
- **05 closed.** `mask_off/routes.py` is the one place that answers "how does
  this request reach a model". `route()` moved there from `batch_providers`,
  and the eligibility rule reads `Adapter.day_only` instead of hardcoding the
  latency test. The four split sites collapsed to one: `llm.run_batch` is now
  `llm.run_anthropic_batch`, an adapter that assumes its route is chosen, and
  the batch cache calls `dispatch` instead of re-partitioning.
- **Route is stamped before `on_result`, not after dispatch returns.** The
  cache normalizes inside `on_result`, so a route stamped afterwards would
  never reach `_results.jsonl` and every replayed cost would be priced by
  inference. `routes._stamped` is the wrapper; an adapter that already knows
  better wins, so a flex fallback stays `openai_sync`.
- **`pricing.route_of` keeps its prefix guess, for legacy rows only.** Records
  written before ticket 05 carry no route, including the `frozen_19` evidence
  log. The guess is wrong for anything that ran on flex or a native OpenAI
  batch, which is why new records never take it. Do not extend it.
- **The journal route name changed from `anthropic` to `anthropic_batch`.**
  `drain_orphans` accepts both: a harvest must never fail to recognise a route
  it wrote itself.
- **Tests drive the registry now.** `mask_off/conftest.py` registers one fake
  adapter across all four routes and fires the real hooks through the real
  stamping wrapper. Monkeypatching `llm.run_batch` only ever worked because
  the transport had no seam.
- **The seam nearly broke "never discard batch work", and now guards it.**
  Collapsing the split sites made `openai_batch` reachable on the *uncached*
  path, where there is no journal: a `ROUTE_OVERRIDES` entry plus a standalone
  `mask_off.evaluate` run would have submitted a paid 24-hour batch with no
  journal row, unrecoverable if the process died. The pre-seam code prevented
  this by never selecting a batch route outside the cache. `dispatch` now
  refuses a `day_only` route when no `on_handle` hook is present, and says how
  to fix it. Anthropic batch still runs uncached, exactly as before the seam.
- **Seed authoring passed latency `"wave"` against ADR-0002, which calls it
  `"day"`.** Aligned. Behaviour-neutral today: the seedgen model is an
  OpenRouter slug and routes identically at both classes.
- **Review closed with two bugs found and fixed, both introduced by this
  effort.** The batch-orphan hole in `dispatch` (self-review) and the
  incomplete OpenRouter-key enumeration in `launch.preflight` (subagent
  review). Both had the same shape: a list of models written by hand where a
  derived one already existed. Derive the set; do not retype it.
- **08 closed.** Concurrency is an `Adapter` field beside `day_only`; both
  `max_workers=8` literals are gone (the ticket said three; there were two).
  Batch polls interleave via `batch_providers.poll_all_until_done`, a
  single-threaded round-robin generator, with `poll_until_done` as its
  one-handle case. **The limits stay at 8 and that number is UNMEASURED** —
  measuring needs paid calls, none were made, none was invented. Do not raise
  one until a cohort has been timed AND the flex fallback count recorded: a
  fallback bills at twice flex, so a higher limit can cost more than it saves.
- **09 closed.** `mask_off/stoprule.py` is the seam; `IterationCap` is its only
  active implementation. The ticket's "exactly two conditions" was wrong —
  `seed_defect` was already a third exit, buried in an `or` beside the cap, and
  is now a named reason. The log key is `stopped`, not `stop_reason`, which
  generator-error records already use for the provider's own field.
- **The cap is 7, by user decision 2026-08-13, overriding the ticket.** It
  diverges from the gate-config lock's 10; the panel and quorum still match it.
  Replayed over p6: 87 waves against 102, none of the 14 items lost, 1.19 h
  earlier. Cap 6 also loses none, so 7 buys one wave of margin for $1.25. p6 is
  PRE-fix data — a seed the direction lock recovers could accept past wave 6
  and be cut off. `python -m mask_off.stoprule <log>` re-measures the ladder.
- **A replay must never read today's cap.** Review caught this: the wave counts
  were cap-independent but the inferred stop REASON was not, so raising the
  live cap above a finished run's cap reported every cap-burner in it as
  `running`. Inference now reads the cap the log itself attests to. Anything
  that describes a past run must derive from the log, never from `config`.
- **06 closed.** Every Stage A id names its wave: `{seed}__w{n}`, with
  `__lint` and `__vote{i}` inheriting it. `frozen_pipeline.wave_id` is the one
  builder. Collision-free by construction, not by luck: `__w` cannot
  self-overlap, so no seed name can make two (seed, wave) pairs share an id.
- **The wave marker cost the `cand-` prefix, and had to.** Anthropic caps a
  custom_id at 64 characters and the corpus behind p6 contains a 49-character
  seed name, so `cand-{seed}__w{n}__vote{i}` is 66. The prefix carried no
  information. A test pins the budget; do not append to a Stage A id without
  re-running it. OpenAI publishes no verifiable custom_id length — inert today
  because no Stage A request takes `openai_batch` under the locked gate.
- **06's cache consequence, recorded as the ticket requires.** The cache keys
  on sha256(custom_id + params), so every Stage A request is a one-time miss:
  an existing run directory replays from the top and re-bills its Stage A work.
  Journaled batches still drain — `drain_orphans` matches ids and keys verbatim
  from `_batches.jsonl` and never recomputes them — so no paid work is lost,
  only re-bought. User confirmed harmless 2026-08-13; `output/` is empty on
  this branch and no `_results.jsonl` exists in the checkout.
- **Two published figures were wrong and are corrected in `docs/evidence/`.**
  p6 holds 103 log records but **102 waves** (one record is a lint record
  sharing a wave), and **50** of them fall on the 5 seeds that never accepted,
  not 51. Ticket 09 must assert 102 and 50. The `frozen_19` output share is
  **87%** of the whole bill ($31.47 of $36.21, cache write and cache read
  included), not 89%; 89% is the share of output plus input alone. Neither
  correction changes a conclusion.

- **07 closed.** `mask_off/panel.py` holds Seat and Panel; the validity gate,
  the target roster and the judge are all panels. A slot is not a seat: a gate
  casts more votes than it has seats and `seats()` cycles the panel to fill
  them, so vote count and accept threshold stay separate settings. Each judge's
  blinding map is the sorted labels rotated by its slot, so one seat is
  bit-identical to the old behaviour. Four things the ticket did not know:
  `fingerprint` round-trips through JSON where a tuple returns as a list and
  aborts every resume (`_plain()` flattens seats); `JUDGE_MODEL` secretly wrote
  the probe-2 email and had to split to `VARIANT_MODEL`; the run stem printed
  `_gate-opus-4-8` while the panel had been kimi+grok+sol since ticket 04; and
  preflight now refuses duplicate seat labels, `VALIDITY_PANEL` exempt because
  a vote is identified by slot.
- **11 closed.** `mask_off/ledger.py` is the one place cost is counted, and the
  dedup key `(seed_name, iteration, stage)` is stated once inside it. Cost had
  been counted in four places with the rule in only one, so a resumed run's
  printed and reported totals already disagreed. The lint record now carries
  its `usage`: lint spend was in the closing figure but invisible to
  `--max-cost`, so the ceiling under-counted every run that linted.
- **10 closed.** Seeds advance independently; each stage holds at most one
  batch and carries whoever is waiting. `drive`'s in-flight guard is
  load-bearing — without it a stage whose batch is still out gets resubmitted
  and the first future is orphaned, which HANGS the run rather than losing
  work, because results still reach the cache through `on_result`.
  `batchcache._cache()`'s lazy load moved inside the write lock, now an
  `RLock`: two stage threads on a cold cache both loaded and the loser's dict
  was dropped, re-billing rows already paid for.
- **Mutation testing is what makes a ticket's tests worth having.** Ticket 10's
  reviewer had no shell and flagged two suspected gaps. Both were real:
  crossing two seeds' feedback, and deleting `drive`'s in-flight guard, each
  left all 206 tests green. The fixtures handed every seed byte-identical
  feedback, so a crossed wire produced identical output. Break the code, watch
  the test fail, restore it — before reporting a ticket done.
- **A concurrency test that passes 4 times in 5 has not passed.** The
  drive-guard test took four attempts. A single-stage stub proves nothing:
  until something completes, `drive` sits in `wait(FIRST_COMPLETED)` and
  physically cannot resubmit. Two stages, deterministic, 6 runs of 6.

### From the code review of 01-11 (2026-08-13)

- **Three ticket commits swept the user's prompt edits in.** `fd68d0e`,
  `dfbd809` and `86505f2` each carry a change to `mask_off/prompts/*` that
  their message does not mention. The prompts are frozen against tickets, but
  the user tunes them by hand and their edits sit uncommitted while a ticket
  runs, so `git add -A` picked them up. `AGENTS.md` now names the mechanism:
  stage by name, never `-A`, never `-a`. Editing a prompt also moves
  `scale.fingerprint`, so every stamped run directory refuses to resume
  without `--force`. No live consequence — `output/` is empty on this branch.
- **Two vocabulary bans were written wider than the code could obey, and the
  glossary moved rather than the code.** "Transport" is banned as a synonym for
  one Route, but `routes.py` IS the transport seam and that is the ticket's own
  name for it; CONTEXT now bans only the synonym use. "Iteration" is banned as
  a name for a wave, but `iteration` is the ordinal field every run log on disk
  carries, so renaming it would strand the evidence logs; CONTEXT now keeps it
  for the ordinal alone. Still to fix, one word each, deferred only because the
  files were in use: `config.py:38` says "each seat's transport" where it means
  route, and `routes.py`'s table header says Transport where it means endpoint.
- **ADR-0002 §3 named two wave-eligible routes and the code has three.**
  `openai_flex` is a synchronous call at Batch API rates, so it carries no
  window and the rule excluding 24h routes never reached it. §3 is amended;
  `openai_batch` remains the one route the wave class excludes.
- **Three real defects, fixed in `12f23e3`.** `spent_before` resolved the run
  log by DIRECTORY, which only exists under `scale`, so a standalone resumed
  run read 0 and labelled the whole log's spend as this cohort's.
  `pricing.configured_models()` missed `CHEAP_AUDIT_MODEL` — pinned today, so
  nothing ran free, but preflight could not have caught a future edit.
  `scale.run_cost` was a one-line delegation with zero callers.
- **Known and accepted, not fixed.** `evaluate._judges_in` and
  `metrics._judge_seats` are the same function with different sentinels, and
  `metrics` scans `judgments` but not `probe2_judgments`, so a judge appearing
  only in probe 2 is invisible there. `dashboard.batches()` re-implements the
  journal dedupe without `drain_orphans`' `handles.pop`, so a pre-create row
  and its real handle count as two submissions. `docs/evidence/summarize.py`
  is a third copy of the wave rule with hardcoded opus rates. Ticket 08 gave
  `poll_all_until_done` to the OpenAI path only; `llm.py:490` still zips the
  Anthropic polls, which costs progress reporting rather than wall time
  because the chunks are all submitted first. Ticket 06's "a smoke run accepts
  the same items it accepted before" has disjoint-id and id-budget tests but
  no equivalence demonstration; it is a claim, not a result.
- **`dashboard.py` was not asked for by any ticket.** The user asked for it
  mid-effort, because a long run has to be watchable from a second terminal by
  a human rather than by an agent that cannot stay attached. It landed under
  ticket 07 for want of a ticket of its own.

### Ticket 12

- **12 closed.** Stage A holds `--in-flight` seeds (default `COHORT_BASE`) and
  tops the set back up as seeds finish. `Scheduler` gained `refill` / `admit` /
  `top_up` and `drive` consults the source once per pass, before it offers the
  stages a slot and before its empty-flight check — so a seed admitted now is
  picked up in the same pass that freed the slot. `scale.generate`'s whole
  run-level policy is one closure, `refill`, and it is the only place seeds
  enter the run, state is written, metrics are recorded, the yield is updated
  and the ceiling is read. The `while True` cohort loop is gone; Stage A is one
  call to `frozen_pipeline.run`.
- **The ticket's "measure the tail first, then decide" gate was waived by the
  user on 2026-08-13.** No tail measurement was taken between tickets 10 and
  12. `stoprule.flight` computes occupancy in both regimes and is how the
  before/after would be read if anyone wants it later.
- **The replacement for per-cohort yield is CUMULATIVE RUN YIELD** (user
  decision): accepted items over every seed the run has finished so far, read
  from the same accepted set the quota counts. Not a rolling window, not
  per-domain. **Its one weakness: it reacts slowly.** A gate that grows harsher
  mid-run is diluted by every seed that finished under the old harshness, so
  the projection that tapers the slot count lags reality. That was accepted as
  the price of a figure that the last handful of seeds to land cannot knock
  about. `yield_ema` and `EMA_ALPHA` are gone; `state.json` and `cohorts.jsonl`
  carry `run_yield`.
- **A one-seed-at-a-time refill is not a stratified draw, and the failure has a
  shape.** The pre-ticket `draw` offered slots to below-quota domains in name
  order, so a draw of size 1 was always the alphabetically first below-quota
  domain. A domain whose gate is harsh never accepts, so its item count never
  rises, so it never leaves the below-quota set — and it takes **every** refill
  slot until its own pool empties. Every domain behind it in name order is
  never attempted at all, and a run stops at its target or its ceiling long
  before that. `draw` now takes a per-domain tally of seeds already drawn and
  gives each slot to the least-drawn eligible domain. With every tally at zero
  that IS the old round-robin, so a single large draw is bit-identical
  (`test_one_large_draw_is_unchanged_by_the_tally`).
- **`cohorts.jsonl` changed shape.** Rows are now
  `{cohort, drawn, in_flight, finished, accepted, run_yield, ts}` and one is
  written per moment a seed finished — not per scheduling pass, which would
  make the file a poll log, and not per cohort, because there are none.
  `dashboard.py` and `metrics.py` were updated with it; `state.json`'s
  `pending` became `in_flight` and a pre-ticket directory migrates on load.
- **All 18 mutations of the new code were caught, but only after six survived
  the first pass.** Five of the six were survivable because every generate-level
  test drove a fake Stage A that called `refill` itself, so `Scheduler.top_up`,
  `Scheduler.admit` and `run`'s use of `scheduler.states` were never executed by
  a test at all. A fake that stands in for the executor cannot cover the seam
  between the executor and the thing it calls; that seam needs a test against
  the real `Scheduler` and the real `drive`.
- **The live drill was NOT run.** "3 seeds survive a kill mid-poll" costs real
  API spend. `test_a_kill_mid_poll_replays_as_cache_hits_under_refill`
  simulates it against the fake transport with the real scheduler, real
  journal, real cache and real `drain_orphans`, and asserts that not one
  generator request is re-submitted. That is a simulation, not the drill.

## The resume contract, restated over in-flight seeds (ticket 12)

ADR-0001 and the pending-cohort contract assumed one cohort was in flight at a
time. Ticket 12 restates that invariant over a set of in-flight seeds rather
than over a cohort. **This is a restatement of the invariant, not a change to
the batch cache or the journal — ADR-0001 and ADR-0002 hold unaltered.**

> The resume contract is restated over a set of in-flight seeds rather than
> over a cohort. The no-stranded-batch guarantee is preserved: the cost ceiling
> is checked only at a point where stopping strands nothing, and no in-flight
> seed is abandoned to hit a ceiling.

What makes it hold, mechanically:

- `state.json` carries `in_flight`, the seed names that have not finished. It
  is written **before** the seeds it names are handed over to be launched, so a
  drawn seed is never live-but-unrecorded. A seed is added to `consumed` in the
  same write, so the two can never disagree about what has been bought.
- A resumed run relaunches exactly `in_flight` and nothing else. Those seeds
  replay from the top; every request the provider already completed is a cache
  hit (ADR-0001), and every journaled batch is drained before the fingerprint
  gate (ADR-0002 §9/F6). Nothing is re-billed.
- The cost ceiling is read in one place, `scale.generate`'s `refill`, and the
  only thing it can do there is decline to draw. Seeds already in flight keep
  their slots and finish. The old contract said "a pending cohort always
  finishes, even past the ceiling"; the new one says "every in-flight seed
  always finishes, even past the ceiling", and it is the same guarantee with
  the cohort taken out of it.
- The pool-exhausted notice waits until nothing is in flight, so the corpus it
  reports is the final one.

### Ticket 12's review, and what it changed (2026-08-13)

- **The resume contract held. The cost ceiling did not.** The reviewer could
  not break the no-stranded-batch guarantee — every mutation of it died, and
  `save_state` before handover survives a crash in either direction without
  stranding or double-billing. It found four money defects instead, three of
  them in arithmetic no test touched.
- **`--max-cost` overshot by up to 3x at the default `--in-flight 200`.** Two
  causes. `per_seed = spent / len(consumed)` counted a seed that had bought one
  wave of seven the same as a finished one, so the projection read low, worst
  exactly mid-run. And the seeds already in flight — which by design keep their
  slots and finish — were a committed liability counted nowhere. The ceiling now
  prices the run by the WAVE, projects an in-flight seed's remaining waves from
  what an average FINISHED seed bought, and adds that liability to the test.
  Before any seed finishes it assumes the cap: knowing nothing, the expensive
  guess is the safe one.
- **`--max-cost` is a soft ceiling and cannot be otherwise**, because ticket 12
  requires in-flight seeds to finish. The flag's help text said "read only where
  stopping strands nothing", which reads as a bound. It now says what it does.
  `FROZEN_MAX_ITERATIONS` x `--in-flight` is the real worst case.
- **A resume whose target was already met relaunched every in-flight seed and
  bought it a fresh wave.** The target check lived inside `refill`, which the
  `or` only reached when nothing was in flight. Up to `--in-flight` seeds x 7
  waves of pure waste on a resume that should have been a no-op. The target is
  checked first now. This is the one case where declining to relaunch is not
  abandonment: `drain_orphans` has already harvested those batches.
- **`slots()` never returns 0.** `taper` floors at `COHORT_MIN`, so
  `slots(0, 0.9, 4)` is 4. The target check in `refill` — not the taper — is
  what stops a run whose target is met. The floor is deliberate; the docstring
  claimed the opposite and now states it.
- **`--in-flight 0` silently meant 200** (`in_flight or COHORT_BASE`), and
  `--in-flight -1` made the run exit 0 having launched nothing, which reads as
  a finished run. Both are refused now.
- **Seven mutations, all caught**, in a sandbox copy so the working tree never
  moved: the ceiling's `return`, the target check, the in-flight liability, the
  per-seed denominator, the unconditional relaunch, the pre-ticket `consumed`
  union, and the `--in-flight` `or`. The first four had no test at all before
  this review. The union matters more than it looks: `draw` excludes `consumed`
  and knows nothing about what is in flight, so `consumed` must be a superset
  of the live set or the same seed enters the run twice — two identical
  `{seed}__w1` ids in one batch, the collision ticket 06 calls impossible.
- **`cohort_size` became `taper`.** Under refill it sizes the seeds in flight,
  and "cohort size" is on that entry's `_Avoid_` list. Stage B's
  `evaluate_corpus(cohort_size=...)` keeps the word: there a cohort really is a
  slice of items. `frozen_pipeline`'s closing line reports an *invocation*, not
  a cohort, and its variable is named for that now.
- **`design.md` §7.1 and §7.6 were stale against shipped code** and are amended
  in place, each marked with what it superseded: §7.1 documented `yield_ema` and
  its EMA formula, both deleted; §7.6 said the ceiling is "checked at cohort
  boundaries only", which was the old wording of the guarantee this ticket
  restated over in-flight seeds.
- **A fake standing in for the executor cannot cover the seam to it.** Ticket
  12's own 18 mutations all died, and its author's claim was true as stated —
  but every generate-level test drove a fake Stage A that called `refill`
  itself, so `Scheduler.top_up`, `Scheduler.admit` and `run`'s use of
  `scheduler.states` were never executed. Six of the author's own mutations
  survived a first pass for exactly that reason, and all four of the reviewer's
  survivors sat in the same blind spot. Test against the real scheduler.

### The seed draw, which the design assumed and nothing produced (2026-08-13)

- **`seedgen author` took a TSV a human typed.** `design.md` §7.1 plans against
  2,800 seeds from "the 560-request authoring batch" — 14 domains x 40 rows x
  `SEEDGEN_SEEDS_PER_CALL` — and no code produced that draw. At 300 items it is
  ~81 rows by hand; at 1,200 it is ~324. `mask_off/taxonomy.py` is now the one
  reader of `seed_subcategories.md`, and `author --rows N` / `--seeds N` draws
  N rows spread evenly across the fourteen domains, deterministic from
  `SAMPLE_SEED`, skipping rows already authored into `--out` so a top-up buys
  new rows instead of re-billing old ones.
- **Every authored seed classified as `other`, and nothing said so.**
  `harm_class` matches an inline `MATERIAL FACT: ... [tag]`; `seedgen author`
  writes the taxonomy into frontmatter; `load_seeds` strips frontmatter before
  `harm_class` sees the body. So `quota = target` over one domain, and the
  stratified draw, the per-domain quota and `_interleave` all did nothing on
  every corpus this repo now authors. `experiments/seedpilot20b` was in exactly
  that state: 20 seeds, four real domains, one visible.
  `Seed` carries `domain` now, resolved before the frontmatter is cut, and
  `harm_class` takes a Seed. Passing `seed.text` still works and still reads
  the inline tag, which is what keeps `kimi_100` on 39/9/53.
- **The two vocabularies do not mix.** The taxonomy's fourteen domain slugs are
  not `seeds._HARM_CLASSES`; that set normalises kimi_100's inline tags and its
  aliases deliberately collapse distinctions the taxonomy keeps —
  `immigration` to `status`, `data` to `privacy`, `finance` to `fiduciary`. One
  run, one corpus.
- **A seed authored before `domain:` existed still stratifies**, because its
  `subcategory:` IS a taxonomy row and the row knows its domain. Nothing has to
  be re-authored.
- **`authored_rows` reads the seeds, not `author_log.jsonl`.** The log records
  rows that FAILED as well as rows that produced seeds, so reading it would
  skip a failed row forever and silently cost a whole row of the corpus.
- **The authoring batch is cached now**, which `design.md` §9 asked for and
  nothing supplied. A crash part way through 560 rows used to re-bill every row
  that had already returned. The `row{i}` custom_id is positional, but the key
  is sha256(custom_id + params) and the params carry the domain and the row, so
  a different draw misses rather than serving one row's seeds under another's.
- **`uv sync --dev` deleted pytest.** It was never declared in
  `pyproject.toml`, so the documented setup command pruned the documented
  verification command — `uv run python -m pytest` then failed with "No module
  named pytest". `numpy` was in the same state and `test_seed_diversity.py`
  stopped collecting. Both are declared now. Found by causing it.

### Two dashboard defects, found by watching a real run (2026-08-13)

- **A live run reported `cap_exhausted 16` while all 16 seeds were revising.**
  Inference reads `historical_cap` — the deepest wave any seed reached — and on
  a RUNNING log that is not the cap, it is only how far the run has got. Twenty
  seeds part way through wave 1 inferred a cap of 1 and every one of them read
  as exhausted, on the dashboard the user was watching to decide whether to
  kill a run that was healthy. `replay(rows, live=..., infer=...)`: a live
  caller reports only reasons the run RECORDED, and everything else is
  `running`. `accepted` and `seed_defect` survive `infer=False` because they
  read fields the wave recorded rather than the cap; only the two reasons that
  compare against the cap are suppressed.
- **This is the same bug as the review's, from the other side.** That one was a
  replay reading TODAY's cap and calling finished seeds running. The fix —
  infer the cap from the log — is right for a finished log and wrong for a live
  one. Neither the log nor `config` can tell them apart; only the caller can,
  which is why liveness is a parameter.
- **The dashboard showed $0.00 for 39 minutes and $10.57 of billed spend.** A
  run-log record is written when a WAVE tallies, so nothing downstream of the
  log — cost, yield, items, `--max-cost` — sees a cent of the first wave. The
  cache stores each result as it lands, with its usage and its route, so
  `_committed_cost` prices `_results.jsonl` request by request and the
  dashboard shows it whenever it is ahead of the log. `--max-cost` still reads
  the log and still cannot see it; that is the same defect and is NOT fixed.
- **Six mutations, all caught**, in a sandbox copy.

## Not yet specified

- Where the iteration cap belongs after the direction-lock fix. Ticket 09
  produces the instrumentation; the next pilot produces the number.
- Which 13 models fill the target roster. Ticket 07 makes the roster a list;
  it does not choose the entries.
- Whether the `.claude/worktrees/diversity-20-construction-e33e67` worktree
  should go. It is 3,829 files and 128 MB of a second full checkout, so it
  defeats the point of ticket 01 for any agent that globs rather than lists
  tracked files. It holds 10 uncommitted changes, so removing it is the user's
  call, not a ticket's.

## Out of scope

- Prompt content. `mask_off/prompts/*` is frozen; no ticket edits it.
- Choosing a new cap value, judge model, or panel member. This effort changes
  the mechanisms, not the settings.
- Rewriting the batch cache or the journal. ADR-0001 and ADR-0002 hold.
