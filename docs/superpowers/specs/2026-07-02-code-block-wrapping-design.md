# Responsive Code Block Wrapping

## Scope

Change only the live notebook cell that defines `code_block`.

## Design

Return an HTML `<pre><code>` block instead of a Markdown fence. Escape the
input with Python's standard-library `html.escape`, then apply:

- `white-space: pre-wrap` to preserve existing whitespace while allowing
  visual line wrapping.
- `overflow-wrap: anywhere` to wrap long unbroken strings.
- `max-width: 100%` to keep the block inside the visible output region.

The source text remains unchanged when copied. The downstream marimo cell
reruns reactively after the function cell is edited and executed.

## Verification

Render text containing:

- A line wider than the notebook output region.
- A long string without spaces.
- HTML-sensitive characters such as `<`, `>`, and `&`.

Confirm wrapping, exact copied content, and no cell errors.
