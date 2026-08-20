# 0007 — The 500 is two pools, disjoint seeds

Date: 2026-08-14 · Status: active, **amended 2026-08-20** · Builds on: 0006 · Lesson: pending

> **Amendment, 2026-08-20 (user).** Two of this record's premises were wrong
> and one of its consequences is withdrawn.
>
> **The generator was never opus-4-8.** `GENERATOR_MODEL` has been
> `moonshotai/kimi-k3` since before any released item existed (checked at
> `691c6f8f`, the `dataset_v1.jsonl` freeze; `git log -S GENERATOR_MODEL`
> touches the constant twice, both in early setup). So the two pools were
> never two generators, and the "P1 panel" phrase describes a panel this
> repo never ran for a released item.
>
> **The composition changed.** 400 pool A + 100 pool B, and pool B is
> doc-derived rather than generated. See `ANALYSIS_PLAN.md` §0.
>
> **The generator-variation ablation is dropped and will not run.** It had
> no carrier and none will be built. The objection it answered is answered
> instead from `diversity/research/generator-variation.md`, which found
> that seeds built by two different generators produce near-twins.

## The decision (user, 2026-08-14)

The released 500 (record 0006) is **300 items from the primary pipeline**
(~~opus-4-8 generator~~ — `moonshotai/kimi-k3`, see the amendment) **+ 200
items from a second run of that pipeline** (~~non-Claude generator~~ — the
same one; same seed spec, same panel). The two pools use **disjoint seed
subsets** — no released item shares a seed with an item from the other pool.
~~The 200 double as the cross-generator ablation arm (shared-understanding
§9), so the ablation stops being extra spend.~~ **Withdrawn 2026-08-20: the
ablation is dropped.**

## What it does to measurement

- **Diversity battery runs three times**: pool A, pool B, pooled 500. The
  per-pool numbers are the primary text-metric numbers. ~~Pooling two
  generators inflates Self-BLEU/Vendi mechanically (mixture, not craft);
  the pooled row carries that label.~~ **Amended 2026-08-20: there is one
  generator across pool A and none in pool B. The pooled inflation is real
  but its cause is stimulus construction — pool A's prompts average 159.5
  words against pool B's 61.2 — so the pooled row carries THAT label.**
- **Labeling frame**: one frame, n = 200, drawn once after both pools
  exist; stratified by pool at the corpus ratio (120/80) and by domain
  (10-per-domain floor). Binding κ is the pooled one; per-pool κ is
  descriptive (n = 80 carries ±0.10). Floor n = 150, and only with the
  finite-population estimand stated. Full numbers: amendment block in
  `diversity/research/agreement-standards.md`.
- **Near-duplicate audit** runs over the pooled 500. Disjoint seeds remove
  the cross-pipeline same-seed near-duplicate risk by construction.
- ~~**"Generator" is a facet**: a column in the pipeline audit table, and a
  variable in the independence checks.~~ **Withdrawn 2026-08-20.** It was
  never implemented and could not have been: it is constant across every
  generated item in the release. The audit-table column stays as provenance.

## The dependency this creates

Pool B must exist before the labeling frame is drawn (the frame is never
topped up — LABELING_DESIGN §10, kappa.py stamp discipline). If pool B is
late, the pre-declared fallback in `ANALYSIS_PLAN.md` §5 applies: binding κ
on pool A alone, pool B validated later in a separately-reported 40–60 item
addendum.

## Revisit if

The co-author rejects n = 200 at review of `ANALYSIS_PLAN.md`. ~~or the
cross-generator pipeline cannot reach 200 accepted items on its seed
subset~~ — **moot 2026-08-20**: the second pool is doc-derived and frozen
at 100, and the corpus definition was reopened and settled in
`ANALYSIS_PLAN.md` §0.
