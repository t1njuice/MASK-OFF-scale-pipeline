# 01 — Manifest builder

**Status:** resolved
**Type:** task
**Blocked by:** —

## Problem

Stage B must run on a frozen, hash-pinned corpus of exactly 300 items, cut
from the regenerated accepted set before any target result exists. No
manifest code exists. The 20-item rehearsal must draw from the same frozen
corpus.

## Decisions

- One pure function in a new small module (or `scale`-adjacent — smallest
  home wins): accepted-item rows in → the chosen 300 rows out.
- Stratified across **domains** (CONTEXT.md sense), proportional to the
  accepted set's domain counts, using the largest-remainder method for
  rounding. Within a domain, acceptance order decides — first accepted,
  first in. Fully deterministic: same input rows → byte-identical output.
- Output: `dataset_v1.jsonl` plus the file's sha256 printed for the run
  log. Items keep their fields verbatim; the manifest adds nothing.
- A second entry point draws the n=20 rehearsal subset from the manifest:
  stratified the same way, deterministic under a fixed integer seed that is
  a named constant, recorded in the output.
- Input with fewer than 300 rows, or rows missing a domain, is a hard
  error, not a silent shortfall.

## Tests

New test file at the pure-function seam; no transport needed.

- Proportionality: synthetic rows over 3 domains with counts 161/107/54 →
  the 300 split matches largest remainder exactly.
- Determinism: two calls, identical bytes.
- Tie-break: within a domain, earlier acceptance wins.
- Hard error on <300 rows and on a missing-domain row.
- Rehearsal draw: n=20, stratified, deterministic, subset of the manifest.

## Out of scope

Running it on the real regenerated corpus (the verification pilot is still
in flight); committing the hash.

## Comments

**2026-08-16, agent (ticket 01):** Built `mask_off/manifest.py` — pure
`build_manifest(rows, size=300)` (largest-remainder quotas in integer
arithmetic, remainder ties to the domain seen first in acceptance order,
within-domain fill by acceptance order, rows verbatim) and
`rehearsal_draw(manifest, n=20, seed=REHEARSAL_SEED=20260816)` (same quota
machinery; within-domain pick via one shared `random.Random(seed)`, domains
in first-appearance order, output kept in manifest order). Hard `ValueError`
on `<size` rows and on any row with a missing/empty domain field. CLI:
`python -m mask_off.manifest build|rehearsal <in> [<out>]`, printing item
count + sha256 for the run log; the rehearsal command also prints the seed.
The domain lives in the on-disk field `taxonomy` (schema predates the
glossary; noted in a comment, not renamed).

Tests: `mask_off/test_manifest.py`, 6 tests covering every ticket case
(161/107/54 → 150/100/50, byte-identical determinism, within-domain
tie-break, both hard errors, rehearsal stratified/deterministic/subset).
`pytest mask_off -q`: 274 passed, 1 failed — the failure is
`test_pricing_preflight.py::test_the_shipped_judge_panel_is_two_models_both_priced`,
pre-existing from the working tree's uncommitted `config.py`/pricing edits
(another agent's files this wave); nothing imports the new module. CLI
smoke-tested on synthetic 322-row input: 300 + 20 out, hashes printed.
No deviations from spec.
