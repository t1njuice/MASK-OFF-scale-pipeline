# Agreement standards for the judge-vs-author validation

Ticket 002. Research note for the annotation-validation plan.

Setting: an LLM judge labels all ~1000 scenarios on four categorical
facets (domain ~14 categories, user role, assistant role, emotional
tone). Two authors hand-label a random sample of n scenarios. The
paper reports Cohen's kappa (judge vs. author) per facet.

Definitions used below:

- **Cohen's kappa (kappa)**: agreement between two raters, corrected
  for the agreement that chance alone would produce (Cohen 1960).
- **P_o**: observed agreement — the fraction of items where the two
  raters give the same label.
- **P_e**: chance agreement — the agreement expected if both raters
  labeled at random with their own label frequencies.
- Kappa = (P_o − P_e) / (1 − P_e).

---

## (a) What kappa threshold counts as acceptable

### The benchmark scales reviewers cite

Landis & Koch (1977, p. 165) give the scale that almost every
reviewer knows:

| Kappa | Strength of agreement (Landis & Koch) |
|---|---|
| < 0.00 | Poor |
| 0.00–0.20 | Slight |
| 0.21–0.40 | Fair |
| 0.41–0.60 | Moderate |
| 0.61–0.80 | Substantial |
| 0.81–1.00 | Almost perfect |

Landis & Koch themselves call these cut points arbitrary. They are
"clearly arbitrary" divisions offered as benchmarks, not derived
limits. Reviewers still use them.

Krippendorff (2004) gives a stricter, more principled scale for
content-analysis data. It is stated for his alpha coefficient, but
the community applies it to kappa-family coefficients in general:

| Alpha / kappa | Krippendorff's reading |
|---|---|
| >= 0.800 | Reliable. Draw conclusions from the data. |
| 0.667–0.800 | Tentative conclusions only. |
| < 0.667 | Discard. Do not use the data. |

### The conventional pass bar in NLP annotation

Artstein & Poesio (2008), the standard survey for computational
linguistics, review both scales. Their conclusion: 0.8 is a good
overall bar, but no single cutoff fits every task; coefficients
above 0.6 have supported useful annotation work, and the cutoff must
be argued for the task at hand. In practice, NLP papers treat
kappa >= 0.67 as the floor and kappa >= 0.8 as the "good" mark.

Recent LLM-as-judge work lands in the same region. Zheng et al.
(2023, MT-Bench) validate GPT-4 as a judge because it agrees with
humans at the human-human agreement level (~80%+ raw agreement).
Follow-up work (e.g. arXiv:2606.00093) warns that raw percent
agreement overstates judge quality and asks for chance-corrected
coefficients — which is exactly what kappa is.

### Recommendation

- **Target: kappa >= 0.80 per facet** ("almost perfect" on Landis &
  Koch; "reliable" on Krippendorff). Report this as the pass bar.
- **Floor: kappa >= 0.67.** A facet in 0.67–0.80 passes with a
  stated caveat (tentative, per Krippendorff). A facet below 0.67
  fails; the judge prompt or the taxonomy must be revised.
- Also report the author-vs-author kappa on a shared subset. It is
  the ceiling. A judge cannot beat the humans' own agreement, and
  reviewers will ask for this number.

---

## (b) What sample size n out of 1000

### The standard-error reasoning

The large-sample standard error of kappa (Fleiss, Cohen & Everitt
1969; simple form as used by Sim & Wright 2005) is approximately:

    SE(kappa) ≈ sqrt( P_o (1 − P_o) / n ) / (1 − P_e)

A 95% confidence interval is kappa ± 1.96 × SE. We want a half-width
of about ±0.05, so a kappa of 0.80 is distinguishable from the 0.67
floor.

Worked numbers, using the hardest facet (domain, ~14 categories) and
assuming the target kappa = 0.8:

- With ~14 categories and some skew, chance agreement is low. Take
  P_e = 0.20 (conservative; balanced categories give P_e ≈ 0.07).
- Then P_o = kappa × (1 − P_e) + P_e = 0.8 × 0.8 + 0.2 = 0.84.
- SE = sqrt(0.84 × 0.16 / n) / 0.8 = 0.458 / sqrt(n).

| n | SE(kappa) | 95% CI half-width |
|---|---|---|
| 100 | 0.046 | ±0.090 |
| 200 | 0.032 | ±0.063 |
| 300 | 0.026 | ±0.052 |
| 400 | 0.023 | ±0.045 |

Because we sample n from a finite set of 1000, the finite-population
correction sqrt((N − n)/(N − 1)) applies. At n = 300, N = 1000, the
correction is 0.837, so the real half-width is about **±0.043**.

Check on a low-P_e-unfriendly facet: suppose emotional tone has ~5
categories with one dominant, so P_e = 0.40. Then P_o = 0.88 and
SE = 0.325 / (0.6 sqrt(n)). At n = 300 the half-width is ±0.061,
or ±0.051 after the finite-population correction. Still adequate.

### Recommendation

- **n = 300** (30% of the set). This gives a 95% CI of roughly
  ±0.04–0.05 on every facet, tight enough to place each kappa
  cleanly above or below the 0.80 and 0.67 bars.
- n = 200 is a defensible minimum (±0.05–0.06). n = 100 is not: a
  ±0.09 interval cannot separate 0.80 from 0.67.
- Sim & Wright (2005) tabulate sample sizes for kappa hypothesis
  tests and reach the same order of magnitude: distinguishing
  kappa = 0.8 from a null of 0.6 at 80% power needs on the order of
  100–250 items per comparison, before any per-category demands.

### Stratification

Yes — stratify, on one facet. Draw the sample stratified by the
judge's **domain** label (the 14-category facet), with proportional
allocation plus a floor of **10 items per domain category**. Reasons:

- A simple random n = 300 gives a rare domain (say 2% prevalence)
  only ~6 items. Per-category error analysis is then impossible.
- Proportional allocation keeps the pooled kappa an (approximately)
  unbiased estimate of the full-set kappa; only the top-up items
  for rare categories deviate, and they are few. Report the pooled
  kappa on the proportional core if a reviewer objects.
- Do not try to stratify on all four facets at once. The cross of
  14 × roles × tone has too many cells for n = 300. Domain is the
  facet with the most categories, so it is the binding one; the
  other facets get adequate counts for free.

### The prevalence pitfall

When one category dominates a facet, kappa behaves badly. Feinstein
& Cicchetti (1990) show the two paradoxes: observed agreement can be
high while kappa is low (skewed marginals inflate P_e), and
asymmetric marginals can inflate kappa. This matters most for the
role and tone facets, where one label ("user is a private
individual", "neutral tone") may dominate.

Robustness checks to run alongside kappa:

- **Krippendorff's alpha** per facet. It handles unequal marginals
  on a different chance model, generalizes to more raters and
  missing labels, and is the coefficient Artstein & Poesio (2008)
  recommend for corpus annotation. If alpha and kappa agree, the
  result is solid.
- **PABAK** (prevalence-adjusted, bias-adjusted kappa; Byrt, Bishop
  & Carlin 1993) as a sensitivity number. A large gap between kappa
  and PABAK flags a prevalence artifact, not a judge failure.
- Always print the per-facet label distribution and the raw P_o
  next to kappa, so readers can see the prevalence situation.

---

## Summary of recommendations

1. Pass bar: kappa >= 0.80 per facet. Floor 0.67 with caveat.
   Report the Landis & Koch scale row for each result.
2. Hand-label n = 300 of the 1000, stratified by domain with
   proportional allocation and a 10-item floor per domain category.
3. Report 95% CIs on every kappa (SE formula above, or bootstrap).
4. Report Krippendorff's alpha and PABAK as robustness checks on
   skewed facets, plus raw P_o and label distributions.
5. Report author-vs-author kappa on a shared subset as the ceiling.

---

## Citations

- Cohen, J. (1960). A coefficient of agreement for nominal scales.
  Educational and Psychological Measurement, 20(1), 37–46.
  https://journals.sagepub.com/doi/10.1177/001316446002000104
- Landis, J. R., & Koch, G. G. (1977). The measurement of observer
  agreement for categorical data. Biometrics, 33(1), 159–174.
  https://pubmed.ncbi.nlm.nih.gov/843571/
- Fleiss, J. L., Cohen, J., & Everitt, B. S. (1969). Large sample
  standard errors of kappa and weighted kappa. Psychological
  Bulletin, 72(5), 323–327. https://doi.org/10.1037/h0028106
- Artstein, R., & Poesio, M. (2008). Survey article: Inter-coder
  agreement for computational linguistics. Computational
  Linguistics, 34(4), 555–596. https://aclanthology.org/J08-4004/
- Krippendorff, K. (2004). Reliability in content analysis: Some
  common misconceptions and recommendations. Human Communication
  Research, 30(3), 411–433.
  http://faculty.washington.edu/jwilker/559/Krippendorf.pdf
- Sim, J., & Wright, C. C. (2005). The kappa statistic in
  reliability studies: Use, interpretation, and sample size
  requirements. Physical Therapy, 85(3), 257–268.
  https://academic.oup.com/ptj/article-abstract/85/3/257/2805022
- Feinstein, A. R., & Cicchetti, D. V. (1990). High agreement but
  low kappa: I. The problems of two paradoxes. Journal of Clinical
  Epidemiology, 43(6), 543–549.
  https://pubmed.ncbi.nlm.nih.gov/2348207/
- Byrt, T., Bishop, J., & Carlin, J. B. (1993). Bias, prevalence
  and kappa. Journal of Clinical Epidemiology, 46(5), 423–429.
  https://pubmed.ncbi.nlm.nih.gov/8501467/
- Zheng, L., et al. (2023). Judging LLM-as-a-judge with MT-Bench
  and Chatbot Arena. NeurIPS 2023 Datasets and Benchmarks.
  https://arxiv.org/abs/2306.05685
- Anonymous (2026). Agreement measurement for rubric-based LLM
  judges: What to report and why. arXiv preprint.
  https://arxiv.org/abs/2606.00093
