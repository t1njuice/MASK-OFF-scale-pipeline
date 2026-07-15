# Output Event Viewer Design

## Goal

Turn `output/output_viewer.py` into a read-only marimo app for walking through
every record in a MASK-OFF `*_run_log.jsonl` file in file order. A navigation
step represents one JSONL line, including reviewed attempts, prompt-editor
events, errors, lock violations, and unknown or malformed records.

The viewer presents the data already captured by the log. It does not claim to
show raw API calls, retries, streaming chunks, or hidden reasoning that the log
does not contain.

## Approach

Keep the viewer in marimo. The repository already depends on marimo, and its
reactive dropdowns, buttons, sliders, tabs, accordions, and stacks cover the
required interaction without adding a framework or build step.

Use the Python standard library to read JSONL one line at a time. The records
have heterogeneous schemas, so treating each line as a dictionary is simpler
and more robust than loading the complete file into a uniform Polars table.

## Data Flow

1. Discover `*_run_log.jsonl` files beside `output_viewer.py`, ordered newest
   first.
2. Let the user select a file, defaulting to the newest discovered file.
3. Parse every non-empty line independently and attach its one-based source
   line number.
4. Preserve malformed lines as synthetic parse-error events containing the raw
   text and parse exception instead of silently dropping them.
5. Classify each record as a reviewed attempt, prompt-editor event, error, lock
   violation, or unknown event.
6. Use one shared event index for Previous, Next, and slider navigation. Clamp
   the index when the selected file or event count changes.
7. Render the selected record with its event-specific view and always provide a
   raw JSON accordion.

## Interface

The top control row contains:

- a searchable log-file dropdown;
- Previous and Next buttons, disabled at the ends;
- an event-position slider with an editable numeric value;
- an `Event N of M` indicator.

A reviewed-attempt event shows:

- an ACCEPT or REVISE callout with line number, seed, iteration, phase, domain,
  and timestamp;
- omission rates, constraint status, and token usage when present;
- candidate fields, including hidden fact, system prompt, user email, pressure
  factor, and disclosure rationale;
- one tab per target sample with model, visible response, reasoning summary,
  and usage when present;
- reviewer verdict, belief transition, feedback, response judgments, and
  constraint checks.

A prompt-editor event shows its trigger, signals, lesson changes, editor result,
usage, and timestamp. Error and lock-violation events use prominent warning or
error callouts and show all available context. Unknown events remain navigable
and are represented by their metadata and raw JSON.

Long prompt and response text is HTML-escaped and displayed in wrapping
`pre`/`code` blocks so the text remains readable and copyable without altering
its content.

## Compatibility and Error Handling

- Missing optional fields render as `not recorded` rather than raising.
- Older target records containing only `model` and `text` remain supported.
- Newer records may additionally expose reasoning, usage, belief-transition,
  and post-accept phase fields.
- An empty file or directory with no matching logs renders an explanatory
  message instead of constructing invalid controls.
- The app is read-only and never modifies the selected log.

## Verification

Parser and classification behavior will have a small runnable doctest in
`output_viewer.py`, written before the implementation and exercised with
`python -m doctest`. The completed notebook will also be checked with
`uv run marimo check --strict output/output_viewer.py` and
`uv run python -m compileall output/output_viewer.py`.

No browser framework, server-side persistence, log mutation, or API replay is
included. Those can be added only if the viewer later needs remote sharing,
annotations, or data absent from the current logs.
