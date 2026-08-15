---
id: 007
title: Judge bake-off
type: task
mode: AFK
status: open
assignee:
blocked-by: [005, 006]
---

## Question

Which judge model labels closest to the authors: Opus 4.8 or GPT-5.6 Terra? Both label the author-labeled sample; the one with higher κ against the pooled author labels becomes the labeling judge for the full set. Tie or both below threshold → revise the judge prompt (ticket 005) and rerun.

## Progress

- 2026-08-14: runner pre-written and self-checked — `diversity/labeling/bakeoff.py` (gold = author consensus, per-axis κ, Δκ bootstrap CI, tie → non-Claude by file stem). Waits on the author labels and Terra access.
- 2026-08-14: the sample is now n = 200 of the 500 (120 pool A / 80 pool B) — see the amendment in `diversity/research/agreement-standards.md`.
