# Responsive Code Block Wrapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make notebook text blocks wrap within the visible output region without changing copied text.

**Architecture:** Replace Markdown fences from `code_block` with one escaped
HTML `<pre><code>` element whose inline CSS enables responsive visual wrapping.
Apply the change through marimo code mode so the live kernel remains the source
of truth and reruns the dependent output cell.

**Tech Stack:** Python 3.13 standard library, marimo 0.23.13, marimo code mode

## Global Constraints

- Change only the live notebook cell that defines `code_block`.
- Preserve the source text exactly when copied.
- Add no dependency.
- Do not edit the notebook `.py` artifact directly.

---

### Task 1: Make `code_block` wrap responsively

**Files:**
- Modify: live marimo notebook cell `lDSz` at `http://localhost:2719/`
- Test: marimo scratchpad assertions against `code_block` and cell state

**Interfaces:**
- Consumes: `code_block(text: str) -> str`
- Produces: escaped HTML containing a responsive `<pre><code>` block

- [ ] **Step 1: Run the failing scratchpad check**

```bash
bash /Users/antyabharahman/.agents/skills/marimo-pair/scripts/execute-code.sh \
  --url 'http://localhost:2719/' \
  --token "$(cat '/var/folders/t6/fbm36rg51l5_32z_qdtmksf40000gn/T/marimo-pair-fck68pzw/30210c-token.txt')" <<'PY'
_probe = code_block("<tag>&\n" + "x" * 200)
assert "white-space: pre-wrap" in _probe
assert "overflow-wrap: anywhere" in _probe
assert "max-width: 100%" in _probe
assert "&lt;tag&gt;&amp;" in _probe
PY
```

Expected: FAIL at the first assertion because the current implementation
returns a Markdown fence.

- [ ] **Step 2: Edit and run the owning cell**

```bash
bash /Users/antyabharahman/.agents/skills/marimo-pair/scripts/execute-code.sh \
  --url 'http://localhost:2719/' \
  --token "$(cat '/var/folders/t6/fbm36rg51l5_32z_qdtmksf40000gn/T/marimo-pair-fck68pzw/30210c-token.txt')" <<'PY'
import marimo._code_mode as cm

_code = '''def code_block(text):
    import html

    escaped_text = html.escape(text)
    return (
        '<pre style="white-space: pre-wrap; overflow-wrap: anywhere; '
        f'max-width: 100%;"><code>{escaped_text}</code></pre>'
    )'''

async with cm.get_context() as ctx:
    assert ctx.cells["lDSz"].code.startswith("def code_block(text):")
    ctx.edit_cell("lDSz", _code)
    ctx.run_cell("lDSz")
PY
```

Expected: cell `lDSz` and its dependent output cell run without errors.

- [ ] **Step 3: Verify output safety, wrapping styles, and live cell health**

```bash
bash /Users/antyabharahman/.agents/skills/marimo-pair/scripts/execute-code.sh \
  --url 'http://localhost:2719/' \
  --token "$(cat '/var/folders/t6/fbm36rg51l5_32z_qdtmksf40000gn/T/marimo-pair-fck68pzw/30210c-token.txt')" <<'PY'
import marimo._code_mode as cm

_source = "<tag>&\n" + "x" * 200
_probe = code_block(_source)
assert "white-space: pre-wrap" in _probe
assert "overflow-wrap: anywhere" in _probe
assert "max-width: 100%" in _probe
assert "&lt;tag&gt;&amp;" in _probe
assert "<tag>&" not in _probe

async with cm.get_context() as ctx:
    assert ctx.cells["lDSz"].errors == []
    assert ctx.cells["oUYl"].errors == []
PY
```

Expected: all assertions pass and both cells have no errors.
