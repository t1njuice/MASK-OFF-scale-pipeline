# Native OpenAI and Google batch adapters; OpenRouter batch demoted to fallback

**Status:** accepted 2026-08-12. Supersedes design.md §2 ("no native OpenAI/Google
batch adapters") and §5's openrouter_batch-first route table. Everything else in
design.md stands.

Facts below come from provider docs checked 2026-08-12. Sources are in the
research transcripts; the load-bearing ones are restated here.

## 1. Why the reversal

The OpenRouter Batch API turned out weaker than design.md assumed, and the
native batch products turned out stronger:

| Property | OpenAI batch | Google batch | OpenRouter batch |
|---|---|---|---|
| Age | years | years | **launched 2026-08-07 (beta, 5 days old)** |
| Partial results on expiry/cancel | returned and billed | none on expiry (48h); cancel unverified | **none — `results: null`** |
| Cancel endpoint | yes | yes | **not documented** |
| List/recover batches | yes, by id or list | yes, by name or list | by id only; no list endpoint |
| Result retention | ≤30 days | 6 weeks | 30 days |
| Discount | 50% all gpt-5.x | 50% | 50% for 55/60 slugs; **`gpt-5.6-terra:batch` and `terra-pro:batch` currently 1.0x (no discount)** |
| Provider pinning | native (moot) | native (moot) | not accepted |
| Structured outputs | json_schema strict per line | responseSchema per line | per-request unverified; Google slugs need one schema per batch |
| Caps | 50k requests / 200 MB | 2 GB file; enqueued-token quota | undocumented |

"No partial results" breaks the never-discard-batch-work rule structurally: one
expired OpenRouter batch forfeits every completed request in it. That risk is
acceptable nowhere in this pipeline.

## 2. Route table (Stage B, latency class "day")

Route stays price-driven from the pinned table in `config.py`. This is what the
lookup yields today:

| Model | Route |
|---|---|
| `claude-*` | `anthropic_batch` (native, unchanged) |
| `openai/*` | `openai_batch` (native, NEW) — needs `OPENAI_API_KEY` |
| `google/*` | `google_batch` (native, NEW) — needs `GEMINI_API_KEY` |
| kimi / grok / deepseek / qwen | `openrouter_sync` (no batch product exists) |
| any of the above with a missing native key | `openrouter_batch` fallback, only where its `:batch` price < sync |

`openrouter_batch` is built as an adapter (~150 lines behind a protocol that
must exist anyway) but is never first choice while native keys exist.

## 3. Latency classes (the iteration-turn decision)

Two classes, passed per call:

- **"wave"** — Stage A wave loop and any sequential iteration. Eligible routes:
  `anthropic_batch`, `openrouter_sync`. A 24h-window route is never eligible:
  five sequential waves through a 24h window is five days.
- **"day"** — Stage B cells, seedgen authoring. All routes eligible; cheapest wins.

Decision on the "middle" option (`openai/gpt-5.6-sol:batch` via OpenRouter for
iteration turns): **rejected.** The window is a flat 24h with no faster tier,
the terra-class slugs currently carry no batch discount at all, and expiry
forfeits partials. Non-Anthropic panel votes in the wave loop stay on
`openrouter_sync` at full price; that premium is the real cost of a sequential
gate, and wave sizes shrink geometrically so late waves are small anyway.

## 4. Interface (hybrid of the three design candidates)

Base: the caller-first design. Surface adopted:

- `run_batch_retry(requests, label, progress)` keeps its exact signature,
  exported from `llm.py`. The 13 experiment scripts and `pipeline.py` run
  unchanged, zero edits.
- An ambient `Policy` (contextvar: `run_dir`, `tolerance`, `strict`) set ONLY by
  `scale.py` via `with batch_providers.policy(...)`. Default `Policy()` is
  bit-identical to today's behavior. One writer, greppable.
- Adapter protocol: `submit / poll / fetch` over JSON-safe handle dicts.
  **The handle is the journal row** — `_batches.jsonl` stores it verbatim;
  `drain_orphans` re-polls it in any process. No rehydration API.
- Handles: anthropic `{batch_id}`; openai `{batch_id, input_file_id}` (+
  `output_file_id` enriched at poll); google `{operation_name}`; openrouter
  `{batch_id}`; sync `None` (a crash loses in-flight sync calls; only
  `_results.jsonl` rows already appended survive — stated, not hidden).

Adopted from the minimal design: no Ticket/submit-now-harvest-later API.
Process death IS the async mechanism: the journal plus `drain_orphans` plus the
cache make "kill the run, harvest tomorrow" work with zero extra surface.

Adopted from the flexible design: submit-time failures (cap exceeded, schema
rejected, no eligible route) always raise regardless of strictness — there is
no correct silent behavior for a programmer error.

Rejected: `cost_guard` hook inside the seam (design.md §7.6 checks cost at
cohort boundaries in `scale.py`; the seam does not need a policy slot for it);
per-request route overrides (config-level `ROUTE_OVERRIDES` suffices).

## 5. No-loss invariants

1. `on_submit(handle_row)` fires after each provider accepts a group and before
   the next group submits. The unjournaled-but-billed window is one group max.
2. `on_result` appends each result to `_results.jsonl` before it becomes
   visible in the return value. Durability precedes visibility.
3. **Retry-once lives below the cache.** The cache stores only post-retry
   finals, so a truncated result can never become a permanent cache hit.
4. KeyboardInterrupt with a run_dir set: journaled batches are left running and
   a drain hint prints. Cancel is only for uncached legacy mode.
5. Expired/canceled OpenAI batches: harvest the output file BEFORE resubmitting
   the remainder — partials are returned and billed.
6. Result files self-delete (OpenAI ≤30d, Google 6 weeks, OpenRouter 30d).
   `drain_orphans` runs at every process start, so drift toward these deadlines
   only happens if nobody re-invokes the run at all.
7. Request builders stay deterministic (ADR-0001); nothing in the new module
   adds timestamps or unsorted dicts to params.

## 6. Structured outputs

- Callers keep building Anthropic-shaped params; `message_params` always
  attaches `output_config.format` when given a schema. Translation is adapter
  work: OpenAI/OpenRouter `response_format` json_schema strict; Google
  `responseSchema`; Anthropic passthrough (the `STRUCTURED_OUTPUT_MODELS` check
  moves behind the seam, where the route is known).
- Per-line failure modes the harvester checks on OpenAI: `refusal` field
  (status 200!), `finish_reason: "length"` (truncated JSON — strict schema does
  not protect against truncation), `content_filter`, non-200 `status_code`.
- Parse-level bounded resubmission (`resubmit_votes`, ≤3 passes, `short_votes`
  flag) stays caller-side — parsing is caller knowledge. It composes with the
  cache because errored slots are never cache hits.
- Reasoning models: budget `max_tokens` generously — reasoning tokens consume
  the output budget before any JSON is emitted.

## 7. Prompt-cache optimization per route

Cache spend concentrates on the shared-prompt roles (generator, validity panel,
judge — one ~10K-token system prompt each, reused across items and waves).
Target requests have per-item system prompts, so cross-item caching there is
near zero by construction; do not engineer for it.

- **Anthropic:** keep the 1h-TTL breakpoint from `message_params`. Within one
  batch, hits are opportunistic (parallel workers); across waves the 1h TTL is
  the win. A wave gap > 1h re-pays the 2x write — cost fact, not a bug.
- **OpenAI:** automatic prefix caching applies inside batch, and the cached
  rate stacks with the batch rate (batch price table lists a cached-input
  column: sol batch $2.50 in / $0.25 cached). Minimum prefix 1,024 tokens.
  GPT-5.6 cache writes cost 1.25x. Nothing to configure; keep prefixes stable.
- **Google:** implicit caching in batch is unguaranteed. If a shared-prompt
  role ever runs on Gemini: create an explicit `cachedContent` (min 4,096
  tokens, TTL 172800s = 48h to survive the queue; ~$0.48 per 10K tokens per
  48h) and reference it per JSONL line. Cached tokens bill at ~10% of standard
  input INSTEAD of the batch rate — the discounts do not multiply. Not built
  until a Gemini model actually lands in a shared-prompt role.
- **openrouter_sync:** keep `provider.order` + `allow_fallbacks: false` pinning
  (closes cache fragmentation across hosts AND the fp4-quantization drift).
  Kimi/DeepSeek/Grok auto-cache; reads 0.1–0.25x.
- **All batch adapters:** sort request lines by `(model, schema_hash,
  system_prefix_hash)` before writing the file. Free; helps file-order
  processors; also implements the Google one-schema-per-batch partition.
- **Usage convention U:** `usage.input_tokens` EXCLUDES cached tokens on every
  route (Anthropic convention). Adapters over OpenAI-convention counts
  subtract `cached_tokens` out of `prompt_tokens`. This fixes a live bug: the
  current OpenRouter shim double-counts cached input in `usage_cost`.

## 8. Fail-early at the pilot

- The ~100-item pilot runs `policy(strict=True)`: first schema rejection,
  cap violation, or provider 4xx raises with custom_id + route + detail.
  The 1200 run flips one flag.
- Before the pilot: a 2-request canary batch per NEW adapter (openai_batch,
  google_batch) verifying submit → journal → poll → fetch → parse round-trip,
  and one kill-mid-poll → `drain_orphans` recovery.
- Per-route error counts print at completion even in non-strict mode. Silence
  is never a success signal.

## 9. Review amendments (2026-08-12, adversarial review)

Binding changes from the whole-design review. Numbers reference the review's
findings (F1–F10).

**Cache contract (F1).** The cache key cannot see "successful but unusable"
results, so the contract gains three rules:
1. The cache never stores `None` and never stores a final whose
   `stop_reason == "max_tokens"`.
2. `cached_batch` accepts a per-call refresh set of custom_ids that bypass the
   cache and supersede the stored row. `resubmit_votes` passes the ids it
   resubmits; Stage B top-up passes its holes. Without this, a cached
   unparseable vote makes `resubmit_votes` a permanent no-op and silently
   tightens the gate from 2-of-3 to 2-of-2.
3. Duplicate keys are latest-wins, both at `_results.jsonl` load and in the
   in-process dict.

**Determinism fixes (F2) — prerequisites for ADR-0001 being true:**
- `validity.py:tally` breaks scope ties by set iteration order, which varies
  per process under hash randomization, and the tied scope feeds the next
  wave's feedback text. Fix: deterministic tie-break over sorted scopes.
- `result_id` is a fresh uuid at accept time, so a replay-from-top
  double-accepts a seed under a second identity with a cold eval grid. Fix:
  seed done-state from `accepted.jsonl` at startup (ADR-0001's "no per-seed
  state on disk" gets this carve-out: `accepted.jsonl` already is that state).

**Fingerprint (F3).** `FROZEN_GENERATOR_PROMPT` is a filename; hash the
resolved prompt file contents instead, and add the validity reviewer prompt
contents and the seed corpus hash to the fingerprint.

**Policy read-once rule (F5).** `ThreadPoolExecutor` workers do not inherit
contextvars. The Policy is read once at `run_batch_retry` entry on the calling
thread and passed explicitly downward. No adapter or pool worker reads the
contextvar. `policy()` resets its token on exception.

**Scope cut for the 08-13 rehearsal (F8).** The rehearsal ships on the two
existing routes only: batch cache + journal + drain + `scale.py` Stage A +
Stage B replay-fill. `openai_batch` lands after the rehearsal behind its
canary (at 50 items the discount is noise). `google_batch` is deferred until a
`google/*` model is actually rostered. `openrouter_batch` is cut; the
missing-native-key fallback is `openrouter_sync`, never a route whose expiry
forfeits partials (this fixes §2's own contradiction with §1).

**Journal hardening (F6):** an intent row (label, custom_ids, route) is
journaled before submit and the handle row after accept; drain warns on
intent-without-handle. The OpenAI two-step submit dedupes off the intent row.
Enriched-handle rows dedupe by batch id, latest-wins. Drain uses the journaled
`route` field, never re-runs `route(model)`. Drain runs BEFORE the fingerprint
gate (harvest is always safe; the fingerprint gates new submissions only). A
drain that lacks the route's key is a loud run-blocking warning under strict.
A pid lockfile guards against two invocations on one run directory.

**Stage B `--fill` (F7).** The `only=` request filter is dropped. Fill is
replay-from-top with cache on: filled cells are free hits, holes are misses,
and the judge request is rebuilt from the full cache-merged response set — a
changed response set correctly produces a new judge key. Cohort eval rows are
recomputed from the grid, not appended. Empty-text cells count as holes in
coverage-per-model.

**Cost accounting (F4).** `usage_cost`'s claude-only pricing becomes wrong the
moment OpenAI traffic bills on a native key. Before the 300-run: per-model
per-route price table (batch and sync rates, cached-token rates), convention-U
normalization, and `usage.model` mandatory in the stored value. `--max-cost`
is fiction until this lands.

**OpenAI quota (F9).** Check the org Limits page before the rehearsal.
Enqueued-quota-exceeded at submit is a chunk-smaller-and-retry path, not a
raise. Size Stage B per-model sub-batches from the measured quota.

**Verify before writing `openai_batch` (F10):** whether a batch input file
must be single-model (likely — partition by model, not sort). Do not budget
savings on line-order cache adjacency. Metrics surface cache-write ratio per
wave so a >1h wave cadence re-paying the 2x write is visible.

## 10. Open hazards

1. **`openai/gpt-5.6-terra-pro` (judge candidate) does not exist as a native
   OpenAI model** — only `gpt-5.6-sol-pro` does. The slug exists on OpenRouter
   (likely a reasoning-mode composite) with NO batch discount today. If the
   judge bake-off picks it, the judge runs sync at full price; re-check the
   cost table before deciding. `claude-opus-4-8` batch stays the cheap judge.
2. OpenAI enqueued-token quota per model is org-tier-specific — read the org
   Limits page before sizing Stage B cohorts.
3. New-model launch windows have returned transient `model_not_found` on
   OpenAI batch (all gpt-5.6 slugs, July 2026, ~48h). Treat as retryable.
4. OpenAI batches occasionally hang in `finalizing` — the poller needs a
   wall-clock ceiling, not only a status check.
