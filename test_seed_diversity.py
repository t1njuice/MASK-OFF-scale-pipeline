"""Focused no-API checks for the seed diversity notebook.

Run: `uv run python test_seed_diversity.py`.
"""

import hashlib
from pathlib import Path

import numpy as np

from mask_off.seeds import setting_key, variation_tag
from seed_diversity import (
    category_assignments,
    compression_ratio,
    cosine_matrix,
    nearest_neighbours,
    pair_type,
    parse_taxonomy,
    pca_coordinates,
    tag_agreement,
    taxonomy_embedding_rows,
)


for text, expected in (
    (
        "SETTING/ROLE: Target is a booking assistant.\n"
        "MATERIAL FACT: Hidden fact.\n",
        "Target is a booking assistant.",
    ),
    (
        "Setting and role: Target is a customer-care assistant.\n"
        "The user is a registered customer.\n"
        "Exactly one ground-truth fact: Hidden fact.\n",
        "Target is a customer-care assistant.\n"
        "The user is a registered customer.",
    ),
    (
        "Setting: Target is a sales assistant.\n"
        "Ground-truth fact: Hidden fact.\n",
        "Target is a sales assistant.",
    ),
):
    assert setting_key(text) == expected

assert setting_key("No marked setting here.") is None

assert (
    variation_tag("---\ncanary: true\nvariation: Medical / healthcare\n---\nbody\n")
    == "Medical / healthcare"
)
assert variation_tag("---\ncanary: true\n---\nvariation: too late\n") is None
assert variation_tag("variation: no frontmatter\n") is None


root = Path(__file__).parent
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
        "Consumer / product safety: children's products & nursery gear"
    ),
}

duplicate_taxonomy = taxonomy_text.replace(
    "- battery-powered devices and lithium cells",
    "- children's products & nursery gear",
    1,
)
try:
    parse_taxonomy(duplicate_taxonomy)
except ValueError as error:
    assert str(error) == "Taxonomy subcategories must be unique."
else:
    raise AssertionError("Duplicate taxonomy label was accepted.")


for folder in (
    "omission",
    "model_omission1",
    "model_omission_gpt5_6",
    "grok_omission",
):
    paths = sorted((root / folder / "scenarios" / "seeds").glob("*.md"))
    assert paths, folder
    unparsed = [
        path.name
        for path in paths
        if setting_key(path.read_text(encoding="utf-8")) is None
    ]
    assert not unparsed, f"{folder}: {unparsed}"


similarities = cosine_matrix([[3.0, 0.0], [0.0, 4.0], [3.0, 4.0]])
assert np.allclose(np.diag(similarities), 1.0)
assert np.allclose(similarities, similarities.T)
assert np.isclose(similarities[0, 1], 0.0)
assert np.isclose(similarities[0, 2], 0.6)


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


categories = ["Medical / healthcare", "Finance / fiduciary harm"]
assert tag_agreement(None, "Medical / healthcare", categories) == "missing"
assert (
    tag_agreement(
        "indirect_harm_to_other_humans",
        "Medical / healthcare",
        categories,
    )
    == "not comparable"
)
assert (
    tag_agreement(
        "Medical / healthcare",
        "Medical / healthcare",
        categories,
    )
    == "agree"
)
assert (
    tag_agreement(
        "Finance / fiduciary harm",
        "Medical / healthcare",
        categories,
    )
    == "disagree"
)


repeated = ["same institution and assistant role"] * 100
varied = [hashlib.sha256(str(index).encode()).hexdigest() for index in range(100)]
assert compression_ratio(repeated) > compression_ratio(varied)


assert pair_type(None, None, has_tags=False) == "All pairs"
assert pair_type("medical", "medical", has_tags=True) == "Same variation"
assert pair_type("medical", "finance", has_tags=True) == "Different variation"
assert pair_type("medical", None, has_tags=True) == "Missing variation"
