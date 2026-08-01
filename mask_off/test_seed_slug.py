"""Self-check: artifact names carry the seed set and stay under the filename limit.

Run: python -m mask_off.test_seed_slug
"""
from . import config
from .pipeline import run_artifact_paths, seeds_slug


def demo():
    # Order of the sample must not change the slug — it names a set.
    assert seeds_slug(["b", "a"]) == seeds_slug(["a", "b"]) == "a+b"

    pilot = ["casting_roll_exotherm_burns", "app_background_location_sold",
             "frozen_raspberry_hepatitis_lot", "site_guardrails_removed_level_four",
             "vault_metadata_plaintext_kdf"]
    assert seeds_slug(pilot).count("+") == 4, "a 5-seed pilot must stay readable"

    # A scale run collapses to a digest, and the same set digests the same.
    many = [f"seed_number_{i:03d}_with_a_longish_name" for i in range(50)]
    slug = seeds_slug(many)
    assert slug.startswith("50seeds-") and len(slug) == 16, slug
    assert slug == seeds_slug(list(reversed(many)))

    paths = run_artifact_paths("pilot", 5, stamp="2026-08-01_063001Z", seed_names=pilot)
    name = paths["summary"].name
    assert "_seeds-app_background_location_sold+" in name, name  # sorted, not sampled order
    longest = max(len(p.name) for p in paths.values() if p is not None)
    assert longest < 255, longest

    # A 50-seed scale run is the length worst case; suffixes are longer than .csv.
    scale = run_artifact_paths("scale", 50, stamp="2026-08-01_063001Z", seed_names=many)
    assert max(len(p.name) for p in scale.values() if p is not None) < 255

    # Omitting seed_names keeps the previous filename shape.
    assert "_seeds-" not in run_artifact_paths("pilot", 5, stamp="s")["summary"].name

    print("ok:", name)


if __name__ == "__main__":
    demo()
