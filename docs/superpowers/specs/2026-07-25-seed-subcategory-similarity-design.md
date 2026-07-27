# Seed and taxonomy similarity explorers

**Status:** Approved design · **Date:** 2026-07-25

## Goal

Extend `seed_diversity.py` with two related semantic views:

1. show how similar seed examples are within each of the 14 top-level harm
   categories, with each point representing a seed file;
2. show how similar the 40 taxonomy subcategories are within any selected
   top-level category, with each point representing one subcategory.

Both views must be interactive: selecting a point reveals its name and nearest
neighbours. The existing lexical and folder-level seed analysis remains.

## Data model

The supplied taxonomy contains exactly:

- 14 top-level categories;
- 40 subcategories per category;
- 560 subcategories in total.

Store it as a Markdown data file with `# Category` headings and `- subcategory`
items. A small stdlib parser returns:

```python
dict[str, list[str]]
```

The parser validates the expected 14 categories, 40 unique entries per
category, and 560 entries total. This catches accidental truncation or
duplicate labels without adding a schema or dependency.

## Embedding inputs

Reuse the existing `embed_texts` cache and
`text-embedding-3-small`. No second embedding implementation is introduced.

Embed:

- each seed's parsed setting/role text;
- each complete top-level category label, including its parenthetical guidance;
- each subcategory as `"{top-level category}: {subcategory}"`.

Including the parent category in subcategory text prevents short labels such as
“status exam practical evaluation” from being embedded without context.

## Seed category explorer

Assign every seed to the top-level category whose embedding has the greatest
cosine similarity to the seed embedding. Existing `variation:` frontmatter is
kept as validation metadata:

- predicted category;
- existing tag;
- whether they agree, when the existing tag is one of the 14 categories;
- similarity to the chosen category;
- margin over the second-best category.

Several existing folders use `variation:` for pressure or harm type instead of
domain. Those tags remain visible but their agreement is reported as “not
comparable,” not as a false disagreement.

The explorer uses one small-multiple plot per occupied category. Within a plot,
each point is a seed and the 2D coordinates are a local PCA projection of that
category's seed embeddings. A selected point exposes:

- filename;
- setting/role text;
- predicted category;
- existing tag and agreement, when present;
- closest seed in the same category;
- cosine similarity to that seed;
- category score and runner-up margin.

Only occupied categories are rendered. Categories with one seed show one point
and “no within-category pair score.”

Classification is descriptive, not authoritative. A low score margin is shown
to the reader rather than hidden behind an arbitrary confidence threshold.

## Subcategory similarity explorer

Add one reusable marimo section, not 14 duplicated cells.

The section contains a top-level category dropdown. For the selected category:

1. select its 40 contextualized subcategory embeddings;
2. compute the 40×40 cosine-similarity matrix;
3. produce a local 2D PCA projection;
4. render one point per subcategory;
5. expose the selected subcategory and its three nearest neighbours through
   `mo.ui.altair_chart(...).value`.

The exact similarity values, not visual distance in the PCA projection, are
the evidence. The chart labels its axes as projection dimensions and states
that orientation and distance are approximate.

The accompanying summary reports:

- mean pairwise cosine similarity;
- median pairwise cosine similarity;
- 90th-percentile pairwise cosine similarity;
- mean cosine distance, `1 - mean similarity`.

Nearest-neighbour links may be drawn for orientation, but the numeric ranked
list remains the source of truth.

## Relationship to Shaib et al. (2024)

The existing gzip compression ratio remains a paper-aligned lexical diversity
measure for collections of parsed seed setting/role texts. It is not applied
to the short taxonomy labels: compressing 40 short labels would mostly measure
label length and shared category wording.

[Shaib et al. (2024)](https://arxiv.org/html/2403.00553v1) describe average
pairwise similarity as a core family of diversity measures. Cosine similarity
over embeddings is appropriate here because the question is semantic overlap
between labels and seeds. It is reported plainly as semantic
similarity/distance rather than presented as one of the paper's named lexical
scores.

## Interaction

Use existing dependencies only:

- `mo.ui.dropdown` selects the top-level category;
- `mo.ui.altair_chart` makes points selectable;
- the chart's reactive `.value` supplies the selected row to a detail table;
- Altair tooltips provide the same names when selection is not needed.

This follows the current marimo and Altair selection APIs and avoids custom
JavaScript.

## Files

| File | Change |
|---|---|
| `seed_diversity.py` | Add category assignment, category small multiples, and the subcategory explorer |
| `seed_subcategories.md` | Add the supplied 14×40 taxonomy |
| `test_seed_diversity.py` | Add taxonomy parser, assignment, and nearest-neighbour checks |
| `.gitignore` | Ignore `.superpowers/` visual-design scratch files if not already ignored |

The current missing `pair_type` helper in `seed_diversity.py` is repaired in
the same implementation because the existing notebook and test already call
it.

## Verification

The smallest deterministic check remains:

```bash
uv run python test_seed_diversity.py
uv run python -m compileall seed_diversity.py mask_off
```

The test covers:

- taxonomy parses to 14 categories and 560 unique subcategories;
- every category has exactly 40 subcategories;
- contextualized embedding labels are constructed deterministically;
- category assignment selects the maximum cosine score and reports the correct
  runner-up margin;
- nearest-neighbour ranking excludes the selected point itself;
- `pair_type` handles tagged, untagged, and partially tagged pairs.

The live marimo verification opens one seed folder, switches between at least
two top-level categories, selects a seed, then selects a subcategory and checks
that the corresponding detail rows update.

## Deliberate limits

- No UMAP, HDBSCAN, scipy, or sklearn.
- No global projection combining all 560 subcategories.
- No forced subcategory assignment for seed files.
- No threshold configuration until observed score margins show that one is
  needed.
- No claim that 2D PCA distance equals cosine similarity.
