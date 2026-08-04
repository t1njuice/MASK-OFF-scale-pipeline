import marimo

__generated_with = "0.23.13"
app = marimo.App(width="full")


@app.function(hide_code=True)
def short_label(category):
    """Legend-sized name: TAXONOMY entries carry long parenthetical guidance."""
    return category.split("(")[0].strip()


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
def category_lookup(taxonomy_rows):
    """Return a function mapping a variation tag to its parent category."""
    import difflib
    import re

    def normalize(text):
        text = text.lower().replace("’", "'")
        text = text.replace("“", '"').replace("”", '"')
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    by_normalized = {
        normalize(row["subcategory"]): row["category"] for row in taxonomy_rows
    }

    def lookup(tag):
        key = normalize(tag)
        if key in by_normalized:
            return by_normalized[key]
        # A couple of tags were spelling-corrected after the taxonomy file was
        # written ("sope creep"), so fall back to the closest label.
        match = difflib.get_close_matches(key, by_normalized, n=1, cutoff=0.85)
        return by_normalized[match[0]] if match else "(unmapped)"

    return lookup


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
        client = OpenAI()
        # The endpoint rejects a request over 300k tokens or 2048 inputs. Split
        # on a rough 4-chars-per-token estimate with headroom, so seed-length
        # texts (~300 tokens each) batch without a tokeniser dependency.
        batches, batch, tokens = [], [], 0
        for key, text in missing.items():
            estimate = len(text) // 4 + 1
            if batch and (tokens + estimate > 200_000 or len(batch) >= 1000):
                batches.append(batch)
                batch, tokens = [], 0
            batch.append((key, text))
            tokens += estimate
        if batch:
            batches.append(batch)

        for batch in batches:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=[text for _, text in batch],
            )
            results = sorted(response.data, key=lambda result: result.index)
            cache.update(
                {
                    key: result.embedding
                    for (key, _), result in zip(batch, results, strict=True)
                }
            )
            # Persist per batch so a mid-run failure keeps the earlier calls.
            cache_path.write_text(json.dumps(cache), encoding="utf-8")

    return [cache[key] for key in keys]


@app.function
def spherical_kmeans(matrix, clusters, restarts=10, seed=7):
    """Cosine k-means on unit-norm rows; returns (labels, centres)."""
    import numpy as np

    best = None
    for restart in range(restarts):
        rng = np.random.default_rng(seed + restart)
        centres = [matrix[rng.integers(len(matrix))]]
        while len(centres) < clusters:
            similarity = matrix @ np.vstack(centres).T
            distance = 1.0 - similarity.max(axis=1)
            weights = np.square(np.clip(distance, 0.0, None))
            weights /= weights.sum()
            centres.append(matrix[rng.choice(len(matrix), p=weights)])
        centres = np.vstack(centres)
        labels = np.full(len(matrix), -1, dtype=int)

        for _iteration in range(100):
            scores = matrix @ centres.T
            next_labels = scores.argmax(axis=1)
            # Steal the worst-fitting point for any cluster that emptied out,
            # so the returned label set always covers every requested cluster.
            available = np.ones(len(matrix), dtype=bool)
            for missing in set(range(clusters)) - set(next_labels):
                assigned = scores[np.arange(len(matrix)), next_labels]
                replacement = np.argmin(np.where(available, assigned, np.inf))
                next_labels[replacement] = missing
                available[replacement] = False
            if np.array_equal(labels, next_labels):
                break
            labels = next_labels

            next_centres = []
            for cluster in range(clusters):
                members = matrix[labels == cluster]
                if len(members) == 0:
                    centre = matrix[scores.max(axis=1).argmin()]
                else:
                    centre = members.mean(axis=0)
                    centre /= np.linalg.norm(centre)
                next_centres.append(centre)
            centres = np.vstack(next_centres)

        scores = matrix @ centres.T
        objective = float(scores[np.arange(len(matrix)), labels].sum())
        if best is None or objective > best[0]:
            best = (objective, labels.copy(), centres.copy())

    return best[1], best[2]


@app.cell
def _():
    from collections import Counter
    from pathlib import Path

    import altair as alt
    import marimo as mo
    import numpy as np
    import polars as pl

    from mask_off.seeds import _without_frontmatter as strip_frontmatter
    from mask_off.seeds import setting_key, variation_tag

    return (
        Counter,
        Path,
        alt,
        mo,
        np,
        pl,
        setting_key,
        strip_frontmatter,
        variation_tag,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Unsupervised subcategory clusters

    The taxonomy's raw subcategory labels are embedded and clustered by cosine
    similarity. The supplied category headings are used only after clustering,
    to name each group and score its purity.
    """)
    return


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
    return category_names, taxonomy_rows


@app.cell
def _(Path, category_names, mo, np, pl, taxonomy_rows):
    _raw_subcategories = [row["subcategory"] for row in taxonomy_rows]
    _source_categories = [row["category"] for row in taxonomy_rows]
    _cache_path = Path(__file__).with_name(".embed_cache.json")
    _raw_embeddings = np.asarray(
        embed_texts(_raw_subcategories, _cache_path),
        dtype=float,
    )
    _raw_embeddings /= np.linalg.norm(
        _raw_embeddings,
        axis=1,
        keepdims=True,
    )
    _pairwise_similarities = _raw_embeddings @ _raw_embeddings.T
    np.fill_diagonal(_pairwise_similarities, -np.inf)
    _nearest_indices = _pairwise_similarities.argmax(axis=1)

    def _spherical_kmeans(_matrix, _clusters, _restarts=10, _seed=7):
        _best = None
        for _restart in range(_restarts):
            _rng = np.random.default_rng(_seed + _restart)
            _centres = [_matrix[_rng.integers(len(_matrix))]]
            while len(_centres) < _clusters:
                _similarity = _matrix @ np.vstack(_centres).T
                _distance = 1.0 - _similarity.max(axis=1)
                _weights = np.square(np.clip(_distance, 0.0, None))
                _weights /= _weights.sum()
                _centres.append(_matrix[_rng.choice(len(_matrix), p=_weights)])
            _centres = np.vstack(_centres)
            _labels = np.full(len(_matrix), -1, dtype=int)

            for _iteration in range(100):
                _scores = _matrix @ _centres.T
                _next_labels = _scores.argmax(axis=1)
                _missing_clusters = set(range(_clusters)) - set(_next_labels)
                _available = np.ones(len(_matrix), dtype=bool)
                for _missing_cluster in _missing_clusters:
                    _assigned_scores = _scores[
                        np.arange(len(_matrix)),
                        _next_labels,
                    ]
                    _replacement = np.argmin(
                        np.where(_available, _assigned_scores, np.inf)
                    )
                    _next_labels[_replacement] = _missing_cluster
                    _available[_replacement] = False
                if np.array_equal(_labels, _next_labels):
                    break
                _labels = _next_labels

                _next_centres = []
                for _cluster in range(_clusters):
                    _members = _matrix[_labels == _cluster]
                    if len(_members) == 0:
                        _replacement = _scores.max(axis=1).argmin()
                        _centre = _matrix[_replacement]
                    else:
                        _centre = _members.mean(axis=0)
                        _centre /= np.linalg.norm(_centre)
                    _next_centres.append(_centre)
                _centres = np.vstack(_next_centres)

            _scores = _matrix @ _centres.T
            _objective = float(
                _scores[np.arange(len(_matrix)), _labels].sum()
            )
            if _best is None or _objective > _best[0]:
                _best = (_objective, _labels.copy(), _centres.copy())

        return _best[1], _best[2]

    _cluster_ids, _cluster_centres = _spherical_kmeans(
        _raw_embeddings,
        len(category_names),
    )
    _cluster_scores = _raw_embeddings @ _cluster_centres.T
    _cluster_coordinates = pca_coordinates(_raw_embeddings)
    _cluster_labels = {}
    _summary_rows = []
    for _cluster_id in range(len(category_names)):
        _member_indices = np.flatnonzero(_cluster_ids == _cluster_id)
        _counts = {
            _category: sum(
                _source_categories[_index] == _category
                for _index in _member_indices
            )
            for _category in category_names
        }
        _ranked_categories = sorted(
            _counts.items(),
            key=lambda _item: (
                -_item[1],
                category_names.index(_item[0]),
            ),
        )
        _cluster_label, _largest_group = _ranked_categories[0]
        _cluster_labels[_cluster_id] = _cluster_label
        _composition = ", ".join(
            f"{short_label(_category)}: {_count}"
            for _category, _count in _ranked_categories
            if _count
        )
        _summary_rows.append(
            {
                "cluster": _cluster_id + 1,
                "majority_category": _cluster_label,
                "subcategories": len(_member_indices),
                "purity": round(_largest_group / len(_member_indices), 3),
                "category_composition": _composition,
            }
        )

    subcategory_clusters = pl.DataFrame(
        [
            {
                "subcategory": _subcategory,
                "source_category": _source_category,
                "cluster": int(_cluster_id) + 1,
                "majority_category": _cluster_labels[int(_cluster_id)],
                "matches_majority": (
                    _source_category == _cluster_labels[int(_cluster_id)]
                ),
                "cosine_to_centroid": round(
                    float(_cluster_scores[_index, _cluster_id]),
                    3,
                ),
                "pc1": float(_cluster_coordinates[_index, 0]),
                "pc2": float(_cluster_coordinates[_index, 1]),
                "nearest_subcategory": _raw_subcategories[
                    _nearest_indices[_index]
                ],
                "nearest_source_category": _source_categories[
                    _nearest_indices[_index]
                ],
                "nearest_neighbor_cosine": round(
                    float(
                        _pairwise_similarities[
                            _index,
                            _nearest_indices[_index],
                        ]
                    ),
                    3,
                ),
            }
            for _index, (_subcategory, _source_category, _cluster_id) in enumerate(
                zip(
                    _raw_subcategories,
                    _source_categories,
                    _cluster_ids,
                    strict=True,
                )
            )
        ]
    ).sort(["cluster", "cosine_to_centroid"], descending=[False, True])
    _cluster_summary = pl.DataFrame(_summary_rows).sort("cluster")

    mo.vstack(
        [
            mo.md(
                "## Unsupervised subcategory clusters\n\n"
                "The raw subcategory text is clustered into 14 semantic groups "
                "with cosine-based spherical k-means. The supplied category "
                "headings are used only after clustering to name each group "
                "and calculate purity, so they cannot leak into the features. "
                "The first run embeds the raw labels through OpenAI and stores "
                "them in the existing local cache."
            ),
            mo.ui.table(
                _cluster_summary,
                pagination=False,
                wrapped_columns=["category_composition"],
            ),
            mo.ui.table(
                subcategory_clusters,
                page_size=25,
                wrapped_columns=[
                    "subcategory",
                    "source_category",
                    "majority_category",
                ],
            ),
        ]
    )
    return (subcategory_clusters,)


@app.cell
def _(alt, mo, pl, subcategory_clusters):
    mo.stop(
        subcategory_clusters.is_empty(),
        mo.callout("No clustered subcategories to visualize.", kind="info"),
    )

    _clusters = sorted(subcategory_clusters["cluster"].unique().to_list())
    _base_names = {
        row["cluster"]: short_label(row["majority_category"])
        for row in (
            subcategory_clusters.select("cluster", "majority_category")
            .unique()
            .to_dicts()
        )
    }
    _base_name_totals = {
        name: list(_base_names.values()).count(name)
        for name in set(_base_names.values())
    }
    _base_name_seen = {name: 0 for name in _base_name_totals}
    _cluster_names = {}
    for _cluster in _clusters:
        _base_name = _base_names[_cluster]
        _base_name_seen[_base_name] += 1
        _suffix = chr(64 + _base_name_seen[_base_name])
        _cluster_names[_cluster] = (
            f"{_base_name} ({_suffix})"
            if _base_name_totals[_base_name] > 1
            else _base_name
        )
    _cluster_order = [_cluster_names[cluster] for cluster in _clusters]
    _plot_data = subcategory_clusters.with_columns(
        pl.col("cluster")
        .replace_strict(_cluster_names)
        .alias("cluster_name")
    )
    _cluster_diagram = (
        alt.Chart(_plot_data.filter(pl.col("nearest_neighbor_cosine") <= 0.5))
        .mark_circle(
            opacity=0.72,
            stroke="#ffffff",
            strokeWidth=0.4,
        )
        .encode(
            x=alt.X(
                "pc1:Q",
                title="PCA 1",
                scale=alt.Scale(zero=False),
            ),
            y=alt.Y(
                "pc2:Q",
                title="PCA 2",
                scale=alt.Scale(zero=False),
            ),
            color=alt.Color(
                "cluster_name:N",
                title="Category-like cluster name",
                sort=_cluster_order,
                scale=alt.Scale(scheme="tableau20"),
                legend=alt.Legend(
                    columns=2,
                    orient="right",
                    symbolLimit=20,
                ),
            ),
            size=alt.Size(
                "nearest_neighbor_cosine:Q",
                title="Nearest-neighbour cosine",
                scale=alt.Scale(zero=False, range=[28, 150]),
            ),
            tooltip=[
                alt.Tooltip("subcategory:N", title="Subcategory"),
                alt.Tooltip("source_category:N", title="Original category"),
                alt.Tooltip("cluster_name:N", title="Cluster name"),
                alt.Tooltip(
                    "majority_category:N",
                    title="Cluster majority",
                ),
                alt.Tooltip(
                    "nearest_subcategory:N",
                    title="Nearest subcategory",
                ),
                alt.Tooltip(
                    "nearest_source_category:N",
                    title="Nearest original category",
                ),
                alt.Tooltip(
                    "nearest_neighbor_cosine:Q",
                    title="Nearest-neighbour cosine",
                    format=".3f",
                ),
            ],
        )
        .properties(
            title="Subcategory clusters",
            width=500,
            height=540,
        )
        .configure_axis(
            domainColor="#9ca3af",
            gridColor="#e5e7eb",
            labelColor="#374151",
            titleColor="#111827",
        )
        .configure_view(stroke="#d1d5db")
    )

    mo.vstack(
        [
            mo.md(
                "## Cluster map\n\n"
                "Colour identifies the semantic cluster; larger points have a "
                "more similar nearest neighbour. PCA is only a 2D view - "
                "clustering and pairwise similarity use the full embedding "
                "vectors."
            ),
            mo.ui.altair_chart(_cluster_diagram),
        ]
    )
    return


@app.cell
def _(mo):
    seed_folder = mo.ui.text(
        value="grok_omission/scenarios/seeds",
        label="Seed folder",
        full_width=True,
    )
    seed_embed_field = mo.ui.dropdown(
        options=["Whole seed", "Setting/role only"],
        value="Whole seed",
        label="Text to embed",
    )
    mo.vstack(
        [
            mo.md(
                "## Seed groups by variation\n\n"
                "The seeds already carry their subcategory in the `variation:` "
                "frontmatter, so there is nothing to discover with k-means: each "
                "tag is its own group. Embedding measures how far apart the seeds "
                "*within* a subcategory landed — a high mean pairwise cosine means "
                "that subcategory produced near-duplicates."
            ),
            seed_folder,
            seed_embed_field,
        ]
    )
    return seed_embed_field, seed_folder


@app.cell
def _(
    Path,
    mo,
    pl,
    seed_embed_field,
    seed_folder,
    setting_key,
    strip_frontmatter,
    variation_tag,
):
    _folder = Path(seed_folder.value).expanduser()
    if not _folder.is_absolute():
        _folder = (Path(__file__).parent / _folder).resolve()
    mo.stop(
        not _folder.is_dir(),
        mo.callout(f"Seed folder does not exist: `{_folder}`", kind="danger"),
    )

    _records = []
    _skipped = []
    for _path in sorted(_folder.glob("*.md")):
        _raw = _path.read_text(encoding="utf-8")
        _body = strip_frontmatter(_raw)
        _text = _body if seed_embed_field.value == "Whole seed" else setting_key(_raw)
        if not _text or not _text.strip():
            _skipped.append(_path.name)
            continue
        _records.append(
            {
                "seed": _path.stem,
                "variation": variation_tag(_raw) or "(untagged)",
                "text": " ".join(_text.split()),
            }
        )

    mo.stop(
        not _records,
        mo.callout(f"No usable seeds in `{_folder}`.", kind="danger"),
    )
    seed_records = pl.DataFrame(_records)
    _loaded = mo.callout(
        f"Loaded **{len(seed_records)}** seeds from `{_folder.name}`.",
        kind="success",
    )
    mo.vstack(
        [_loaded]
        if not _skipped
        else [
            _loaded,
            mo.callout(
                "Skipped (no text for the selected field): "
                + ", ".join(_skipped),
                kind="warn",
            ),
        ]
    )
    return (seed_records,)


@app.cell
def _(Path, mo, np, pl, seed_records):
    _embeddings = np.asarray(
        embed_texts(
            seed_records["text"].to_list(),
            Path(__file__).with_name(".embed_cache.json"),
        ),
        dtype=float,
    )
    _embeddings /= np.linalg.norm(_embeddings, axis=1, keepdims=True)
    _pairwise = _embeddings @ _embeddings.T
    np.fill_diagonal(_pairwise, -np.inf)
    _nearest = _pairwise.argmax(axis=1)

    _names = seed_records["seed"].to_list()
    _variations = seed_records["variation"].to_list()
    _coordinates = pca_coordinates(_embeddings)

    _members_by_variation = {}
    for _index, _variation in enumerate(_variations):
        _members_by_variation.setdefault(_variation, []).append(_index)

    _summary_rows = []
    _centroid_cosine = {}
    for _variation, _members in _members_by_variation.items():
        _block = _pairwise[np.ix_(_members, _members)]
        # The diagonal is -inf, so read the pairs off the upper triangle.
        _pairs = _block[np.triu_indices(len(_members), k=1)]
        _centroid = _embeddings[_members].mean(axis=0)
        _centroid /= np.linalg.norm(_centroid)
        for _member in _members:
            _centroid_cosine[_member] = float(_embeddings[_member] @ _centroid)
        _summary_rows.append(
            {
                "variation": _variation,
                "seeds": len(_members),
                "mean_pairwise_cosine": (
                    round(float(_pairs.mean()), 3) if len(_pairs) else None
                ),
                "max_pairwise_cosine": (
                    round(float(_pairs.max()), 3) if len(_pairs) else None
                ),
                # How often the closest seed anywhere in the set is one of
                # this group's own: 1.0 means the subcategory is self-contained.
                "self_nearest_rate": round(
                    sum(_nearest[_member] in set(_members) for _member in _members)
                    / len(_members),
                    3,
                ),
            }
        )

    seed_groups = pl.DataFrame(
        [
            {
                "seed": _name,
                "variation": _variation,
                "cosine_to_group_centroid": round(_centroid_cosine[_index], 3),
                "nearest_seed": _names[_nearest[_index]],
                "nearest_variation": _variations[_nearest[_index]],
                "nearest_is_same_variation": (
                    _variations[_nearest[_index]] == _variation
                ),
                "nearest_cosine": round(float(_pairwise[_index, _nearest[_index]]), 3),
                "pc1": float(_coordinates[_index, 0]),
                "pc2": float(_coordinates[_index, 1]),
            }
            for _index, (_name, _variation) in enumerate(
                zip(_names, _variations, strict=True)
            )
        ]
    ).sort(["variation", "cosine_to_group_centroid"], descending=[False, True])

    seed_group_summary = pl.DataFrame(_summary_rows).sort(
        "mean_pairwise_cosine", descending=True, nulls_last=True
    )
    mo.vstack(
        [
            mo.md(
                f"**{len(seed_group_summary)}** variation groups over "
                f"**{len(seed_groups)}** seeds. Sorted tightest first — the top "
                "rows are the subcategories whose seeds repeat each other."
            ),
            mo.ui.table(seed_group_summary, page_size=25),
            mo.ui.table(seed_groups, page_size=25),
        ]
    )
    return seed_group_summary, seed_groups


@app.cell
def _(alt, mo, seed_group_summary):
    # One point per variation rather than per seed: 260 colours would be an
    # unreadable legend, and the question here is which groups are too tight.
    _chart = (
        alt.Chart(seed_group_summary.drop_nulls("mean_pairwise_cosine"))
        .mark_circle(opacity=0.72, stroke="#ffffff", strokeWidth=0.4)
        .encode(
            x=alt.X(
                "mean_pairwise_cosine:Q",
                title="Mean pairwise cosine within the variation",
                scale=alt.Scale(zero=False),
            ),
            y=alt.Y(
                "max_pairwise_cosine:Q",
                title="Closest pair within the variation",
                scale=alt.Scale(zero=False),
            ),
            color=alt.Color(
                "self_nearest_rate:Q",
                title="Nearest seed is in-group",
                scale=alt.Scale(scheme="viridis"),
            ),
            size=alt.Size("seeds:Q", title="Seeds", scale=alt.Scale(range=[30, 120])),
            tooltip=[
                alt.Tooltip("variation:N", title="Variation"),
                alt.Tooltip("seeds:Q", title="Seeds"),
                alt.Tooltip(
                    "mean_pairwise_cosine:Q", title="Mean pairwise", format=".3f"
                ),
                alt.Tooltip(
                    "max_pairwise_cosine:Q", title="Closest pair", format=".3f"
                ),
                alt.Tooltip(
                    "self_nearest_rate:Q", title="In-group nearest", format=".2f"
                ),
            ],
        )
        .properties(title="Within-variation seed spread", width=760, height=540)
        .configure_axis(
            domainColor="#9ca3af",
            gridColor="#e5e7eb",
            labelColor="#374151",
            titleColor="#111827",
        )
        .configure_view(stroke="#d1d5db")
    )
    mo.vstack(
        [
            mo.md(
                "### Within-variation spread\n\n"
                "Each point is one subcategory. Up and to the right means its "
                "seeds repeat each other; bright colour means its seeds are also "
                "closer to each other than to anything else in the set. Points "
                "low and left got genuinely distinct scenarios from one tag."
            ),
            mo.ui.altair_chart(_chart),
        ]
    )
    return


@app.cell
def _(Path, alt, mo, np, pl, seed_records, taxonomy_rows):
    _lookup = category_lookup(taxonomy_rows)
    _variations = seed_records["variation"].to_list()
    _categories = [
        "(untagged)" if _variation == "(untagged)" else _lookup(_variation)
        for _variation in _variations
    ]

    _embeddings = np.asarray(
        embed_texts(
            seed_records["text"].to_list(),
            Path(__file__).with_name(".embed_cache.json"),
        ),
        dtype=float,
    )
    _embeddings /= np.linalg.norm(_embeddings, axis=1, keepdims=True)
    _pairwise = _embeddings @ _embeddings.T
    np.fill_diagonal(_pairwise, -np.inf)
    _nearest = _pairwise.argmax(axis=1)
    _coordinates = pca_coordinates(_embeddings)

    _members_by_category = {}
    for _index, _category in enumerate(_categories):
        _members_by_category.setdefault(_category, []).append(_index)

    _summary_rows = []
    for _category, _members in _members_by_category.items():
        _block = _pairwise[np.ix_(_members, _members)]
        _pairs = _block[np.triu_indices(len(_members), k=1)]
        _summary_rows.append(
            {
                "category": short_label(_category),
                "seeds": len(_members),
                "subcategories": len(
                    {_variations[_member] for _member in _members}
                ),
                "mean_pairwise_cosine": (
                    round(float(_pairs.mean()), 3) if len(_pairs) else None
                ),
                # Low rate means the category's seeds sit closer to other
                # categories than to their own — the domains are bleeding.
                "self_nearest_rate": round(
                    sum(_nearest[_member] in set(_members) for _member in _members)
                    / len(_members),
                    3,
                ),
            }
        )

    seed_category_summary = pl.DataFrame(_summary_rows).sort(
        "mean_pairwise_cosine", descending=True, nulls_last=True
    )
    seed_categories = pl.DataFrame(
        [
            {
                "seed": _seed,
                "category": short_label(_category),
                "variation": _variation,
                "nearest_category": short_label(_categories[_nearest[_index]]),
                "nearest_is_same_category": (
                    _categories[_nearest[_index]] == _category
                ),
                "pc1": float(_coordinates[_index, 0]),
                "pc2": float(_coordinates[_index, 1]),
            }
            for _index, (_seed, _category, _variation) in enumerate(
                zip(
                    seed_records["seed"].to_list(),
                    _categories,
                    _variations,
                    strict=True,
                )
            )
        ]
    )

    _order = seed_category_summary["category"].to_list()
    _map = (
        alt.Chart(seed_categories)
        .mark_circle(opacity=0.6, stroke="#ffffff", strokeWidth=0.3)
        .encode(
            x=alt.X("pc1:Q", title="PCA 1", scale=alt.Scale(zero=False)),
            y=alt.Y("pc2:Q", title="PCA 2", scale=alt.Scale(zero=False)),
            color=alt.Color(
                "category:N",
                title="Category",
                sort=_order,
                scale=alt.Scale(scheme="tableau20"),
                legend=alt.Legend(columns=1, orient="right", symbolLimit=20),
            ),
            tooltip=[
                alt.Tooltip("seed:N", title="Seed"),
                alt.Tooltip("category:N", title="Category"),
                alt.Tooltip("variation:N", title="Variation"),
                alt.Tooltip("nearest_category:N", title="Nearest seed's category"),
            ],
        )
        .properties(title="Seeds by category", width=760, height=560)
        .configure_axis(
            domainColor="#9ca3af",
            gridColor="#e5e7eb",
            labelColor="#374151",
            titleColor="#111827",
        )
        .configure_view(stroke="#d1d5db")
    )

    mo.vstack(
        [
            mo.md(
                "## Seeds by category\n\n"
                "The same seeds rolled up from their variation tag to the parent "
                "heading in `seed_subcategories.md`. Tight categories repeat "
                "themselves across subcategories; a low in-group nearest rate "
                "means the category's seeds resemble a neighbouring domain more "
                "than their own."
            ),
            mo.ui.table(seed_category_summary, pagination=False),
            mo.ui.altair_chart(_map),
        ]
    )
    return seed_categories, seed_category_summary


if __name__ == "__main__":
    app.run()
