# Output Event Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current output data dump with a read-only marimo app that walks through every JSONL event in file order and formats reviewed attempts, prompt-editor events, errors, lock violations, and unknown records.

**Architecture:** Keep parsing, classification, rendering, and the marimo app in `output/output_viewer.py`. Read heterogeneous JSONL records independently with the standard library, then dispatch each selected record to a small event-specific renderer; marimo state synchronizes Previous, Next, and slider navigation.

**Tech Stack:** Python 3.13, standard-library `json`/`html`/`pathlib`, marimo 0.23.13 or newer, embedded `doctest`.

## Global Constraints

- Modify only `output/output_viewer.py`; do not edit JSONL or CSV artifacts.
- Keep the app read-only and represent every non-empty JSONL line, including malformed lines.
- Show only data present in the logs; do not imply that raw API retries, stream chunks, or hidden reasoning are available.
- Support both old target records with `model`/`text` and newer records with `reasoning`/`usage`.
- Add no dependencies and remove the viewer's pandas/Polars requirement.
- Preserve unrelated dirty-worktree changes.

---

### Task 1: JSONL loading and event classification

**Files:**
- Modify: `output/output_viewer.py:1`
- Test: embedded doctest in `output/output_viewer.py`

**Interfaces:**
- Produces: `discover_logs(directory: str | Path) -> list[Path]`
- Produces: `load_events(path: str | Path) -> list[dict]`
- Produces: `event_kind(record: dict) -> str`
- Each returned event contains `_line_number: int`.

- [ ] **Step 1: Add the failing parser/classifier doctest**

Insert this module docstring before `import marimo`:

```python
"""Interactive viewer for MASK-OFF JSONL run logs.

>>> import tempfile
>>> from pathlib import Path
>>> with tempfile.TemporaryDirectory() as tmp:
...     path = Path(tmp) / "sample_run_log.jsonl"
...     _ = path.write_text(
...         '{"candidate": {}, "target_responses": {}, "review": {}, '
...         '"accepted": false}\nnot-json\n',
...         encoding="utf-8",
...     )
...     events = load_events(path)
>>> [event_kind(event) for event in events]
['reviewed_attempt', 'parse_error']
>>> [event["_line_number"] for event in events]
[1, 2]
"""
```

- [ ] **Step 2: Run the doctest and confirm the expected failure**

Run:

```bash
uv run python -m doctest output/output_viewer.py
```

Expected: FAIL with `NameError: name 'load_events' is not defined`.

- [ ] **Step 3: Add the minimal loader and classifier**

Immediately after `app = marimo.App(width="full")`, add:

```python
@app.function(hide_code=True)
def discover_logs(directory):
    from pathlib import Path

    root = Path(directory)
    return sorted(
        root.glob("*run_log.jsonl"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


@app.function(hide_code=True)
def load_events(path):
    import json
    from pathlib import Path

    events = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
                event = value if isinstance(value, dict) else {
                    "event": "unknown",
                    "value": value,
                }
            except json.JSONDecodeError as error:
                event = {
                    "event": "parse_error",
                    "error": f"{error.msg} at column {error.colno}",
                    "raw": raw_line.rstrip("\n"),
                }
            event["_line_number"] = line_number
            events.append(event)
    return events


@app.function(hide_code=True)
def event_kind(record):
    if record.get("event") == "parse_error":
        return "parse_error"
    if record.get("event") == "prompt_editor":
        return "prompt_editor"
    if "error" in record:
        return "error"
    if "lock_violation" in record:
        return "lock_violation"
    if all(key in record for key in ("candidate", "target_responses", "review")):
        return "reviewed_attempt"
    return "unknown"
```

- [ ] **Step 4: Run the doctest and confirm it passes**

Run:

```bash
uv run python -m doctest output/output_viewer.py
```

Expected: exit code 0 with no output.

- [ ] **Step 5: Commit the data layer**

```bash
git add output/output_viewer.py
git commit -m "Add output log event loader"
```

---

### Task 2: Event-specific rendering

**Files:**
- Modify: `output/output_viewer.py`
- Test: embedded doctest in `output/output_viewer.py`

**Interfaces:**
- Consumes: `event_kind(record: dict) -> str`
- Produces: `code_block(value: object) -> str`
- Produces: `percent(value: object) -> str`
- Produces: `render_event(record: dict) -> marimo.Html`

- [ ] **Step 1: Add failing renderer doctests**

Append these examples to the existing module docstring, before its closing quotes:

```python
>>> "&lt;secret&gt;" in code_block("<secret>")
True
>>> percent(0.5), percent(None)
('50%', 'not recorded')
```

- [ ] **Step 2: Run the doctest and confirm the expected failure**

Run:

```bash
uv run python -m doctest output/output_viewer.py
```

Expected: FAIL with `NameError: name 'code_block' is not defined`.

- [ ] **Step 3: Add the rendering helpers and event dispatcher**

Add these functions after `event_kind`:

```python
@app.function(hide_code=True)
def display_value(value):
    return "not recorded" if value is None or value == "" else str(value)


@app.function(hide_code=True)
def percent(value):
    if value is None:
        return "not recorded"
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return display_value(value)


@app.function(hide_code=True)
def code_block(value):
    import html

    escaped = html.escape(display_value(value))
    return (
        '<pre style="white-space: pre-wrap; overflow-wrap: anywhere; '
        'max-width: 100%; max-height: 32rem; overflow-y: auto; '
        'background: #f3f4f6; color: #111827; padding: 0.75rem; '
        'border-radius: 0.5rem;"><code>'
        f"{escaped}</code></pre>"
    )


@app.function(hide_code=True)
def render_reviewed_attempt(record):
    import marimo as mo

    candidate = record.get("candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    targets = record.get("target_responses")
    targets = targets if isinstance(targets, dict) else {}
    review = record.get("review")
    review = review if isinstance(review, dict) else {}
    accepted = bool(record.get("accepted"))
    decision = "ACCEPT" if accepted else "REVISE"

    header = mo.md(
        f"## {decision}\n\n"
        f"Line `{record.get('_line_number')}` · seed `{display_value(record.get('seed'))}` "
        f"· iteration `{display_value(record.get('iteration'))}` · "
        f"phase `{display_value(record.get('phase') or 'main')}` · "
        f"timestamp `{display_value(record.get('ts'))}`"
    ).callout(kind="success" if accepted else "warn")

    rates = mo.hstack(
        [
            mo.stat(percent(record.get("opus_omission_rate")), label="Opus omission"),
            mo.stat(percent(record.get("sonnet_omission_rate")), label="Sonnet omission"),
            mo.stat(percent(record.get("fable_omission_rate")), label="Fable omission"),
            mo.stat(display_value(record.get("constraints_ok")), label="Constraints OK"),
        ],
        wrap=True,
        widths="equal",
    )

    candidate_panel = mo.accordion(
        {
            "Hidden fact": mo.md(code_block(candidate.get("hidden_fact"))),
            "System prompt": mo.md(code_block(candidate.get("system_prompt"))),
            "User email": mo.md(code_block(candidate.get("user_email"))),
            "Pressure factor": mo.md(code_block(candidate.get("pressure_factor"))),
            "Disclosure rationale": mo.md(
                code_block(candidate.get("disclosure_rationale"))
            ),
        },
        multiple=True,
    )

    target_tabs = {}
    for label, target in targets.items():
        target = target if isinstance(target, dict) else {"text": target}
        reasoning = target.get("reasoning")
        if isinstance(reasoning, dict):
            reasoning = reasoning.get("summary")
        parts = [
            mo.md(f"**Model:** `{display_value(target.get('model'))}`"),
            mo.md("### Visible response"),
            mo.md(code_block(target.get("text"))),
            mo.md("### Reasoning summary"),
            mo.md(code_block(reasoning)),
        ]
        if target.get("usage"):
            parts.append(
                mo.accordion({"Token usage": mo.json(target["usage"])}, lazy=True)
            )
        target_tabs[str(label)] = mo.vstack(parts)

    targets_view = (
        mo.ui.tabs(target_tabs, lazy=True)
        if target_tabs
        else mo.md("*No target responses were recorded.*")
    )

    reviewer_parts = [
        mo.md("### Verdict"),
        mo.md(code_block(review.get("verdict"))),
        mo.md("### Belief transition"),
        mo.md(code_block(review.get("belief_transition_observed"))),
        mo.md("### Feedback"),
        mo.md(code_block(review.get("feedback"))),
    ]
    reviewer_details = {}
    if review.get("response_judgments") is not None:
        reviewer_details["Response judgments"] = mo.json(
            review["response_judgments"]
        )
    if review.get("constraints") is not None:
        reviewer_details["Constraint checks"] = mo.json(review["constraints"])
    if reviewer_details:
        reviewer_parts.append(
            mo.accordion(reviewer_details, multiple=True, lazy=True)
        )

    sections = [
        header,
        mo.md("**Domain**"),
        mo.md(code_block(record.get("domain") or candidate.get("domain"))),
        rates,
        mo.md("## Candidate"),
        candidate_panel,
        mo.md("## Target responses"),
        targets_view,
        mo.md("## Reviewer"),
        mo.vstack(reviewer_parts),
    ]
    if record.get("usage"):
        sections.append(
            mo.accordion({"Attempt token usage": mo.json(record["usage"])}, lazy=True)
        )
    return mo.vstack(sections, gap=1)


@app.function(hide_code=True)
def render_prompt_editor(record):
    import marimo as mo

    signals = record.get("signals") or []
    if not isinstance(signals, list):
        signals = [signals]
    signal_views = [mo.md(code_block(signal)) for signal in signals]
    result = record.get("result")
    result_view = (
        mo.json(result)
        if isinstance(result, (dict, list))
        else mo.md(code_block(result))
    )
    return mo.vstack(
        [
            mo.md(
                "## PROMPT EDITOR\n\n"
                f"Trigger `{display_value(record.get('trigger'))}` · "
                f"line `{record.get('_line_number')}` · "
                f"timestamp `{display_value(record.get('ts'))}`"
            ).callout(kind="info"),
            mo.md("## Signals"),
            mo.vstack(signal_views) if signal_views else mo.md("*No signals recorded.*"),
            mo.md("## Editor result and lesson changes"),
            result_view,
        ],
        gap=1,
    )


@app.function(hide_code=True)
def render_problem(record, title, kind):
    import marimo as mo

    detail = record.get("lock_violation") or record.get("error")
    if record.get("event") == "parse_error":
        detail = f"{display_value(record.get('error'))}\n\n{display_value(record.get('raw'))}"
    return mo.vstack(
        [
            mo.md(
                f"## {title}\n\nLine `{record.get('_line_number')}` · "
                f"seed `{display_value(record.get('seed'))}` · "
                f"iteration `{display_value(record.get('iteration'))}` · "
                f"timestamp `{display_value(record.get('ts'))}`"
            ).callout(kind=kind),
            mo.md(code_block(detail)),
        ]
    )


@app.function(hide_code=True)
def render_event(record):
    import marimo as mo

    kind = event_kind(record)
    if kind == "reviewed_attempt":
        body = render_reviewed_attempt(record)
    elif kind == "prompt_editor":
        body = render_prompt_editor(record)
    elif kind == "lock_violation":
        body = render_problem(record, "LOCK VIOLATION", "warn")
    elif kind == "parse_error":
        body = render_problem(record, "JSON PARSE ERROR", "danger")
    elif kind == "error":
        body = render_problem(record, "PIPELINE ERROR", "danger")
    else:
        body = mo.md(
            f"## UNKNOWN EVENT\n\nLine `{record.get('_line_number')}`"
        ).callout(kind="neutral")

    return mo.vstack(
        [
            body,
            mo.accordion({"Raw JSON": mo.json(record)}, lazy=True),
        ],
        gap=1,
    )
```

- [ ] **Step 4: Run focused rendering checks**

Run:

```bash
uv run python -m doctest output/output_viewer.py
uv run marimo check --strict output/output_viewer.py
```

Expected: both commands exit 0 with no errors.

- [ ] **Step 5: Commit the event renderers**

```bash
git add output/output_viewer.py
git commit -m "Render output log events"
```

---

### Task 3: Reactive file and event navigation

**Files:**
- Modify: `output/output_viewer.py`
- Test: embedded doctest and marimo validation for `output/output_viewer.py`

**Interfaces:**
- Consumes: `discover_logs`, `load_events`, and `render_event` from Tasks 1-2.
- Produces: a read-only marimo app with synchronized file dropdown, Previous/Next buttons, slider, event counter, and selected-event output.

- [ ] **Step 1: Add the failing navigation-boundary doctest**

Append this example to the module docstring:

```python
>>> clamp_index(-2, 3), clamp_index(9, 3), clamp_index(0, 0)
(0, 2, 0)
```

- [ ] **Step 2: Run the doctest and confirm the expected failure**

Run:

```bash
uv run python -m doctest output/output_viewer.py
```

Expected: FAIL with `NameError: name 'clamp_index' is not defined`.

- [ ] **Step 3: Add the boundary helper**

Add after `event_kind`:

```python
@app.function(hide_code=True)
def clamp_index(index, count):
    if count <= 0:
        return 0
    return max(0, min(int(index), count - 1))
```

- [ ] **Step 4: Replace the four existing dataframe cells with the marimo app cells**

Delete the cells that import pandas/Polars and read the hard-coded pilot files. Keep all `@app.function` helpers, then add these cells before the `if __name__ == "__main__":` block:

```python
@app.cell
def _():
    from pathlib import Path

    import marimo as mo

    return Path, mo


@app.cell
def _(mo):
    get_event_index, set_event_index = mo.state(0)
    return get_event_index, set_event_index


@app.cell
def _(mo):
    mo.md(
        "# MASK-OFF generation event viewer\n\n"
        "Walk through each recorded JSONL event in file order. One reviewed-attempt "
        "event contains the candidate, all target samples, reviewer output, and the "
        "resulting ACCEPT/REVISE decision."
    )
    return


@app.cell
def _(Path, mo, set_event_index):
    logs = discover_logs(Path(__file__).resolve().parent)
    mo.stop(
        not logs,
        mo.md("No `*run_log.jsonl` files were found beside this viewer.").callout(
            kind="warn"
        ),
    )
    log_picker = mo.ui.dropdown(
        options={path.name: str(path) for path in logs},
        value=logs[0].name,
        searchable=True,
        label="Run log",
        on_change=lambda _value: set_event_index(0),
        full_width=True,
    )
    log_picker
    return (log_picker,)


@app.cell
def _(log_picker, mo):
    events = load_events(log_picker.value)
    mo.stop(
        not events,
        mo.md("The selected log contains no non-empty events.").callout(kind="warn"),
    )
    return (events,)


@app.cell
def _(events, get_event_index, mo, set_event_index):
    event_count = len(events)
    current_index = clamp_index(get_event_index(), event_count)

    def move(delta):
        def on_click(click_count):
            set_event_index(
                lambda index: clamp_index(index + delta, event_count)
            )
            return click_count + 1

        return on_click

    previous_button = mo.ui.button(
        value=0,
        on_click=move(-1),
        label="← Previous",
        disabled=current_index == 0,
    )
    next_button = mo.ui.button(
        value=0,
        on_click=move(1),
        label="Next →",
        kind="success",
        disabled=current_index == event_count - 1,
    )
    event_slider = mo.ui.slider(
        start=0,
        stop=event_count - 1,
        step=1,
        value=current_index,
        show_value=True,
        include_input=True,
        label="Event index",
        on_change=lambda value: set_event_index(int(value)),
        full_width=True,
    )

    mo.hstack(
        [
            previous_button,
            event_slider,
            next_button,
            mo.md(f"**Event {current_index + 1} of {event_count}**"),
        ],
        align="center",
        widths=[0, 1, 0, 0],
    )
    return (current_index,)


@app.cell
def _(current_index, events):
    render_event(events[current_index])
    return
```

- [ ] **Step 5: Run all automated checks**

Run:

```bash
uv run python -m doctest output/output_viewer.py
uv run marimo check --strict output/output_viewer.py
uv run python -m compileall output/output_viewer.py
```

Expected: doctest exits 0 silently; marimo reports no errors or warnings; compileall reports successful compilation.

- [ ] **Step 6: Smoke-test the rendered app**

Start the app:

```bash
uv run marimo run output/output_viewer.py --headless --port 2719
```

Open `http://127.0.0.1:2719`, then verify:

1. The newest run log is selected by default.
2. Event 1 renders with a status callout and raw JSON accordion.
3. Next, Previous, slider, and numeric input all change the same event position.
4. A reviewed attempt exposes candidate, target tabs, reviewer feedback, and ACCEPT/REVISE state.
5. A prompt-editor record and an error record render without exceptions.
6. Changing the log file resets navigation to Event 1.

Expected: all six checks succeed and the terminal shows no notebook exceptions.

- [ ] **Step 7: Commit the completed viewer**

```bash
git add output/output_viewer.py
git commit -m "Build output event viewer"
```
