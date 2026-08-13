# 03 — Delete the v1 pipeline

**What to build:** a package with one pipeline concept in it. The deprecated
omission-gate loop is gone, and the three helper functions that kept it alive
live in a small module of their own.

**Blocked by:** 02 — the brief must already point at the surviving design, or
deleting the module strands the documentation.

**Status:** ready-for-agent

## Why

`mask_off/pipeline.py` is 1,469 lines and is the largest file in the package. It
is the v1 design, marked deprecated in `config.py`. Its `run()`, its candidate
state machine, its rate computation, its coverage tables and its sample writers
are reachable from nothing. Every live module imports it for exactly three
functions: `preflight`, `run_timestamp`, `select_seeds`.

It also shares a name and a vocabulary with `frozen_pipeline.py`, which is the
module that does the work. That collision is the second-largest navigation
hazard in the package after the file count.

## What to build

- A small module holding `preflight`, `run_timestamp` and `select_seeds`, and
  nothing else. Name it for what it does, in `CONTEXT.md` vocabulary.
- Every caller updated: `frozen_pipeline`, `evaluate`, `scale`, `seedgen`.
- `pipeline.py` deleted.
- `cost_report.py` deleted. It carries its own hardcoded opus price table that
  predates `pricing.py` and silently misprices every non-opus model. `pricing`
  and `metrics` already cover it.
- `test_rates.py` deleted, and the v1 half of `test_seed_traceability.py`
  deleted, keeping whatever exercises surviving code.
- The dead knobs stripped from `config.py`: `K_SAMPLES`, `OMISSION_THRESHOLD`,
  `MAX_ITERATIONS`, `EARLY_STOP_ZERO_OMISSION`, `EARLY_STOP_FIXATION`,
  `VARIANT_ROUNDS`, `GATE_MODEL`, and the trailing `TAXONOMY` and `LEVERS`
  blocks already marked as folded into the generator prompt.

## Warnings

`GATE_MODEL` has an `assert` beside it that fires at import time. Removing the
constant means removing the assert; check nothing else reads it first.

`TARGET_MODELS` stays. Only `GATE_MODEL`, which is derived from it and read
solely by the deleted loop, goes.

Apply the deletion test before removing anything not on the list above: would
deleting it concentrate complexity somewhere, or just move it? Only delete when
nothing has to absorb the loss.

## Acceptance criteria

- [ ] `mask_off/pipeline.py` and `mask_off/cost_report.py` no longer exist.
- [ ] No module in `mask_off/` imports `pipeline`.
- [ ] `uv run python -m pytest mask_off -q` passes, with the count updated in
      the map and in `AGENTS.md`.
- [ ] `python -m mask_off.scale generate --help` and
      `python -m mask_off.scale evaluate --help` both succeed.
- [ ] `config.py` contains no knob that no surviving module reads.
- [ ] The package is at least 1,200 lines smaller.
