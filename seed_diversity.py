import marimo

__generated_with = "0.23.13"
app = marimo.App(width="full")


@app.function(hide_code=True)
def compression_ratio(texts):
    import gzip

    raw = "\n".join(texts).encode("utf-8")
    return len(raw) / len(gzip.compress(raw, mtime=0))


@app.function(hide_code=True)
def short_label(category):
    """Legend-sized name: TAXONOMY entries carry long parenthetical guidance."""
    return category.split("(")[0].strip()


@app.function(hide_code=True)
def pair_type(left_tag, right_tag, has_tags):
    if not has_tags:
        return "All pairs"
    if left_tag is None or right_tag is None:
        return "Missing variation"
    if left_tag == right_tag:
        return "Same variation"
    return "Different variation"


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


@app.function(hide_code=True)
def cosine_matrix(embeddings):
    import numpy as np

    matrix = np.asarray(embeddings, dtype=float)
    normalized = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    return normalized @ normalized.T


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


@app.function(hide_code=True)
def embed_texts(texts, cache_path):
    import hashlib
    import json

    from dotenv import load_dotenv
    from openai import OpenAI

    keys = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        cache = {}

    missing = {
        key: text for key, text in zip(keys, texts, strict=True) if key not in cache
    }
    if missing:
        load_dotenv(cache_path.with_name(".env"))
        response = OpenAI().embeddings.create(
            model="text-embedding-3-small",
            input=list(missing.values()),
        )
        results = sorted(response.data, key=lambda result: result.index)
        cache.update(
            {
                key: result.embedding
                for key, result in zip(missing, results, strict=True)
            }
        )
        cache_path.write_text(json.dumps(cache), encoding="utf-8")

    return [cache[key] for key in keys]


@app.cell
def _():
    from pathlib import Path

    import altair as alt
    import marimo as mo
    import numpy as np
    import polars as pl

    from mask_off.seeds import setting_key, variation_tag

    return Path, alt, mo, np, pl, setting_key, variation_tag


@app.cell
def _(mo):
    mo.md(r"""
    # Seed setting/role diversity

    Compare one seed folder at a time. The embedding distribution gives the
    overview; the nearest-neighbour tables identify seeds worth rewriting.
    """)
    return


@app.cell
def _(mo):
    seed_folder = mo.ui.text(
        value="grok_omission/scenarios/seeds",
        label="Seed folder",
        full_width=True,
    )
    seed_folder
    return (seed_folder,)


@app.cell
def _(Path, mo, pl, seed_folder, setting_key, variation_tag):
    folder = Path(seed_folder.value).expanduser()
    if not folder.is_absolute():
        folder = (Path(__file__).parent / folder).resolve()

    mo.stop(
        not folder.is_dir(),
        mo.callout(f"Seed folder does not exist: `{folder}`", kind="danger"),
    )
    _paths = sorted(folder.glob("*.md"))
    mo.stop(
        not _paths,
        mo.callout(f"No Markdown seeds found in: `{folder}`", kind="danger"),
    )

    _records = []
    _unparsed = []
    for _path in _paths:
        _text = _path.read_text(encoding="utf-8")
        _setting = setting_key(_text)
        if _setting is None:
            _unparsed.append(_path.name)
        else:
            _records.append(
                {
                    "filename": _path.name,
                    "tag": variation_tag(_text),
                    "setting": _setting,
                }
            )

    mo.stop(
        not _records,
        mo.callout("No settings or roles could be parsed.", kind="danger"),
    )
    mo.stop(
        len(_records) < 2,
        mo.callout(
            "At least two parsed seeds are required to measure diversity.",
            kind="danger",
        ),
    )
    seeds = pl.DataFrame(_records)
    unparsed = pl.DataFrame({"filename": _unparsed})
    _status = mo.callout(
        f"Loaded **{len(seeds)}** settings from `{folder}`.",
        kind="success",
    )
    mo.vstack(
        [_status]
        if unparsed.is_empty()
        else [
            _status,
            mo.callout(
                "These files were not embedded because their setting marker "
                "was not recognised:",
                kind="warn",
            ),
            mo.ui.table(unparsed, pagination=False),
        ]
    )
    return folder, seeds


@app.cell
def _(mo, pl, seeds):
    _settings = seeds["setting"].to_list()
    lexical_metrics = pl.DataFrame(
        {
            "metric": [
                "Gzip compression ratio (↓ more diverse)",
                "Mean setting length (words)",
            ],
            "value": [
                round(compression_ratio(_settings), 3),
                round(
                    sum(len(text.split()) for text in _settings) / len(_settings),
                    1,
                ),
            ],
        }
    )
    mo.vstack(
        [
            mo.md(
                "## Paper-aligned lexical diversity check\n\n"
                "Following [Shaib et al. (2024)]"
                "(https://arxiv.org/html/2403.00553v1), gzip compression ratio "
                "is reported with text length. Higher compression means more "
                "repeated wording. Compare folders or revisions only when "
                "their typical lengths are similar; the embedding analysis "
                "below remains the semantic check."
            ),
            mo.ui.table(lexical_metrics, pagination=False),
        ]
    )
    return


@app.cell
def _(Path, folder, mo, np, seeds):
    _cache_path = Path(__file__).with_name(".embed_cache.json")
    embedding_matrix = np.asarray(
        embed_texts(seeds["setting"].to_list(), _cache_path),
        dtype=float,
    )
    similarities = cosine_matrix(embedding_matrix)
    mo.md(
        f"Embedded **{len(seeds)}** parsed seeds from `{folder.name}` "
        f"into **{embedding_matrix.shape[1]}** dimensions."
    )
    return embedding_matrix, similarities


@app.cell
def _(pl, seeds, similarities):
    _names = seeds["filename"].to_list()
    _tags = seeds["tag"].to_list()
    _settings = seeds["setting"].to_list()
    _has_tags = any(tag is not None for tag in _tags)
    _pair_rows = []
    for _left in range(len(seeds)):
        for _right in range(_left + 1, len(seeds)):
            _pair_rows.append(
                {
                    "left": _names[_left],
                    "left_tag": _tags[_left],
                    "left_setting": _settings[_left],
                    "right": _names[_right],
                    "right_tag": _tags[_right],
                    "right_setting": _settings[_right],
                    "pair_type": pair_type(
                        _tags[_left],
                        _tags[_right],
                        _has_tags,
                    ),
                    "similarity": float(similarities[_left, _right]),
                }
            )

    pairs = pl.DataFrame(_pair_rows)
    summary = (
        pairs.group_by("pair_type")
        .agg(
            pl.len().alias("pairs"),
            pl.col("similarity").mean().round(3).alias("mean"),
            pl.col("similarity").median().round(3).alias("median"),
            pl.col("similarity").quantile(0.9).round(3).alias("p90"),
        )
        .sort("pair_type")
    )
    return pairs, summary


@app.cell
def _(alt, mo, pairs, summary):
    histogram = (
        alt.Chart(pairs)
        .mark_bar(opacity=0.55)
        .encode(
            x=alt.X(
                "similarity:Q",
                bin=alt.Bin(maxbins=30),
                title="Cosine similarity",
            ),
            y=alt.Y("count():Q", stack=None, title="Pair count"),
            color=alt.Color("pair_type:N", title="Pair type"),
            tooltip=[
                alt.Tooltip("pair_type:N", title="Pair type"),
                alt.Tooltip("count():Q", title="Pairs"),
            ],
        )
        .properties(title="Pairwise setting/role similarity", height=320)
    )
    mo.vstack(
        [
            mo.md("## Similarity distribution"),
            histogram,
            mo.ui.table(summary, pagination=False),
        ]
    )
    return


@app.cell
def _(mo, np, pairs, pl, seeds, similarities):
    _without_diagonal = similarities.copy()
    np.fill_diagonal(_without_diagonal, -np.inf)
    _nearest_indices = _without_diagonal.argmax(axis=1)
    _names = seeds["filename"].to_list()
    _tags = seeds["tag"].to_list()
    _settings = seeds["setting"].to_list()
    _ranking_rows = [
        {
            "filename": _names[_index],
            "tag": _tags[_index],
            "setting": _settings[_index],
            "nearest_neighbour": _names[_nearest],
            "nearest_setting": _settings[_nearest],
            "cosine": float(similarities[_index, _nearest]),
        }
        for _index, _nearest in enumerate(_nearest_indices)
    ]
    redundancy = pl.DataFrame(_ranking_rows).sort("cosine", descending=True)
    top_pairs = (
        pairs.sort("similarity", descending=True)
        .head(20)
        .select(
            "left",
            "left_tag",
            "left_setting",
            "right",
            "right_tag",
            "right_setting",
            "similarity",
        )
    )
    mo.vstack(
        [
            mo.md("## Redundancy ranking"),
            mo.ui.table(
                redundancy,
                page_size=20,
                wrapped_columns=["setting", "nearest_setting"],
            ),
            mo.md("### 20 most-similar pairs"),
            mo.ui.table(
                top_pairs,
                pagination=False,
                wrapped_columns=["left_setting", "right_setting"],
            ),
        ]
    )
    return


@app.cell
def _(alt, embedding_matrix, mo, pca_coordinates, pl, seeds):
    _coordinates = pca_coordinates(embedding_matrix)
    scatter_data = pl.DataFrame(
        {
            "filename": seeds["filename"],
            "tag": [
                tag if tag is not None else "(none)"
                for tag in seeds["tag"].to_list()
            ],
            "setting": seeds["setting"],
            "pc1": _coordinates[:, 0],
            "pc2": _coordinates[:, 1],
        }
    )
    scatter = (
        alt.Chart(scatter_data)
        .mark_circle(size=90)
        .encode(
            x=alt.X("pc1:Q", title="PCA 1"),
            y=alt.Y("pc2:Q", title="PCA 2"),
            color=alt.Color("tag:N", title="Variation"),
            tooltip=[
                alt.Tooltip("filename:N", title="File"),
                alt.Tooltip("tag:N", title="Variation"),
                alt.Tooltip("setting:N", title="Setting/role"),
            ],
        )
        .properties(title="PCA sketch of setting/role embeddings", height=420)
        .interactive()
    )
    mo.vstack(
        [
            mo.md(
                "## PCA scatter\n\n"
                "Orientation only: a 2D projection of this small sample can "
                "manufacture structure that is not present in the rankings."
            ),
            scatter,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
