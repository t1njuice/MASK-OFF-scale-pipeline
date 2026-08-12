---
id: 002
title: Agreement standards and sample size
type: research
mode: AFK
status: closed
assignee: claude (subagent, 2026-08-09)
resolved: 2026-08-09
blocked-by: []
---

## Question

Two facts from peer-reviewed literature: (a) what κ (Cohen's kappa) value counts as acceptable agreement for annotation labels in NLP work — the thresholds reviewers cite; (b) what sample size gives a representative agreement estimate when the full set is ~1000 scenarios.

Deliverable: a recommended κ threshold with citations (expect Landis & Koch 1977, Krippendorff, Artstein & Poesio 2008), a recommended sample n with the confidence-interval math, and whether the sample should be stratified by facet category. Report to `diversity/research/agreement-standards.md`. Append citations to `diversity/LITERATURE.md`.

## Resolution

- Pass bar: κ ≥ 0.80 per facet (Landis & Koch "almost perfect"; Krippendorff "reliable"). Floor: 0.67 — a facet between 0.67 and 0.80 passes with a stated "tentative" caveat; below 0.67 fails (Artstein & Poesio convention).
- Sample: n = 300 of the 1000, stratified by the judge's domain label, proportional allocation, minimum 10 items per domain category. At κ = 0.8 this gives a 95% CI of about ±0.05 (±0.043 with the finite-population correction), which separates 0.80 from the 0.67 floor. n = 100 (±0.09) cannot.
- Robustness on skewed facets (role, tone): also report Krippendorff's α and PABAK, plus raw agreement and label distributions. Report author-vs-author κ as the ceiling.
- Full report: [research/agreement-standards.md](../../research/agreement-standards.md). Ten citations appended to [LITERATURE.md](../../LITERATURE.md).
