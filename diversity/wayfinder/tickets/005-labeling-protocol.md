---
id: 005
title: Labeling protocol
type: grilling
mode: HITL
status: closed
assignee: claude + user (HITL, 2026-08-09)
resolved: 2026-08-09
blocked-by: [002, 004]
---

## Question

Settle the labeling protocol: (a) author labeling uses fixed options from the frozen taxonomy or free text — recommendation: fixed options plus one "other + note" escape, because free text cannot produce κ without a second mapping step; (b) sample size and stratification, from the agreement-standards research; (c) the judge prompt design (one facet per call or all facets per call); (d) the κ threshold that counts as a pass.

## Resolution (user-confirmed 2026-08-09)

1. Only user role is labeled (12 options + Other-with-note). Domain rides in from the seed; task is not labeled (descriptive-only, ticket 004 amendment).
2. Judge prompt: one call per scenario, single facet — reads `system_prompt` + `user_email`, returns role label + one-line justification.
3. Pilot: the 26 existing scenarios + a seed sample; Other-rate > 5% → one list revision → hard freeze.
4. Validation: n = 300 stratified by domain (min 10 per domain), both authors independent, plus a domain spot-check against seed labels. Pass κ ≥ 0.80; 0.67–0.80 with stated caveat; α and PABAK as robustness; author-vs-author κ as ceiling.
5. Bake-off (ticket 007): Opus 4.8 vs GPT-5.6 Terra on the 300; higher κ labels the full set.
