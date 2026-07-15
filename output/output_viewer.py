import marimo

__generated_with = "0.23.13"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    return (pl,)


@app.cell
def _(pl):
    all_dataset = pl.read_csv("pilot_2_20260705T040234Z.csv")
    all_dataset
    return


@app.cell
def _(pl):
    pl.read_csv("pilot_2_20260705T040234Z_all_responses.csv")
    return


@app.cell
def _(pl):
    pl.read_csv("pilot_2_20260705T040234Z_omission_samples.csv")
    return


@app.cell
def _():
    import pandas as pd
    pd.read_json("pilot_2_20260705T040234Z_run_log.jsonl", lines=True)
    return


if __name__ == "__main__":
    app.run()
