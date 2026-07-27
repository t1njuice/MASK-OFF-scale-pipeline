# Prompt Explorer Field Rendering

## Goal

Keep the existing Seed Name, Accepted, Generator Model, and Hidden Fact
sections, then add System Prompt, User Prompt, Target Model, Target Response,
Target Reasoning, Reviewer Model, Reviewer Reason, Disclosure Level, and
Feedback.

## Design

Read the selected Polars row with `named=True` and render an ordered sequence
of `(label, column)` pairs through the existing `code_block` helper. Named
columns replace the current numeric indexes, which are already displaying
values under the wrong labels.

The field order is:

1. Seed Name
2. Accepted
3. Generator Model
4. Hidden Fact
5. System Prompt
6. User Prompt
7. Target Model
8. Target Response
9. Target Reasoning
10. Reviewer Model
11. Reviewer Reason
12. Disclosure Level
13. Feedback

## Verification

Run the edited live cell and confirm all labels render with their matching
values and no cell error. Then run `uv run marimo check prompt_explore.py` and
`git diff --check`.
