"""Build the pool-B corpus from the relevance-conversion and diverse-20 docs.

Both source documents interleave item text with model transcripts, and the
transcripts contain real markdown headings inside their fenced blocks. Every
scan here is fence-aware for that reason: a line-prefix match over the raw
file finds headings the models wrote, not items.

See docs/superpowers/specs/2026-08-20-pool-b-doc-import-design.md.
"""

import json
import re
import uuid
from pathlib import Path

_FENCE = "```"


def outside_fence_indices(lines: list[str]) -> set[int]:
    """Indices of the lines that sit outside every fenced block.

    Fence lines themselves are excluded: they delimit, they are not content.
    Both source documents use bare triple-backtick fences with no language
    tag, and both balance exactly, so a toggle is sufficient.
    """
    outside: set[int] = set()
    inside = False
    for i, line in enumerate(lines):
        if line.strip() == _FENCE:
            inside = not inside
            continue
        if not inside:
            outside.add(i)
    return outside


def fenced_block(lines: list[str], start: int) -> tuple[str, int]:
    """The body of the first fenced block at or after `start`, and the index
    of the line following its closing fence."""
    i = start
    while lines[i].strip() != _FENCE:
        i += 1
    body = []
    j = i + 1
    while lines[j].strip() != _FENCE:
        body.append(lines[j])
        j += 1
    return "\n".join(body), j + 1
