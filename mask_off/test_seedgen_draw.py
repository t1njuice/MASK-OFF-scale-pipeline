"""The `author --rows` draw and the pinned `domain:` line.

Split from test_taxonomy.py because these exercise `mask_off/seedgen.py`,
which carries uncommitted authoring work of the user's alongside this. The
taxonomy and `seeds.harm_class` halves stand on their own and ship first.
"""

from . import taxonomy


def test_the_row_draw_skips_what_is_already_on_disk(tmp_path):
    """`authored_rows` reads the seeds, not `author_log.jsonl`, because the log
    records rows that FAILED as well as rows that produced seeds — and a failed
    row has to be offered again rather than skipped forever."""
    from . import seedgen

    out = tmp_path / "corpus"
    seeds_dir = out / "scenarios" / "seeds"
    seeds_dir.mkdir(parents=True)
    row = taxonomy.rows()[0][1]
    (seeds_dir / "s.md").write_text(
        f"---\nsubcategory: {row}\n---\n\nWORLD: x.\n", encoding="utf-8"
    )
    assert seedgen.authored_rows(out) == {row}
    assert all(r != row for _, r in seedgen.draw_rows(40, out))


def test_a_failed_row_is_offered_again(tmp_path):
    """A row logged with an error wrote no seed, so the draw must still offer
    it — otherwise a transient provider failure silently costs a whole row."""
    from . import seedgen

    out = tmp_path / "corpus"
    out.mkdir(parents=True)
    row = taxonomy.rows()[0][1]
    (out / "author_log.jsonl").write_text(
        f'{{"row": "{row}", "error": "boom"}}\n', encoding="utf-8"
    )
    assert seedgen.authored_rows(out) == set()
    assert any(r == row for _, r in seedgen.draw_rows(560, out))


def test_author_pins_the_domain_into_the_frontmatter():
    """The pinned `domain:` is what makes the seed stratifiable at all. Pinned
    by us, never trusted from the model, exactly like the canary and the
    subcategory."""
    from . import seedgen

    body = "---\n# canary GUID x\nsubcategory: wrong\nfamily: regulator review\n---\n\nWORLD: x.\n"
    out = seedgen._pin(body, "coastal wetland fill and mitigation", "Environment")
    assert "subcategory: coastal wetland fill and mitigation" in out
    assert "domain: Environment" in out
    assert out.count("domain:") == 1


def test_author_recovers_the_domain_when_the_draw_did_not_name_one():
    """`--row` without `--domain` passes an empty domain; the row still knows
    which domain it belongs to."""
    from . import seedgen

    body = "---\nsubcategory: wrong\n---\n\nWORLD: x.\n"
    out = seedgen._pin(body, "coastal wetland fill and mitigation")
    assert "domain: Environment" in out


def test_pinning_twice_does_not_stack_domain_lines():
    """`--regen` re-pins a seed that already carries a domain."""
    from . import seedgen

    body = "---\nsubcategory: a\ndomain: Environment\n---\n\nWORLD: x.\n"
    once = seedgen._pin(body, "coastal wetland fill and mitigation", "Environment")
    twice = seedgen._pin(once, "coastal wetland fill and mitigation", "Environment")
    assert twice.count("domain:") == 1
