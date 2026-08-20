---
id: 007
title: Judge bake-off
type: task
mode: AFK
status: closed
assignee: claude (2026-08-20)
resolved: 2026-08-20
blocked-by: [005, 006]
---

> **CLOSED 2026-08-20 — obsolete, and acting on it would break the
> pre-registration.** This ticket selects a labeling judge by κ. That
> selection was abolished on 2026-08-18: `ANALYSIS_PLAN.md` §5 records the
> user decision that **both judges are primary and neither is dropped** —
> both score every response at scale, both get a judge–human κ, and every
> reported rate carries both judges' numbers. Running the rule below would
> perform exactly the post-hoc judge selection §5 forbids.
>
> `diversity/labeling/bakeoff.py` survives and is still wanted, but as a
> validation of both judges rather than a decider between them.

## Question

~~Which judge model labels closest to the authors: Opus 4.8 or GPT-5.6 Terra? Both label the author-labeled sample; the one with higher κ against the pooled author labels becomes the labeling judge for the full set. Tie or both below threshold → revise the judge prompt (ticket 005) and rerun.~~ **Superseded — see the closure note above.**

## Progress

- 2026-08-14: runner pre-written and self-checked — `diversity/labeling/bakeoff.py` (gold = author consensus, per-axis κ, Δκ bootstrap CI, tie → non-Claude by file stem). Waits on the author labels and Terra access.
- 2026-08-14: the sample is now n = 200 of the 500 (~~120 pool A / 80 pool B~~ — **160 / 40, amended 2026-08-20** at the 400/100 ratio) — see the amendment in `diversity/research/agreement-standards.md`.
- 2026-08-20: closed. Both judges are primary; there is nothing to select.
