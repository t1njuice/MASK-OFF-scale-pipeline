# 0002 — Choose diversity metrics from the claim, not the literature's defaults

Date: 2026-08-09 · Status: active · Supersedes: 0001 · Lesson: 0003

## Insight
The paper's diversity claim is categorical ("spans domains, user/assistant roles, tones"), so headline metrics must be label-based: per-dimension coverage vs. a pre-frozen taxonomy (variety), effective number of categories / Hill q=1 (balance), pairwise Cramér's V + joint-cell coverage (independence), judge-vs-human κ (label validity). Text-dispersion metrics (Self-BLEU, Vendi, embedding distances) don't speak to the claim — they survive only as a within-cell near-duplicate audit.

## Final battery (chosen 2026-08-09)
One metric per axis, nothing more: facet tables + effective number (categorical, headline) · Self-BLEU (lexical) · POS compression ratio (syntactic, Shaib `diversity` package) · Vendi Score on embeddings (semantic, doubles as near-dup audit via top nearest-neighbor pairs). All text metrics vs. baseline at matched N.

## Execution plan (finalized 2026-08-09)
1. Freeze the four facet taxonomies (domain, user role, assistant role, tone) before labeling; justify taxonomy construction + disparity in an appendix.
2. Label: domain from `taxonomy` field; judge labels the rest; judge-vs-human κ per facet on an author-labeled sample.
3. Measure the seed pool first (facet tables + Hill q=0/q=1); fix thin facets at the seed stage.
4. Measure the released set with the full battery (see above).
5. Pipeline audit: per-category seed count / released count / acceptance rate; pairwise Cramér's V; stated gaps.
Kept separate: lowercase/dashes style effect → discussion note or pre-declared exploratory item in ANALYSIS_PLAN.md, never a diversity row.

## Decision it drives
Datasheet diversity section = per-dimension coverage/effective-number/κ rows + Cramér's V matrix + near-dup audit + HELM-style stated gaps. Taxonomies for user role and tone must be frozen before any labeling run. Framework source: Stirling decomposition (arXiv:1902.09167).

## Revisit if
The frozen doc's Vendi rows conflict with this table (decide keep-as-appendix vs. drop), or a reviewer demands a text-dispersion number anyway.
