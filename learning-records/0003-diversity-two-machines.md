# 0003 — Diversity is a construction machine and a measurement machine, joined at kappa

Date: 2026-08-14 · Status: active · Builds on: 0002 · Lesson: 0002

## Insight
The workstream reads as one topic and executes as two independent machines.
**Construction** (`mask_off/`) forces spread into the corpus while it is authored:
balanced row draw, rotating 5-of-9 trigger-family window, name pool without
replacement, embed-flag-regenerate at cosine 0.90. **Measurement** (`diversity/`)
labels the finished corpus and counts the spread. They share no code path.

The hinge is that Machine B emits two kinds of number and they are not peers.
Cohen's kappa is a **gate** on whether the labels mean anything; Hill numbers are
the **result**. A Hill number on labels that failed kappa is not a weak result, it
is not a result. This fixes the execution order: freeze the menu, freeze the
sample, label twice, gate on kappa, only then count.

Second-order point: role spread is the one facet that is measured but never
engineered. Domain, trigger family, and entity names are all forced at the seed
stage; the three role axes are observed after the fact.

## Decision it drives
- Never run `hill.py` on a label set before `kappa.py` passes on it.
- The 209-item scan (`out/scan/`) is a smoke test for the measurement code, not a
  citable number: it pools many pipeline variants.
- Standing is the weak axis today (coverage 4 of 4, effective 2.01, 71% `current`).
  If the frozen corpus repeats that shape, report it as a stated gap rather than
  engineering the axis, because engineering it would make the measurement circular.

## Open gap this record names
Self-BLEU, POS compression ratio, Vendi Score, Cramer's V, and the verb-object task
extraction have **no code in the tree**. They are the lexical, syntactic, semantic,
and independence rows. Record 0002 already demoted them below the categorical rows,
so this is sequencing rather than slippage — but the schedule to Aug 29 must carry
them explicitly.

## Revisit if
The binding 300-item kappa run fails on any axis (the menu, not the raters, is the
first suspect), or a reviewer demands a text-dispersion number before the frozen
corpus exists.
