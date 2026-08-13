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
