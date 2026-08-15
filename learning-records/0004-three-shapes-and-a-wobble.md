# 0004 — Twelve diversity statistics are three shapes and one wobble

Date: 2026-08-14 · Status: active · Lesson: 0003

## Insight
The workstream's metric list looks like twelve unrelated things to learn. It is three
recurring forms plus an orthogonal precision statement:

1. **Effective count**, `exp(entropy)` — Hill q=0, Hill q=1, Vendi Score.
   Vendi is *the same arithmetic as Hill q=1*, run on the eigenvalues of a similarity
   matrix instead of on category counts. Hill needs labels; Vendi does not. That is
   the whole difference, and it is why the categorical rows do not make the semantic
   row redundant.
2. **Chance-corrected agreement**, `(observed - expected)/(1 - expected)` — Cohen's
   kappa, PABAK, Krippendorff's alpha. The three differ only in how they model chance.
3. **Closeness**, a 0-1 ratio — cosine, Self-BLEU, POS compression ratio, Cramer's V,
   confusion-pair share. They differ only in what counts as a "thing".

The **wobble** (bootstrap confidence interval) sits on top of any of them and is not a
fourth shape.

## Two corrections this record pins down
- A 95% confidence interval is a claim about the **procedure**, not about the interval
  in hand. "95% of intervals built this way would cover the truth" is defensible;
  "95% probability the true value is in this interval" is not, because the true value
  is fixed. This changes what may be written in the paper, not only how it is read.
- Kappa is computed **per axis** (beneficiary, institution, standing) and never pooled.
  Three reasons: a menu defect lives in one axis; the joint sentence label spans 120
  cells so its kappa tracks the weakest axis by construction; and the gate is per
  facet, so one axis can fail without taking the others with it.

## Decision it drives
- When a kappa comes back low, read the **confusion pairs before blaming the raters**.
  Concentrated disagreement (one ordered pair at >= 30%) is a menu defect. Scattered
  disagreement is the noise kappa exists to absorb.
- When a kappa is low on a skewed axis, read PABAK and the label distribution beside it.
  Low kappa with high agreement is the prevalence paradox, not rater failure — and the
  `standing` axis (71% `current`) is already in that regime.
- Never quote a pilot-sized (n=26) bootstrap interval as a result. Percentile-bootstrap
  coverage is asymptotic.

## Revisit if
The binding n=300 interval straddles the 0.80 gate. The rule is already pre-declared
(gate on the point estimate, report the interval), so the correct response is to
report the straddle, not to re-cut the sample.
