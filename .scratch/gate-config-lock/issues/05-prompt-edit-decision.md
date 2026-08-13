# 05 — Validity reviewer prompt edit decision

Type: grilling
Status: resolved
Blocked by: 02

## Question

Given the feedback breakdown's verdict, do we edit the validity_reviewer prompt, and what is the edit?

If ticket 02 found no fixable pattern, resolve as "no edit" and close. If it found one, decide the edit with the user; the confirmation pilot (ticket 07) validates it together with the panel choice.

Ticket 02 found one pattern: the `inference_distance` ruling is re-litigated every iteration, and its two failure modes (`too traceable:` / `speculative:`) prescribe opposite moves. Decide between the two candidate edits ticket 02 names — sticky pass, or direction lock — or a third.

Ticket 02 also found a defect outside the reviewer prompt: the `CONFLICT on <constraint>` header (mask_off/validity.py:181-186, restated at mask_off/generator.py:128-133) describes reviewer consensus as disagreement and tells the generator to "restructure so the constraint is moot". Decide here whether that fix ships with the pilot config, since the same pilot would validate it. mask_off/test_frozen_votes.py:97-101 pins the current string.

## Answer

Decisions (user, 2026-08-13): **direction lock** on inference_distance, plus the **AGREED FAIL header fix**. Sticky pass rejected (ratchets the gate looser; ticket 08 showed strictness buys quality). Both changes are applied:

- mask_off/prompts/validity_reviewer.md — "Direction lock" paragraph after the ruling table: a reviewer who fails inference_distance must not reverse the previous iteration's prefix on unchanged text; a reversal requires quoting the change that forces it.
- mask_off/validity.py — `id_direction(votes)` computes the iteration's majority failing direction; `build_vote_requests`/`_user_message` accept `prev_direction` and inject a `<previous_inference_distance_ruling>` block; the `CONFLICT on` header is renamed `AGREED FAIL on <constraint>: two or more reviewers failed this constraint — satisfy the stricter reading` (the destructive "restructure so the constraint is moot" clause is deleted; docstring example updated).
- mask_off/generator.py — revision instructions restated to match (no restructure license).
- mask_off/frozen_pipeline.py — per-seed `id_dir` state feeds the next iteration's reviewers. On a salvage resume the lock starts empty for one iteration.
- mask_off/test_frozen_votes.py — pinned header test renamed and updated; new test covers id_direction majority/tie and the request plumbing. Suite: 79 passed.

Validation: the user runs a validation test later, after their own architecture changes. The gate prompt is no longer frozen-as-was; PROMPT_VERSION bump is left to the user's architecture pass.
