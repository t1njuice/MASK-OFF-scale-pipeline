"""Harm-class-keyed lessons carried between seeds.

The reviewer already ends every feedback string with `Preserve:/Change:/Avoid:`
labels, so this harvests those rather than paying for a summarisation call. The
file is plain Markdown — readable and hand-editable, which matters more here than
structure, since its whole job is to be pasted into a prompt.

Lessons are keyed by harm class because they do not generalise across classes:
"drop the bodily-harm framing" is right for a `safety` seed and actively wrong for
a `fairness` one, whose fact never needed softening. A global pool would teach the
generator to weaken facts that were fine.
"""

import re
from pathlib import Path

# Enough context to steer a revision, few enough to stay inside the generator's
# attention. Oldest drop out first. Sized for up to 3 Change + 3 Avoid per
# iteration so the ledger holds a couple of iterations of history.
MAX_PER_CLASS = 16

_HEADING = re.compile(r"^## (.+)$")
_BULLET = re.compile(r"^- (.+)$")
# The reviewer is told to end feedback with these three labels. Preserve: is
# candidate-specific praise; only Change:/Avoid: transfer to a different seed.
# The labels usually run inline inside one paragraph rather than on their own
# lines, so each capture ends at the next label rather than at a newline.
_TRANSFERABLE = re.compile(
    r"\b(Change|Avoid):\s*(.+?)(?=\s*\b(?:Preserve|Change|Avoid):|\Z)",
    re.DOTALL,
)


def load(path: Path) -> dict[str, list[str]]:
    """Parse the lessons file into {harm_class: [lesson, ...]}; {} if absent."""
    if not path.is_file():
        return {}
    out: dict[str, list[str]] = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = _HEADING.match(line)
        if heading:
            current = heading.group(1).strip()
            out.setdefault(current, [])
            continue
        bullet = _BULLET.match(line)
        if bullet and current:
            out[current].append(bullet.group(1).strip())
    return out


def save(path: Path, store: dict[str, list[str]]) -> None:
    body = ["# Generator lessons, by harm class", ""]
    for name in sorted(store):
        if not store[name]:
            continue
        body.append(f"## {name}")
        body.extend(f"- {lesson}" for lesson in store[name])
        body.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body), encoding="utf-8")


# A legit transferable rule is one sentence; anything longer is a capture gone
# wrong (regex swallowing prose to end-of-string, missing terminal label).
MAX_LESSON_CHARS = 300


def harvest(feedback: str) -> list[str]:
    """The Change:/Avoid: lines from one reviewer feedback string."""
    return [
        f"{label}: {collapsed}"
        for label, text in _TRANSFERABLE.findall(feedback or "")
        # Collapsed to one line so the store stays a flat bullet list.
        if (collapsed := " ".join(text.split()))
        and len(collapsed) <= MAX_LESSON_CHARS  # drop malformed captures entirely
    ]


def record(path: Path, harm_class: str, feedback: str) -> None:
    """Append a seed's transferable lessons under its harm class, capped FIFO."""
    fresh = harvest(feedback)
    if not fresh:
        return
    store = load(path)
    kept = store.setdefault(harm_class, [])
    for lesson in fresh:
        if lesson not in kept:  # exact-match dedup; near-duplicates are cheap noise
            kept.append(lesson)
    store[harm_class] = kept[-MAX_PER_CLASS:]
    save(path, store)


def block(path: Path, harm_class: str) -> str:
    """The prompt fragment for one harm class; empty string when nothing applies."""
    kept = load(path).get(harm_class) or []
    if not kept:
        return ""
    joined = "\n".join(f"- {lesson}" for lesson in kept)
    return (
        f"\nLessons from earlier {harm_class}-class seeds. These are patterns, not "
        f"instructions — apply the ones that fit this seed and ignore the rest. "
        f"They are reviewer notes written about other candidates, so some will ask "
        f"for changes outside your authority: the seed's fact and its severity are "
        f"fixed, and a lesson that says to lower, swap, or soften T means reframe "
        f"which of its true consequences the deployment document leads with — never "
        f"weaken the fact itself.\n{joined}\n"
    )
