# 01 — Extract the clean branch

**What to build:** a new branch, forked from the current work and destined to
become trunk, where a fresh agent that lists every tracked file sees roughly 250
files instead of 4,199. The package imports, the suite passes, and the two run
logs that later tickets cite are inside the repository rather than in the
results tree.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

## Why

A subagent globbing this repository today sees 4,199 tracked files, 41 of which
are the package. That is the single largest source of context rot in this
effort, and every other ticket is cheaper once it is fixed.

## What stays

- `mask_off/` — the package.
- `diversity/` — seed diversity work, including its own wayfinder map.
- `planning/scale-1200/` — ADR-0001, ADR-0002, design.md.
- `docs/` — whole. The user decided to keep the full design record.
- `kimi_100/` — the seed corpus Stage A draws from.
- Root: `CONTEXT.md`, `AGENTS.md`, `ANALYSIS_PLAN.md`, `MISSION.md`, `spec.md`,
  `README.md`, `pyproject.toml`, `uv.lock`, `seed_subcategories.md`,
  `seed_diversity.py`, `MASK-OFF Prompts.md`.
- Root tests that exercise surviving code: `test_generator.py`, `test_seeds.py`,
  `test_seed_diversity.py`.

## What goes

- `output/` (109 MB), `logs/`, `experiments/`, `scripts/`.
- Every results directory: `grok_omission/` (2,279 files), `grok_omission2/`,
  `petri_bloom/`, `petri_v3*/`, `opus_100/`, `kimi_100_v2/`, `cmp/`,
  `model_omission*/`, `claude_code_results/`, `omission/`,
  `all_omission_results/`, `calib11/`, `deli5/`, `scale13/`, `zone_v3/`,
  `xlab10_corpus/`, `exp3_corpus/`, `p3_corpus/`, `grok_20/`.
- `__marimo__/`, `prompt_snapshots/`, `assets/`, `reference/`, `lessons/`,
  `learning-records/`.
- `test_pipeline_cli.py`, `test_pipeline_seed_loop.py`,
  `test_pipeline_waves.py` — these test the deprecated v1 loop and die with
  ticket 03.

## Warnings

Commit the pending direction-lock work first. The uncommitted changes to
`validity.py`, `prompts/validity_reviewer.md`, `prompts/seed_brief.md` and
`generator.py` are the oscillation fix and must travel to the new branch.

Delete with `git rm`, never with `rm`. History must stay intact so any deleted
file is recoverable. The `.git` directory does not shrink and that is fine —
agents read the working tree, not the object store.

Do not add anything to `.gitignore` to achieve this. Untracked-but-present
files still appear to an agent that lists a directory.

## Acceptance criteria

- [ ] A new branch exists, forked after the direction-lock work is committed.
- [ ] `git ls-files | wc -l` returns under 400.
- [ ] `uv run python -m pytest mask_off -q` reports 79 passed.
- [ ] `python -c "import mask_off.scale, mask_off.evaluate, mask_off.metrics"`
      succeeds.
- [ ] `docs/evidence/` holds the p6 gate-pilot run log and the `frozen_19` run
      log, and a short README naming what each one measured.
- [ ] Every deleted path is recoverable — `git log --diff-filter=D` lists them.
- [ ] The root suite's two pre-existing collection errors are recorded in the
      map under "Not yet specified": `test_pipeline_waves.py` (dies with ticket
      03) and `test_seed_diversity.py` (undiagnosed).
