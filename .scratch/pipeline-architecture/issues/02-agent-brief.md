# 02 — Rewrite the agent brief

**What to build:** an onboarding path where a fresh agent reads one file, learns
which pipeline is real, and knows where the design record and the current
effort live. Today `AGENTS.md` documents the deprecated v1 loop, so every cold
subagent is sent to the dead module by the first file it reads.

**Blocked by:** 01 — the brief must describe the clean tree, not the old one.

**Status:** ready-for-agent

## Why

`AGENTS.md` tells an agent to run `mask_off.pipeline --mode smoke` and describes
a Generator to Target to Reviewer loop. That design was retired by the
2026-08-03 amendment. The real entry point is `mask_off.scale`, and the real
Stage A loop has no target model in it. An agent that trusts the brief writes
code against a module that ticket 03 deletes.

## What the brief must say

- The two stages, in the vocabulary of `CONTEXT.md`: Stage A is seed to item,
  gated by the validity panel, no target model inside it. Stage B is evaluation
  of an approved corpus.
- The real commands: `python -m mask_off.scale generate` and
  `python -m mask_off.scale evaluate`, driven against a run directory.
- The verification command, `uv run python -m pytest mask_off -q`, and its
  current expected count.
- Which four documents matter and what each one settles: `CONTEXT.md` for
  vocabulary, `planning/scale-1200/design.md` for the scale design, ADR-0001 for
  the batch cache, ADR-0002 for routes and adapters.
- That pilots run through `mask_off.scale` and not through ad-hoc scripts.
- The standing rules: never discard batch work, run reports end with artifact
  paths, prompts under `mask_off/prompts/` are frozen.

## Warnings

Keep it short. A brief that lists every module is a brief nobody finishes. Name
the entry points and the four documents; let the agent read the code for the
rest.

Do not describe modules that tickets 03 to 12 will change. Describe the stages
and the commands, which are stable.

## Acceptance criteria

- [ ] `AGENTS.md` contains no reference to `mask_off.pipeline`, `--mode smoke`,
      `--mode pilot`, or a target model inside the generation loop.
- [ ] `AGENTS.md` names the two stages, the two `mask_off.scale` commands, and
      the verification command with its expected pass count.
- [ ] `AGENTS.md` points at the four load-bearing documents and says in one line
      what each settles.
- [ ] `AGENTS.md` links to this effort's map so an agent finds the open tickets.
- [ ] An agent given only `AGENTS.md` can state which module runs Stage A
      without reading any other file.
