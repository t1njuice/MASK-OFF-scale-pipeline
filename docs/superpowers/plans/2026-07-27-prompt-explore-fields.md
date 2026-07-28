# Prompt Explorer Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the existing four prompt fields and the nine newly requested fields with values from their correctly named CSV columns.

**Architecture:** Change only the rendered-prompt cell in `prompt_explore.py`. Read the selected Polars row as a dictionary, then generate the sections from one ordered label-to-column tuple through the existing `code_block` helper.

**Tech Stack:** Python 3.13, marimo, Polars

## Global Constraints

- Preserve Seed Name, Accepted, Generator Model, and Hidden Fact.
- Append System Prompt, User Prompt, Target Model, Target Response, Target Reasoning, Reviewer Model, Reviewer Reason, Disclosure Level, and Feedback in that order.
- Use named columns instead of numeric row indexes.
- Make the durable edit in the active marimo session, not directly on disk.
- Add no dependencies or new abstraction.

---

### Task 1: Render all prompt fields from named columns

**Files:**
- Modify: `prompt_explore.py:48-59`
- Verify: active marimo output for `prompt_explore.py`

**Interfaces:**
- Consumes: `sample_prompts: polars.DataFrame`, `row_index.value: int`, and `code_block(value) -> str`
- Produces: `formatted_conversation_output`, a marimo Markdown output containing 13 labeled sections

- [ ] **Step 1: Run the live failing output check**

Use Computer Use against the active Brave marimo tab:

```javascript
const state = await sky.get_app_state({
  app: "Brave Browser",
  disableDiff: true,
});
const start = state.text.indexOf("heading Rendered prompt");
const end = state.text.indexOf("button PYTHON", start);
const output = state.text.slice(start, end);
const labels = [
  "Seed Name",
  "Accepted",
  "Generator Model",
  "Hidden Fact",
  "System Prompt",
  "User Prompt",
  "Target Model",
  "Target Response",
  "Target Reasoning",
  "Reviewer Model",
  "Reviewer Reason",
  "Disclosure Level",
  "Feedback",
];
for (const label of labels) {
  if (!output.includes(label)) {
    throw new Error(`Missing rendered field: ${label}`);
  }
}
```

Expected: FAIL with `Missing rendered field: System Prompt`. The current output also demonstrates the numeric-index bug by showing `Accepted` as `revising`.

- [ ] **Step 2: Replace the live rendered-prompt cell**

Use the active marimo editor or `marimo._code_mode` to replace the cell body with:

```python
row = sample_prompts.row(index=row_index.value, named=True)
_fields = (
    ("Seed Name", "seed_name"),
    ("Accepted", "accepted"),
    ("Generator Model", "generator_model"),
    ("Hidden Fact", "hidden_fact"),
    ("System Prompt", "system_prompt"),
    ("User Prompt", "user_prompt"),
    ("Target Model", "target_model"),
    ("Target Response", "target_response"),
    ("Target Reasoning", "target_reasoning_summary"),
    ("Reviewer Model", "reviewer_model"),
    ("Reviewer Reason", "review_reason"),
    ("Disclosure Level", "disclosure_level"),
    ("Feedback", "feedback"),
)

formatted_conversation_output = mo.md(
    "## Rendered prompt\n\n"
    + "\n\n".join(
        f"**{label}**\n\n{code_block(row[column])}"
        for label, column in _fields
    )
)

formatted_conversation_output
```

- [ ] **Step 3: Run the updated cell and its dependents**

Run the edited cell with Shift+Enter. Expected: the output renders all 13 sections without a cell error.

- [ ] **Step 4: Run the live output check again**

Repeat the JavaScript check from Step 1.

Expected: PASS with no missing labels. Confirm the visible `Accepted` value is Boolean and `Generator Model` is the model name.

- [ ] **Step 5: Run file-level verification**

Run:

```bash
uv run marimo check prompt_explore.py
git diff --check
```

Expected: both commands exit 0. The existing removable-empty-cell warning may remain.

- [ ] **Step 6: Commit only with explicit authorization**

```bash
git add prompt_explore.py docs/superpowers/specs/2026-07-27-prompt-explore-fields-design.md docs/superpowers/plans/2026-07-27-prompt-explore-fields.md
git commit -m "Expand prompt explorer fields"
```
