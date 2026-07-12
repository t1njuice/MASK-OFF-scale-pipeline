# Magnolia — project notes

## petri_bloom is NOT installed as a package (intentional)

The `petri-bloom` PyPI package has been **uninstalled** from `.venv` on purpose, so
there is only ONE copy of the code and no confusion about which one runs. The single
source of truth is the local tree at `petri_bloom/src/petri_bloom/`.

- **Run scenario generation via the script**, not the CLI:
  `uv run python scripts/run_model_omission_scenarios.py --behavior .\<behavior_dir> --model anthropic/claude-...`
  The script does `sys.path.insert(0, petri_bloom/src)`, so `import petri_bloom`
  resolves to the local source. Edits to `petri_bloom/src/` take effect immediately —
  **no sync, no reinstall needed.**

- **Dependencies still come from `.venv`.** petri_bloom is not self-contained: it imports
  `inspect_petri` (defines `JudgeDimension`), `inspect_ai`, `pydantic`, `anyio` — all
  installed in `.venv` and left in place. So you MUST run with the venv Python
  (`uv run …` or `.\.venv\Scripts\python.exe …`); a bare system Python will `ImportError`.

- **The `bloom` CLI and `inspect eval petri_bloom/bloom_audit` no longer work** — they
  import the (now removed) installed package. If you need them back, either reinstall
  (`uv pip install petri-bloom`) or run with `PYTHONPATH=petri_bloom/src`. Prefer the
  script instead.

- **Do not "sync to site-packages."** Earlier there were two copies (installed 0.2.6 +
  local src) and files were being copied between them — that is obsolete now. There is
  only local src.

## Local edits to petri_bloom (fork divergence)

`petri_bloom/src/petri_bloom/_understanding/understanding.py` — `_generate_with_tool`
now repairs invalid model tool output instead of crashing: it coerces stringified /
double-wrapped payloads and, on a pydantic `ValidationError`, feeds the error back to
the model and retries (`invalid_output_retries`), mirroring the existing content-filter /
missing-tool-call retry pattern. `_ideation/prompts.py` `DIMENSIONS_PROMPT` now explicitly
requires a one-sentence `description` per dimension (the schema requires it; the model
kept omitting it).
