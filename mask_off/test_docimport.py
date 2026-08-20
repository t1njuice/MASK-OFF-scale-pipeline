"""The pool-B document importer: parsers, sidecar gate, freeze."""

from . import docimport


def test_a_fence_line_toggles_the_scanner_off_and_on():
    lines = ["outside a", "```", "inside", "```", "outside b"]
    assert docimport.outside_fence_indices(lines) == {0, 4}


def test_a_heading_inside_a_fence_is_not_visible_to_the_scanner():
    lines = ["# real heading", "```", "# WELCOME TO THE SHED", "```"]
    outside = docimport.outside_fence_indices(lines)
    assert 0 in outside
    assert 2 not in outside


def test_fenced_block_returns_its_body_and_the_index_after_it():
    lines = ["## System prompt", "", "```", "line one", "line two", "```", "next"]
    body, after = docimport.fenced_block(lines, 0)
    assert body == "line one\nline two"
    assert lines[after] == "next"
