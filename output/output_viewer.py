"""Interactive viewer for MASK-OFF JSONL run logs.

>>> import tempfile
>>> from pathlib import Path
>>> with tempfile.TemporaryDirectory() as tmp:
...     path = Path(tmp) / "sample_run_log.jsonl"
...     _ = path.write_text(
...         '{"candidate": {}, "target_responses": {}, "review": {}, '
...         '"accepted": false}\\nnot-json\\n',
...         encoding="utf-8",
...     )
...     events = load_events(path)
>>> [event_kind(event) for event in events]
['reviewed_attempt', 'parse_error']
>>> [event["_line_number"] for event in events]
[1, 2]
"""

import marimo

__generated_with = "0.23.13"
app = marimo.App(width="full")


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


if __name__ == "__main__":
    app.run()
