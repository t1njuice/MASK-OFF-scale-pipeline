import marimo

__generated_with = "0.23.15"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    data = pl.read_ndjson("./run1000/accepted.jsonl")
    return (data,)


@app.cell
def _(data):
    data
    return


if __name__ == "__main__":
    app.run()
