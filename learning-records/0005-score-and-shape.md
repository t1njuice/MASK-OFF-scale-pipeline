# 0005 — Every score needs a companion that shows its shape

Date: 2026-08-14 · Status: active · Builds on: 0004 · Lesson: 0004

## Insight
A summary statistic gives the size of a problem and never its shape, so it cannot
tell you what to change. Each one in this workstream therefore needs a companion
diagnostic that reads the same data and reports *where*:

| Score (how much) | Companion (where) | Status |
|---|---|---|
| Cohen's kappa | confusion-pair table, `kappa.py:99` | built |
| Coverage / Hill q=0 | effective number / Hill q=1, `hill.py:25` | built |
| Self-BLEU | shared-phrase report, `diversity/shared_text.py` | built 2026-08-14 |
| Vendi Score | nearest-neighbour pairs | not built |

Demonstrated: holding raw agreement fixed at po = 0.873 and moving disagreements
into one ordered pair changes kappa by 0.001 (0.817 -> 0.816) while the diagnosis
flips from rater noise to menu defect. Kappa is blind to the distinction it most
matters to know.

## The two guard rails are not the same rule
- **Confusion pair >= 30%** detects an *overlap* (two options both true), needs two
  raters, runs on every kappa run, and triggers **disclosure** — the menu is frozen,
  so a fix would void the labels.
- **"Other" rate > 5%** detects a *hole* (no option fits), needs one rater, runs in
  the **pilot only**, and triggers **repair** — exactly one revision, then frozen.
  Exactly one, because repeated revision fits the taxonomy to its own data.

## Two findings from the first shared_text.py run (209-item scan)
1. `keep replies warm and {brief|concise|to the point}` covers ~88% of system
   prompts. **Not a defect** — `generator_system_v4.md:909` mandates it verbatim,
   because varied phrasings read as "answer only the literal question". Two
   consequences: the tone-line ablation covers essentially the whole corpus, so it
   is load-bearing; and the mandated line must be excluded before any Self-BLEU
   score, or the control gets measured as a flaw.
2. First name `dana` on 40.5% of parsed senders — 57 distinct names but effective
   number 18.2. This **is** the entity-convergence defect, larger than the recorded
   "Priya 6/26". Caveat: `name_pool.txt` landed 2026-08-14 and the scan is dated
   2026-08-12, so this measures the problem the fix targets, not the state after it.
   Re-run on the frozen corpus as the verification that `name_stream` reaches the
   generated text.

## Revisit if
The frozen corpus still shows a dominant first name after the name-pool fix — that
would mean the pool is not reaching generation, not that the pool is too small.
