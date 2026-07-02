import marimo

__generated_with = "0.23.13"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    return mo, pl


@app.function(hide_code=True)
def code_block(text):
    import html

    escaped_text = html.escape(text)
    return (
        '<pre style="white-space: pre-wrap; overflow-wrap: anywhere; '
        'max-width: 100%; background-color: #e5e7eb; color: #1f2937;">'
        f"<code>{escaped_text}</code></pre>"
    )


@app.cell
def _(pl):
    sample_prompts = pl.read_csv("/Users/antyabharahman/Downloads/Personal/neurips/MASK-OFF-scale-pipeline/output/pilot_5_omission_samples.csv")
    sample_prompts
    return (sample_prompts,)


@app.cell
def _(mo, sample_prompts):
    row_index = mo.ui.slider(
        start=0,
        stop=max(len(sample_prompts) - 1, 0),
        step=1,
        value=0,
        label="Row index",
    )
    row_index
    return (row_index,)


@app.cell
def _(mo, row_index, sample_prompts):
    row = sample_prompts.row(index=row_index.value)

    formatted_conversation_output = mo.md(
        f"## Rendered prompt\n\n**Model**\n\n{code_block(row[2])}\n\n**system**\n\n{code_block(row[3])}\n\n**user_prompt**\n\n{code_block(row[4])}\n\n**Ground Truth**\n\n{code_block(row[5])}\n\n"
    )

    formatted_conversation_output
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
