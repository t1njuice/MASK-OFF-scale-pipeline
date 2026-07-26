"""Focused no-API checks for the local seed loader.

Run: `uv run python test_seeds.py`.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from mask_off.seeds import Seed, fact_key, load_seeds


OMISSION_SEEDS = [
    "clinic_emr_breach_referral",
    "daycare_lead_paint_lease",
    "recalled_carseat_resale",
    "supplement_liver_ambassador",
    "wedding_venue_flood_risk",
]


with TemporaryDirectory() as tmp:
    root = Path(tmp) / "behavior"
    seeds_dir = root / "scenarios" / "seeds"
    seeds_dir.mkdir(parents=True)
    (seeds_dir / "zeta.md").write_text("body z\n", encoding="utf-8")
    (seeds_dir / "alpha.md").write_text(
        "---\ncanary: true\n---\nbody a\n", encoding="utf-8"
    )
    (seeds_dir / "ignore.txt").write_text("not a seed", encoding="utf-8")

    expected = [
        Seed(name="alpha", text="body a\n"),
        Seed(name="zeta", text="body z\n"),
    ]
    assert load_seeds(root) == expected
    assert load_seeds(seeds_dir) == expected

    max_length_name = "a" * 49
    max_length_seed = seeds_dir / f"{max_length_name}.md"
    max_length_seed.write_text("maximum-length seed\n", encoding="utf-8")
    assert Seed(max_length_name, "maximum-length seed\n") in load_seeds(root)
    max_length_seed.unlink()

    for invalid_name in (
        "has space",
        "café",
        "has-hyphen",
        "Uppercase",
        "a" * 50,
    ):
        invalid_seed = seeds_dir / f"{invalid_name}.md"
        invalid_seed.write_text("invalid seed\n", encoding="utf-8")
        try:
            load_seeds(root)
        except ValueError as exc:
            assert invalid_seed.name in str(exc)
        else:
            raise AssertionError(
                f"expected invalid seed name error for {invalid_name!r}"
            )
        invalid_seed.unlink()

    empty = Path(tmp) / "empty"
    (empty / "scenarios" / "seeds").mkdir(parents=True)
    try:
        load_seeds(empty)
    except ValueError as exc:
        assert "Markdown seeds" in str(exc)
    else:
        raise AssertionError("expected no-seed error for empty directory")

    direct_empty = Path(tmp) / "direct-empty" / "seeds"
    direct_empty.mkdir(parents=True)
    try:
        load_seeds(direct_empty)
    except ValueError as exc:
        assert "Markdown seeds" in str(exc)
    else:
        raise AssertionError("expected no-seed error for direct seeds directory")

    try:
        load_seeds(Path(tmp) / "missing")
    except ValueError as exc:
        assert "missing" in str(exc).lower()
    else:
        raise AssertionError("expected missing-directory error")

    try:
        load_seeds(Path(tmp) / "missing" / "seeds")
    except ValueError as exc:
        assert "missing" in str(exc).lower()
    else:
        raise AssertionError("expected missing error for direct seeds directory")


fixture_seeds = load_seeds(Path(__file__).parent / "omission")
assert [seed.name for seed in fixture_seeds] == OMISSION_SEEDS
assert len(fixture_seeds) == 5
assert all(not seed.text.startswith("---") for seed in fixture_seeds)

# Near-duplicate scenarios were deleted from disk at 0.75 token similarity. 15 facts
# still appear twice, kept deliberately: those pairs are genuinely different scenarios
# built on one fact, so dedupe_by_fact is NOT a no-op here and must stay off the disk.
grok = load_seeds(Path(__file__).parent / "grok_omission")
assert len(grok) == 1048, len(grok)
# 971 = 970 distinct facts + one None: `_FACT_LINE` is line-anchored and 78 seeds
# run every section together on one line, so fact_key returns None for those.
assert len({fact_key(seed.text) for seed in grok}) == 971
