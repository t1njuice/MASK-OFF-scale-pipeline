# Seed and Subcategory Similarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `seed_diversity.py` with an interactive category view for seed files and a 40-point semantic-distance view for every top-level category's subcategories.

**Architecture:** Keep all computation in the existing marimo notebook and reuse its cached OpenAI embeddings, numpy cosine math, PCA-by-SVD, Polars tables, and Altair charts. Add one Markdown taxonomy file parsed by a strict stdlib helper, pure numerical helpers covered by the existing assert-based test script, and reactive chart detail cells using `mo.ui.altair_chart(...).value`.

**Tech Stack:** Python 3.13, marimo 0.23.13+, numpy, Polars, Altair 6.2.2+, OpenAI `text-embedding-3-small`.

## Global Constraints

- Add no dependencies.
- Preserve the existing folder-level lexical metrics, histogram, redundancy tables, and PCA scatter.
- Store the supplied taxonomy as Markdown with exactly 14 headings, 40 subcategories per heading, and 560 unique subcategories.
- Contextualize every subcategory embedding as `"{top-level category}: {subcategory}"`.
- Treat non-domain `variation:` tags as “not comparable,” not category disagreements.
- Use exact cosine values for evidence; label PCA as an approximate orientation view.
- Do not add UMAP, HDBSCAN, scipy, sklearn, threshold configuration, or a global 560-point projection.
- Do not assign seed files to subcategories.
- Do not make a paid embedding request during verification without confirming that the user wants a cold-cache run.
- Preserve all unrelated working-tree changes.

---

### Task 1: Repair the Existing Pair-Type Baseline

**Files:**
- Modify: `seed_diversity.py:15-21`
- Test: `test_seed_diversity.py:75-78`

**Interfaces:**
- Consumes: `left_tag: str | None`, `right_tag: str | None`, `has_tags: bool`
- Produces: `pair_type(left_tag, right_tag, has_tags) -> str`

- [ ] **Step 1: Run the existing focused check and confirm the baseline failure**

Run:

```bash
uv run python test_seed_diversity.py
```

Expected: FAIL while importing `pair_type` because `seed_diversity.py` calls and
the test imports a helper that is not currently defined.

- [ ] **Step 2: Add the minimal missing helper**

Insert after `short_label`:

```python
@app.function(hide_code=True)
def pair_type(left_tag, right_tag, has_tags):
    if not has_tags:
        return "All pairs"
    if left_tag is None or right_tag is None:
        return "Missing variation"
    if left_tag == right_tag:
        return "Same variation"
    return "Different variation"
```

- [ ] **Step 3: Run the focused check**

Run:

```bash
uv run python test_seed_diversity.py
```

Expected: PASS, including the four existing `pair_type` assertions.

- [ ] **Step 4: Commit the baseline repair**

```bash
git add seed_diversity.py test_seed_diversity.py
git commit -m "Fix seed similarity pair labels"
```

---

### Task 2: Add and Validate the 14×40 Taxonomy

**Files:**
- Create: `seed_subcategories.md`
- Modify: `seed_diversity.py:15-29`
- Modify: `test_seed_diversity.py:6-13`

**Interfaces:**
- Consumes: Markdown text containing `# Category` headings and `- subcategory` items
- Produces: `parse_taxonomy(text: str) -> dict[str, list[str]]`
- Produces: `taxonomy_embedding_rows(taxonomy: dict[str, list[str]]) -> list[dict[str, str]]`

- [ ] **Step 1: Add the exact taxonomy source file**

Create `seed_subcategories.md` using the exact contents of:

```text
/Users/antyabharahman/.codex/attachments/777453e6-ab3b-4870-92ed-50e3ccaae0e3/pasted-text.txt
```

Do not shorten parenthetical category guidance or normalize spelling. Verify
the created file before continuing:

```bash
shasum -a 256 seed_subcategories.md
wc -l -w -c seed_subcategories.md
```

Expected:

```text
d1e33c4b53c26bb8fbc146f455e90d679f4098323dc01bcc2bc63603e45b3bf4  seed_subcategories.md
600 3464 24905 seed_subcategories.md
```

- [ ] **Step 2: Write failing taxonomy assertions**

Extend the import from `seed_diversity`:

```python
from seed_diversity import (
    compression_ratio,
    cosine_matrix,
    pair_type,
    parse_taxonomy,
    taxonomy_embedding_rows,
)
```

Add after `root = Path(__file__).parent`:

```python
taxonomy_text = (root / "seed_subcategories.md").read_text(encoding="utf-8")
taxonomy = parse_taxonomy(taxonomy_text)
assert len(taxonomy) == 14
assert all(len(subcategories) == 40 for subcategories in taxonomy.values())
assert sum(map(len, taxonomy.values())) == 560
assert len({item for items in taxonomy.values() for item in items}) == 560

taxonomy_rows = taxonomy_embedding_rows(taxonomy)
assert len(taxonomy_rows) == 560
assert taxonomy_rows[0] == {
    "category": "Consumer / product safety",
    "subcategory": "children's products & nursery gear",
    "embedding_text": (
        "Consumer / product safety: "
        "children's products & nursery gear"
    ),
}

duplicate_taxonomy = taxonomy_text.replace(
    "- battery-powered consumer devices",
    "- children's products & nursery gear - toys and play equipment",
    1,
)
try:
    parse_taxonomy(duplicate_taxonomy)
except ValueError as error:
    assert str(error) == "Taxonomy subcategories must be unique."
else:
    raise AssertionError("Duplicate taxonomy label was accepted.")
```

- [ ] **Step 3: Run the check and confirm the helper failure**

Run:

```bash
uv run python test_seed_diversity.py
```

Expected: FAIL because `parse_taxonomy` and `taxonomy_embedding_rows` do not
exist.

- [ ] **Step 4: Implement the strict parser and embedding-row helper**

Insert after `pair_type`:

```python
@app.function(hide_code=True)
def parse_taxonomy(text):
    taxonomy = {}
    category = None
    for line in text.splitlines():
        if line.startswith("# "):
            category = line[2:].strip()
            if not category or category in taxonomy:
                raise ValueError("Taxonomy categories must be unique and non-empty.")
            taxonomy[category] = []
        elif line.startswith("- "):
            if category is None:
                raise ValueError("Taxonomy item appears before its category.")
            subcategory = line[2:].strip()
            if not subcategory:
                raise ValueError("Taxonomy subcategories must be non-empty.")
            taxonomy[category].append(subcategory)
        elif line.strip():
            raise ValueError(f"Unexpected taxonomy line: {line}")

    if len(taxonomy) != 14:
        raise ValueError("Taxonomy must contain exactly 14 categories.")
    if any(len(subcategories) != 40 for subcategories in taxonomy.values()):
        raise ValueError("Every taxonomy category must contain exactly 40 items.")
    labels = [item for items in taxonomy.values() for item in items]
    if len(set(labels)) != 560:
        raise ValueError("Taxonomy subcategories must be unique.")
    return taxonomy


@app.function(hide_code=True)
def taxonomy_embedding_rows(taxonomy):
    return [
        {
            "category": category,
            "subcategory": subcategory,
            "embedding_text": f"{category}: {subcategory}",
        }
        for category, subcategories in taxonomy.items()
        for subcategory in subcategories
    ]
```

- [ ] **Step 5: Run the taxonomy check**

Run:

```bash
uv run python test_seed_diversity.py
```

Expected: PASS with 14 categories, 40 entries per category, and 560 unique
subcategory labels.

- [ ] **Step 6: Commit the taxonomy boundary**

```bash
git add seed_subcategories.md seed_diversity.py test_seed_diversity.py
git commit -m "Add seed harm subcategory taxonomy"
```

---

### Task 3: Add Reusable Category and Projection Math

**Files:**
- Modify: `seed_diversity.py:21-29`
- Modify: `test_seed_diversity.py:63-78`

**Interfaces:**
- Consumes: item and category embedding matrices
- Produces: `category_assignments(item_embeddings, category_embeddings) -> list[tuple[int, float, float]]`
- Produces: `pca_coordinates(embeddings) -> numpy.ndarray`
- Produces: `nearest_neighbours(labels, similarities, selected_index) -> list[tuple[str, float]]`

- [ ] **Step 1: Add failing numerical assertions**

Append after the existing cosine assertions:

```python
assignments = category_assignments(
    [[1.0, 0.0], [0.0, 1.0]],
    [[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]],
)
assert assignments[0][0] == 0
assert np.isclose(assignments[0][1], 1.0)
assert assignments[0][2] > 0
assert assignments[1][0] == 2
assert np.isclose(assignments[1][1], 1.0)

single_point = pca_coordinates([[3.0, 4.0]])
assert single_point.shape == (1, 2)
assert np.allclose(single_point, 0.0)

projected = pca_coordinates([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
assert projected.shape == (3, 2)
assert np.allclose(projected.mean(axis=0), 0.0)

neighbours = nearest_neighbours(
    ["selected", "near", "far", "middle"],
    np.asarray(
        [
            [1.0, 0.9, 0.1, 0.5],
            [0.9, 1.0, 0.2, 0.4],
            [0.1, 0.2, 1.0, 0.3],
            [0.5, 0.4, 0.3, 1.0],
        ]
    ),
    0,
)
assert neighbours == [("near", 0.9), ("middle", 0.5), ("far", 0.1)]
```

Extend the import block with:

```python
    category_assignments,
    nearest_neighbours,
    pca_coordinates,
```

- [ ] **Step 2: Run the check and confirm missing helpers**

Run:

```bash
uv run python test_seed_diversity.py
```

Expected: FAIL while importing the new numerical helpers.

- [ ] **Step 3: Implement the three pure helpers**

Insert after `cosine_matrix`:

```python
@app.function(hide_code=True)
def category_assignments(item_embeddings, category_embeddings):
    import numpy as np

    items = np.asarray(item_embeddings, dtype=float)
    categories = np.asarray(category_embeddings, dtype=float)
    items /= np.linalg.norm(items, axis=1, keepdims=True)
    categories /= np.linalg.norm(categories, axis=1, keepdims=True)
    scores = items @ categories.T
    ranking = np.argsort(scores, axis=1)[:, ::-1]
    return [
        (
            int(order[0]),
            float(scores[index, order[0]]),
            float(scores[index, order[0]] - scores[index, order[1]]),
        )
        for index, order in enumerate(ranking)
    ]


@app.function(hide_code=True)
def pca_coordinates(embeddings):
    import numpy as np

    matrix = np.asarray(embeddings, dtype=float)
    if len(matrix) == 1:
        return np.zeros((1, 2))
    normalized = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    centered = normalized - normalized.mean(axis=0)
    _, _, components = np.linalg.svd(centered, full_matrices=False)
    coordinates = centered @ components[:2].T
    if coordinates.shape[1] == 1:
        coordinates = np.column_stack([coordinates, np.zeros(len(matrix))])
    return coordinates


@app.function(hide_code=True)
def nearest_neighbours(labels, similarities, selected_index):
    import numpy as np

    ranking = np.argsort(similarities[selected_index])[::-1]
    return [
        (labels[index], float(similarities[selected_index, index]))
        for index in ranking
        if index != selected_index
    ][:3]
```

- [ ] **Step 4: Replace the existing inline PCA calculation**

In the existing PCA cell around `seed_diversity.py:338-347`, replace:

```python
    _normalized = embedding_matrix / np.linalg.norm(
        embedding_matrix,
        axis=1,
        keepdims=True,
    )
    _centered = _normalized - _normalized.mean(axis=0)
    _, _, _components = np.linalg.svd(_centered, full_matrices=False)
    _coordinates = _centered @ _components[:2].T
```

with:

```python
    _coordinates = pca_coordinates(embedding_matrix)
```

Add `pca_coordinates` to that cell's dependency signature.

- [ ] **Step 5: Run the focused check and marimo linter**

Run:

```bash
uv run python test_seed_diversity.py
uv run marimo check seed_diversity.py
```

Expected: both PASS.

- [ ] **Step 6: Commit the reusable math**

```bash
git add seed_diversity.py test_seed_diversity.py
git commit -m "Add seed category similarity helpers"
```

---

### Task 4: Build the Seed Category Small-Multiples Explorer

**Files:**
- Modify: `seed_diversity.py:65-76`
- Modify: `seed_diversity.py:201-213`
- Add cells before the existing global PCA cell at `seed_diversity.py:338`

**Interfaces:**
- Consumes: `seeds`, `embedding_matrix`, `category_names`, `category_embeddings`
- Produces: `seed_category_points: polars.DataFrame`
- Produces: `seed_category_chart: marimo.ui.altair_chart`

- [ ] **Step 1: Add a taxonomy-loading cell before embedding**

Insert after the seed-loading cell:

```python
@app.cell
def _(Path, mo):
    _taxonomy_path = Path(__file__).with_name("seed_subcategories.md")
    taxonomy = parse_taxonomy(_taxonomy_path.read_text(encoding="utf-8"))
    taxonomy_rows = taxonomy_embedding_rows(taxonomy)
    category_names = list(taxonomy)
    mo.md(
        f"Loaded **{len(category_names)}** categories and "
        f"**{len(taxonomy_rows)}** subcategories from `{_taxonomy_path.name}`."
    )
    return category_names, taxonomy, taxonomy_rows
```

- [ ] **Step 2: Extend the embedding cell with category and subcategory slices**

Replace the body of the existing embedding cell with:

```python
@app.cell
def _(
    Path,
    category_names,
    folder,
    mo,
    np,
    seeds,
    taxonomy_rows,
):
    _cache_path = Path(__file__).with_name(".embed_cache.json")
    _seed_texts = seeds["setting"].to_list()
    _subcategory_texts = [row["embedding_text"] for row in taxonomy_rows]
    _all_texts = _seed_texts + category_names + _subcategory_texts
    _all_embeddings = np.asarray(
        embed_texts(_all_texts, _cache_path),
        dtype=float,
    )

    _seed_end = len(_seed_texts)
    _category_end = _seed_end + len(category_names)
    embedding_matrix = _all_embeddings[:_seed_end]
    category_embeddings = _all_embeddings[_seed_end:_category_end]
    subcategory_embedding_matrix = _all_embeddings[_category_end:]
    similarities = cosine_matrix(embedding_matrix)
    mo.md(
        f"Embedded **{len(seeds)}** parsed seeds from `{folder.name}`, "
        f"**{len(category_names)}** categories, and "
        f"**{len(taxonomy_rows)}** subcategories."
    )
    return (
        category_embeddings,
        embedding_matrix,
        similarities,
        subcategory_embedding_matrix,
    )
```

- [ ] **Step 3: Build seed classification and per-category coordinates**

Insert a cell before the current global PCA cell:

```python
@app.cell
def _(
    category_embeddings,
    category_names,
    embedding_matrix,
    np,
    pl,
    seeds,
):
    _assignments = category_assignments(
        embedding_matrix,
        category_embeddings,
    )
    _category_keys = {
        short_label(category).casefold(): category for category in category_names
    }
    _rows = []
    _seed_records = seeds.to_dicts()

    for _category_index, _category in enumerate(category_names):
        _indices = [
            index
            for index, assignment in enumerate(_assignments)
            if assignment[0] == _category_index
        ]
        if not _indices:
            continue

        _local_embeddings = embedding_matrix[_indices]
        _coordinates = pca_coordinates(_local_embeddings)
        _local_similarities = cosine_matrix(_local_embeddings)
        _local_names = [_seed_records[index]["filename"] for index in _indices]

        for _position, _seed_index in enumerate(_indices):
            _record = _seed_records[_seed_index]
            _tag = _record["tag"]
            _tag_key = short_label(_tag).casefold() if _tag else None
            if _tag_key is None:
                _agreement = "missing"
            elif _tag_key not in _category_keys:
                _agreement = "not comparable"
            elif _category_keys[_tag_key] == _category:
                _agreement = "agree"
            else:
                _agreement = "disagree"

            _neighbour = (
                nearest_neighbours(
                    _local_names,
                    _local_similarities,
                    _position,
                )[0]
                if len(_indices) > 1
                else (None, None)
            )
            _rows.append(
                {
                    **_record,
                    "predicted_category": _category,
                    "category_short": short_label(_category),
                    "tag_agreement": _agreement,
                    "category_score": _assignments[_seed_index][1],
                    "category_margin": _assignments[_seed_index][2],
                    "nearest_in_category": _neighbour[0],
                    "nearest_cosine": _neighbour[1],
                    "pc1": float(_coordinates[_position, 0]),
                    "pc2": float(_coordinates[_position, 1]),
                }
            )

    seed_category_points = pl.DataFrame(_rows)
    return (seed_category_points,)
```

- [ ] **Step 4: Render selectable small multiples**

Insert the next cell:

```python
@app.cell
def _(alt, mo, seed_category_points):
    _chart = (
        alt.Chart(seed_category_points)
        .mark_circle(size=90)
        .encode(
            x=alt.X("pc1:Q", title=None, axis=None),
            y=alt.Y("pc2:Q", title=None, axis=None),
            color=alt.Color(
                "category_short:N",
                title="Predicted category",
                legend=None,
            ),
            facet=alt.Facet(
                "category_short:N",
                columns=3,
                title=None,
                header=alt.Header(labelLimit=220),
            ),
            tooltip=[
                alt.Tooltip("filename:N", title="File"),
                alt.Tooltip("predicted_category:N", title="Predicted category"),
                alt.Tooltip("tag:N", title="Existing variation"),
                alt.Tooltip("setting:N", title="Setting/role"),
                alt.Tooltip("nearest_in_category:N", title="Closest seed"),
                alt.Tooltip(
                    "nearest_cosine:Q",
                    title="Closest cosine",
                    format=".3f",
                ),
            ],
        )
        .properties(width=220, height=160)
        .resolve_scale(x="independent", y="independent")
    )
    seed_category_chart = mo.ui.altair_chart(_chart)
    mo.vstack(
        [
            mo.md(
                "## Seeds within predicted categories\n\n"
                "Each panel has its own PCA projection. Use the numeric cosine "
                "values in the selected-seed details as evidence."
            ),
            seed_category_chart,
        ]
    )
    return (seed_category_chart,)
```

- [ ] **Step 5: Add the selected-seed detail cell**

```python
@app.cell
def _(mo, pl, seed_category_chart):
    _selected = seed_category_chart.value
    if len(_selected) == 0:
        _details = mo.callout(
            "Select a seed point to inspect its filename and nearest neighbour.",
            kind="info",
        )
    else:
        _row = _selected.iloc[0].to_dict()
        _details = mo.ui.table(
            pl.DataFrame(
                [
                    {
                        "filename": _row["filename"],
                        "predicted_category": _row["predicted_category"],
                        "existing_tag": _row["tag"],
                        "tag_agreement": _row["tag_agreement"],
                        "category_score": round(_row["category_score"], 3),
                        "runner_up_margin": round(_row["category_margin"], 3),
                        "nearest_in_category": _row["nearest_in_category"],
                        "nearest_cosine": (
                            round(_row["nearest_cosine"], 3)
                            if _row["nearest_cosine"] is not None
                            else None
                        ),
                    }
                ]
            ),
            pagination=False,
        )
    _details
    return
```

- [ ] **Step 6: Run deterministic checks**

Run:

```bash
uv run python test_seed_diversity.py
uv run marimo check seed_diversity.py
uv run python -m compileall seed_diversity.py
```

Expected: all PASS. Do not run a cold embedding call in this task.

- [ ] **Step 7: Commit the seed category explorer**

```bash
git add seed_diversity.py
git commit -m "Add seed category similarity explorer"
```

---

### Task 5: Build the 40-Point Subcategory Similarity Explorer

**Files:**
- Add cells in `seed_diversity.py` after the seed category explorer

**Interfaces:**
- Consumes: `taxonomy`, `taxonomy_rows`, `subcategory_embedding_matrix`
- Produces: `subcategory_selector: marimo.ui.dropdown`
- Produces: `selected_subcategory_labels: list[str]`
- Produces: `selected_subcategory_similarities: numpy.ndarray`
- Produces: `subcategory_chart: marimo.ui.altair_chart`

- [ ] **Step 1: Add the category selector**

```python
@app.cell
def _(mo, taxonomy):
    subcategory_selector = mo.ui.dropdown(
        options=list(taxonomy),
        value=list(taxonomy)[0],
        label="Top-level category",
        full_width=True,
    )
    mo.vstack(
        [
            mo.md(
                "## Subcategory semantic similarity\n\n"
                "Each point is one taxonomy subcategory. The projection is "
                "approximate; the selected point's cosine ranking is exact."
            ),
            subcategory_selector,
        ]
    )
    return (subcategory_selector,)
```

- [ ] **Step 2: Compute the selected category's projection and summary**

```python
@app.cell
def _(
    mo,
    np,
    pl,
    subcategory_embedding_matrix,
    subcategory_selector,
    taxonomy_rows,
):
    _category = subcategory_selector.value
    _indices = [
        index
        for index, row in enumerate(taxonomy_rows)
        if row["category"] == _category
    ]
    _rows = [taxonomy_rows[index] for index in _indices]
    _embeddings = subcategory_embedding_matrix[_indices]
    _coordinates = pca_coordinates(_embeddings)
    selected_subcategory_similarities = cosine_matrix(_embeddings)
    selected_subcategory_labels = [row["subcategory"] for row in _rows]
    subcategory_points = pl.DataFrame(
        {
            "category": [_category] * len(_rows),
            "subcategory": selected_subcategory_labels,
            "pc1": _coordinates[:, 0],
            "pc2": _coordinates[:, 1],
        }
    )

    _pairwise = selected_subcategory_similarities[
        np.triu_indices(len(_rows), k=1)
    ]
    subcategory_summary = pl.DataFrame(
        [
            {
                "subcategories": len(_rows),
                "mean_similarity": round(float(_pairwise.mean()), 3),
                "median_similarity": round(float(np.median(_pairwise)), 3),
                "p90_similarity": round(float(np.quantile(_pairwise, 0.9)), 3),
                "mean_cosine_distance": round(
                    float(1.0 - _pairwise.mean()),
                    3,
                ),
            }
        ]
    )
    mo.ui.table(subcategory_summary, pagination=False)
    return (
        selected_subcategory_labels,
        selected_subcategory_similarities,
        subcategory_points,
    )
```

- [ ] **Step 3: Render one selectable point per subcategory**

```python
@app.cell
def _(alt, mo, subcategory_points):
    _chart = (
        alt.Chart(subcategory_points)
        .mark_circle(size=105, color="#fb7185")
        .encode(
            x=alt.X("pc1:Q", title="PCA 1"),
            y=alt.Y("pc2:Q", title="PCA 2"),
            tooltip=[
                alt.Tooltip("subcategory:N", title="Subcategory"),
                alt.Tooltip("category:N", title="Category"),
            ],
        )
        .properties(
            title="Subcategory embedding projection",
            height=480,
        )
        .interactive()
    )
    subcategory_chart = mo.ui.altair_chart(_chart)
    subcategory_chart
    return (subcategory_chart,)
```

- [ ] **Step 4: Add the selected-subcategory nearest-neighbour table**

```python
@app.cell
def _(
    mo,
    pl,
    selected_subcategory_labels,
    selected_subcategory_similarities,
    subcategory_chart,
):
    _selected = subcategory_chart.value
    if len(_selected) == 0:
        _details = mo.callout(
            "Select a subcategory point to see its three closest labels.",
            kind="info",
        )
    else:
        _selected_label = _selected.iloc[0]["subcategory"]
        _selected_index = selected_subcategory_labels.index(_selected_label)
        _neighbours = nearest_neighbours(
            selected_subcategory_labels,
            selected_subcategory_similarities,
            _selected_index,
        )
        _details = mo.vstack(
            [
                mo.md(f"### {_selected_label}"),
                mo.ui.table(
                    pl.DataFrame(
                        [
                            {
                                "nearest_subcategory": label,
                                "cosine_similarity": round(similarity, 3),
                            }
                            for label, similarity in _neighbours
                        ]
                    ),
                    pagination=False,
                ),
            ]
        )
    _details
    return
```

Do not add nearest-neighbour lines in the first version. The three-row numeric
table is clearer and avoids another chart data transform.

- [ ] **Step 5: Run deterministic checks**

Run:

```bash
uv run python test_seed_diversity.py
uv run marimo check seed_diversity.py
uv run python -m compileall seed_diversity.py
```

Expected: all PASS.

- [ ] **Step 6: Commit the subcategory explorer**

```bash
git add seed_diversity.py
git commit -m "Add subcategory similarity map"
```

---

### Task 6: Clean Scratch State and Verify the Live Notebook

**Files:**
- Modify: `.gitignore`
- Verify: `seed_diversity.py`
- Verify: `seed_subcategories.md`
- Verify: `test_seed_diversity.py`

**Interfaces:**
- Consumes: completed notebook and deterministic checks
- Produces: clean validation result and a live interaction check

- [ ] **Step 1: Ignore the brainstorm scratch directory**

Append only this line if it is not already present:

```gitignore
.superpowers/
```

Do not modify or revert any other `.gitignore` lines.

- [ ] **Step 2: Run all non-API verification**

```bash
uv run python test_seed_diversity.py
uv run marimo check seed_diversity.py
uv run python -m compileall seed_diversity.py mask_off
git diff --check
```

Expected: every command exits successfully.

- [ ] **Step 3: Inspect whether the live run needs a paid call**

Check without printing credentials:

```bash
test -n "$OPENAI_API_KEY" && echo "OPENAI_API_KEY is set" || echo "OPENAI_API_KEY is not set"
test -f .embed_cache.json && echo "embedding cache exists" || echo "embedding cache is cold"
```

If the cache does not already contain the 574 taxonomy/category texts, tell the
user that the first live run will make one batched embeddings request and get
confirmation before running it.

- [ ] **Step 4: Verify the notebook interactively**

Use the `marimo-pair` skill or run:

```bash
uv run marimo edit seed_diversity.py
```

Verify:

1. the configured seed folder loads;
2. the seed explorer renders one panel per occupied predicted category;
3. selecting a seed updates filename, category, nearest seed, cosine, score,
   and margin;
4. a pressure/harm-type `variation:` tag displays “not comparable”;
5. the subcategory selector shows all 14 categories;
6. selecting Consumer / product safety renders exactly 40 points;
7. selecting a subcategory shows three different nearest labels;
8. switching to Medical / healthcare rerenders 40 points and clears or updates
   stale selection details.

- [ ] **Step 5: Commit the verification cleanup**

```bash
git add .gitignore
git commit -m "Ignore brainstorm scratch files"
```

- [ ] **Step 6: Review the final scoped diff**

```bash
git status --short
git diff 76fd6f8..HEAD -- seed_diversity.py seed_subcategories.md test_seed_diversity.py .gitignore
```

Confirm the diff contains only the taxonomy, notebook explorers, focused tests,
the repaired helper, and the one ignore rule. Leave every unrelated user-owned
change untouched.
