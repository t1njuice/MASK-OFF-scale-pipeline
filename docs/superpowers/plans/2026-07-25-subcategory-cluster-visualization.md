# Subcategory Cluster Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a marimo cell that visualizes subcategory cluster composition and centroid cohesion without recomputing the clustering.

**Architecture:** Derive a complete cluster-by-category composition grid from the existing `subcategory_clusters` DataFrame, then render it as an Altair heatmap. Render the row-level centroid similarities as a second Altair point chart and stack both charts in one marimo output.

**Tech Stack:** Python 3.13, marimo, Polars, Altair

## Global Constraints

- Modify only `seed_diversity.py`; preserve all unrelated uncommitted work.
- Add one visible cell immediately after the cell that defines `subcategory_clusters`.
- Consume existing `subcategory_clusters`; do not call the embeddings API or rerun clustering.
- Use a blue sequential scale for heatmap share.
- Distinguish majority matches with both colour and shape.
- Display an informational callout when `subcategory_clusters` is empty.
- Do not commit `seed_diversity.py` because it already contains overlapping uncommitted user work.

---

### Task 1: Add and verify the cluster-quality visualization cell

**Files:**

- Modify: `seed_diversity.py:972`
- Reference: `docs/superpowers/specs/2026-07-25-subcategory-cluster-visualization-design.md`

**Interfaces:**

- Consumes: `subcategory_clusters: pl.DataFrame`, `category_names: list[str]`, `alt`, `mo`, `pl`, and the existing `short_label(category: str) -> str`
- Produces: `cluster_quality_visualization`, a marimo display object containing either both Altair charts or an informational callout

- [ ] **Step 1: Confirm the public output name does not already exist**

Run:

```sh
rg -n "cluster_quality_visualization" seed_diversity.py
```

Expected: no matches.

- [ ] **Step 2: Add the visualization cell after `subcategory_clusters`**

Add this cell before the `if __name__ == "__main__":` block:

```python
@app.cell
def _(alt, category_names, mo, pl, subcategory_clusters):
    if subcategory_clusters.is_empty():
        cluster_quality_visualization = mo.callout(
            "No clustered subcategories are available to visualize.",
            kind="info",
        )
    else:
        _clusters = sorted(subcategory_clusters["cluster"].unique().to_list())
        _category_order = [short_label(name) for name in category_names]
        _cluster_sizes = {
            row["cluster"]: row["subcategories"]
            for row in (
                subcategory_clusters.group_by("cluster")
                .agg(pl.len().alias("subcategories"))
                .to_dicts()
            )
        }
        _counts = {
            (row["cluster"], row["source_category"]): row["count"]
            for row in (
                subcategory_clusters.group_by(["cluster", "source_category"])
                .agg(pl.len().alias("count"))
                .to_dicts()
            )
        }
        _composition = pl.DataFrame(
            [
                {
                    "cluster": cluster,
                    "source_category": category,
                    "category_short": short_label(category),
                    "count": _counts.get((cluster, category), 0),
                    "share": (
                        _counts.get((cluster, category), 0)
                        / _cluster_sizes[cluster]
                    ),
                }
                for cluster in _clusters
                for category in category_names
            ]
        )
        _point_data = subcategory_clusters.with_columns(
            pl.when(pl.col("matches_majority"))
            .then(pl.lit("Matches majority"))
            .otherwise(pl.lit("Different category"))
            .alias("match_status")
        )

        _heatmap = (
            alt.Chart(_composition)
            .mark_rect(stroke="#f8fafc", strokeWidth=0.5)
            .encode(
                x=alt.X(
                    "category_short:N",
                    sort=_category_order,
                    title="Original category",
                    axis=alt.Axis(labelAngle=-45, labelLimit=170),
                ),
                y=alt.Y("cluster:O", sort=_clusters, title="Cluster"),
                color=alt.Color(
                    "share:Q",
                    title="Share",
                    scale=alt.Scale(domain=[0, 1], scheme="blues"),
                ),
                tooltip=[
                    alt.Tooltip("cluster:O", title="Cluster"),
                    alt.Tooltip(
                        "source_category:N",
                        title="Original category",
                    ),
                    alt.Tooltip("count:Q", title="Subcategories"),
                    alt.Tooltip("share:Q", title="Cluster share", format=".1%"),
                ],
            )
            .properties(
                title=alt.TitleParams(
                    text="Category composition by cluster",
                    subtitle="Darker cells indicate a larger share of the cluster.",
                ),
                width=760,
                height=340,
            )
        )
        _cohesion = (
            alt.Chart(_point_data)
            .mark_point(filled=True, size=45, opacity=0.55)
            .encode(
                x=alt.X("cluster:O", sort=_clusters, title="Cluster"),
                y=alt.Y(
                    "cosine_to_centroid:Q",
                    title="Cosine similarity to centroid",
                    scale=alt.Scale(zero=False),
                ),
                color=alt.Color(
                    "match_status:N",
                    title="Category agreement",
                    scale=alt.Scale(
                        domain=["Matches majority", "Different category"],
                        range=["#2563eb", "#f59e0b"],
                    ),
                ),
                shape=alt.Shape(
                    "match_status:N",
                    title="Category agreement",
                    scale=alt.Scale(
                        domain=["Matches majority", "Different category"],
                        range=["circle", "triangle-up"],
                    ),
                ),
                tooltip=[
                    alt.Tooltip("subcategory:N", title="Subcategory"),
                    alt.Tooltip("source_category:N", title="Original category"),
                    alt.Tooltip(
                        "majority_category:N",
                        title="Cluster majority",
                    ),
                    alt.Tooltip("cluster:O", title="Cluster"),
                    alt.Tooltip(
                        "cosine_to_centroid:Q",
                        title="Cosine to centroid",
                        format=".3f",
                    ),
                    alt.Tooltip("match_status:N", title="Agreement"),
                ],
            )
            .properties(
                title=alt.TitleParams(
                    text="Subcategory similarity to cluster centroid",
                    subtitle="Higher values indicate tighter cluster cohesion.",
                ),
                width=760,
                height=300,
            )
        )
        cluster_quality_visualization = mo.vstack(
            [
                mo.md(
                    "## Cluster quality visualization\n\n"
                    "The heatmap shows category purity and mixing; the point "
                    "chart shows how tightly individual subcategories fit "
                    "their assigned cluster."
                ),
                _heatmap,
                _cohesion,
            ]
        )

    cluster_quality_visualization
    return (cluster_quality_visualization,)
```

- [ ] **Step 3: Validate marimo's dependency graph**

Run:

```sh
.venv/bin/marimo check seed_diversity.py
```

Expected: exit status 0 with no issues.

- [ ] **Step 4: Validate syntax and whitespace**

Run:

```sh
.venv/bin/python -m compileall seed_diversity.py
git diff --check -- seed_diversity.py
```

Expected: both commands exit with status 0.

- [ ] **Step 5: Inspect the scoped diff**

Run:

```sh
git diff -- seed_diversity.py
```

Expected: the existing uncommitted clustering work remains intact and the only
new change from this task is the visualization cell. Leave the notebook
unstaged so unrelated user-owned edits are not included in a commit.
