"""Panel and Seat: one way to express a set of model positions on one artifact.

A **Seat** is one position in such a group — which model fills it, at what
reasoning effort, and under what output token cap. A **Panel** is an ordered
list of seats. See CONTEXT.md for the definitions.

The same concept used to be written three incompatible ways: the validity gate
was a list of model ids indexed by vote slot, the target roster a list of bare
ids with the effort and the cap held elsewhere, and the judge a single string.
Adding a judge was therefore a change to the request builder, the identifier
scheme, the un-blinding map and the summary all at once.

The **token cap belongs to the seat**, not to the stage. Output tokens are 87%
of a run's bill and a stage costs (seats x output cap), so one global ceiling
makes every seat as expensive as the seat that needs the most.

`expand` is the one way a panel becomes requests. Its identifiers are
`{custom_id}__{tag}{slot}`, which cannot collide within a call (slot is unique)
and cannot collide across calls as long as each call site uses its own tag —
the gate uses `vote`, the judge `j`, and a roster seat its own label. Ids are
budgeted: Anthropic caps a custom_id at 64 characters and a Stage A id already
spends 53 of them on a 49-character seed name plus its wave marker, so a tag
here is short on purpose (see the id-budget test in test_frozen_votes.py).

This module imports nothing from the package at module scope: `config` holds
the panel values, so it imports `Seat` from here and a top-level import of
`llm` (which imports `config`) would close the cycle.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Seat:
    """One position on a panel.

    `label` names the seat, not the lab: it is what identifiers, reports and
    un-blinding maps key on, so it must stay stable while a model id behind it
    can change. It never reaches a generator or a reviewer prompt — the
    validity gate deliberately shows its reviewers anonymous letters instead
    (see `validity._letter`).
    """

    label: str
    model: str
    effort: str
    max_tokens: int


def seats(panel: list[Seat], slots: int | None = None) -> list[tuple[int, Seat]]:
    """`(slot, seat)` for each slot, cycling the panel when slots exceed seats.

    `slots` defaults to one slot per seat, which is what the roster and the
    judge want. The validity gate passes `config.VALIDITY_VOTES` instead: the
    number of votes and the quorum that accepts them are configuration and
    must never be derived from how many seats the panel happens to hold.
    """
    count = len(panel) if slots is None else slots
    return [(slot, panel[slot % len(panel)]) for slot in range(count)]


def duplicate_labels(panel: list[Seat]) -> list[str]:
    """Labels used by more than one seat, sorted.

    A duplicate is silent and expensive. Two roster seats labelled `kimi` write
    their samples to the same `{rid}__kimi_{i}` ids, so the batch cache serves
    one seat's answer to both and the second model is never actually sampled —
    a measurement that reports two models and holds one. Preflight refuses on a
    non-empty result, which is why growing a roster stays a list edit.
    """
    seen, dupes = set(), set()
    for seat in panel:
        (dupes if seat.label in seen else seen).add(seat.label)
    return sorted(dupes)


def expand(
    panel: list[Seat],
    custom_id: str,
    tag: str,
    system: str,
    user: str | Callable[[int, "Seat"], str],
    thinking: dict | None = None,
    schema: dict | None = None,
    slots: int | None = None,
) -> list[dict]:
    """One request per slot, under `{custom_id}__{tag}{slot}`.

    Each request runs on its seat's model, effort and token cap, so a panel
    whose seats disagree about any of the three costs what it actually needs.

    `user` is the user message, or a callable `(slot, seat) -> str` when it
    differs per slot. The judge's does: each judge sees the responses under its
    own anonymous ordering, so that a position effect cannot line up across
    judges and an un-blinding that reached for the wrong judge's map produces
    visibly wrong attributions rather than plausible ones.
    """
    from .llm import message_params  # deferred: llm imports config imports us

    return [
        {
            "custom_id": f"{custom_id}__{tag}{slot}",
            "params": message_params(
                seat.model,
                seat.effort,
                system,
                user(slot, seat) if callable(user) else user,
                seat.max_tokens,
                thinking,
                schema=schema,
            ),
        }
        for slot, seat in seats(panel, slots)
    ]
