# Subcategory Cluster Visualization Design

## Goal

Add one marimo cell after the subcategory clustering cell that makes cluster
quality easy to inspect. The visual must answer two questions:

1. How strongly does each cluster correspond to one supplied category?
2. How close are individual subcategories to their assigned cluster centroid?

## Data

The cell reads the existing `subcategory_clusters` Polars DataFrame. It does
not recompute embeddings or clustering and therefore introduces no additional
API calls.

Relevant fields are:

- `cluster`
- `subcategory`
- `source_category`
- `matches_majority`
- `cosine_to_centroid`

## Visual Design

The cell displays two vertically stacked Altair charts.

### Category-composition heatmap

The heatmap has cluster identifiers on the vertical axis and shortened source
category names on the horizontal axis. Each cell represents the share of a
cluster belonging to that source category.

- A single blue sequential scale encodes share from zero to one.
- Tooltips show cluster, full category name, count, and share.
- The cell constructs the complete cluster-by-category grid so missing
  combinations appear as zero rather than disappearing.
- A concentrated dark cell indicates a purer cluster; several similarly dark
  cells indicate category mixing.

### Centroid-similarity dot plot

The dot plot places cluster identifiers on the horizontal axis and
`cosine_to_centroid` on the vertical axis. Each point represents one
subcategory.

- Higher values indicate stronger cluster cohesion.
- Matching and non-matching majority assignments use both colour and shape, so
  the distinction does not depend on colour alone.
- Tooltips show subcategory, source category, majority category, cluster,
  cosine similarity, and match status.
- Points use partial opacity to reveal dense regions without obscuring
  outliers.

## Notebook Integration

The implementation is one new visible marimo cell immediately after the cell
that defines `subcategory_clusters`. It reuses the notebook's existing
`altair`, `marimo`, and `polars` imports. Intermediate variables remain private
to preserve marimo's single-definition dataflow rules.

If `subcategory_clusters` is empty, the cell displays an informational callout
instead of attempting to render charts.

## Verification

Run:

```sh
.venv/bin/marimo check seed_diversity.py
.venv/bin/python -m compileall seed_diversity.py
git diff --check -- seed_diversity.py
```

If a live marimo session is available, run the new cell and inspect both charts
for readable labels, complete tooltips, and honest scales.
