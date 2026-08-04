# Delete petri_bloom

Type: task
Status: open
Blocked by: 07

## Question

`git rm -r petri_bloom` once the pilot passes.

Deletion is deliberately last: if the pilot fails, petri_bloom-authored seeds
are the A/B arm, and deleting it early throws away the comparison.

Before deleting, confirm nothing outside the deleted tree still imports it and
that the two things worth keeping were ported by hand into
`mask_off/prompts/seed_brief.md` (ticket 02): `SCENARIOS_BATCH_PROMPT` and the
anti-clustering language in `SEED_DESIGN_SECTIONS`.

Everything else in the 4.7k-LOC tree — `_behavior/example.py` (985 lines),
`_evaluation/`, the viewer, the CLI, the registry, the async util, 12 test
files, the quarto docs, the CI workflows — was never used by this project;
`mask_off` does its own evaluation. It stays retrievable via `git show`, which
is what git history is for.

Also decide what happens to the generated behavior directories that petri_bloom
produced and that are now scattered across the repo root: `petri_v3`,
`petri_v3_fable`, `petri_v3_grok`, `petri_v3_kimi`, `kimi_100`, `kimi_100_v2`,
`grok_20`, `grok_omission`, `grok_omission2`, `scale13`, `opus_100`, `zone_v3`,
`zone_v3b`, `exp3_corpus`, `p3_corpus`, `xlab10_corpus`, and others. Some hold
seeds still cited as ground truth by the affordance model; most are dead runs.
Sorting the cited from the dead is part of this ticket, because a reviewer
opening this repo cannot currently tell which is which.
