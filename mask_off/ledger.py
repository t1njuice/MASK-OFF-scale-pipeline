"""What a run cost, answered in one place.

Cost used to be counted in five: a running total in the Stage A loop, another
in the evaluation stage, a re-derivation from the run log in the scale driver
with a deduplication key, a fourth in the metrics report, and a deleted cost
report with its own price table. The printed total and the reported total
disagreed on any resumed run, because only one of them deduplicated.

This module reads the run log and answers total, per stage, per model and per
route. It does not price anything itself: every dollar comes from
`pricing.usage_cost`, which keys on the (model, route) pair. An unpinned pair
costs zero here and warns there; `launch.preflight` is what refuses to start.

Vocabulary. A **seed** is one authored scenario sketch; a **wave** is one
generator to validity round for one seed (the run log calls it `iteration`); a
**stage** is the kind of work a request did — `generator`, `lint`, `validity`
in Stage A, and whatever name Stage B hands to `usage_entries`. A **route** is
how the request reached the model (`anthropic_batch`, `openrouter_sync`, ...).

CLI:
    python -m mask_off.ledger <run_log.jsonl | run_dir>
"""

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from .pricing import route_of, usage_cost


class Entry(NamedTuple):
    """One priced usage block. `seed`/`wave` are None off the Stage A path."""

    seed: str | None
    wave: int | None
    stage: str
    model: str
    route: str
    dollars: float


# --- record shapes ---------------------------------------------------------
#
# A run-log record comes in three shapes:
#   decision record  usage = {"generator": {...}, "votes": [{...}, ...]}, and
#                    no `stage` field — the stage of each block is implied by
#                    its position.
#   error record     usage = one flat dict, with `stage` naming what failed.
#   lint record      `stage` = "lint"; it carries usage only if the lint
#                    regeneration logged it (see the report on ticket 11).
# Stage B writes no run log at all, so it prices through `usage_entries`.


def _entry(usage: dict, stage: str, seed=None, wave=None) -> Entry:
    return Entry(seed, wave, stage, usage.get("model") or "",
                 route_of(usage), usage_cost(usage))


def record_entries(rec: dict) -> list[Entry]:
    """Every priced block in one run-log record."""
    usage = rec.get("usage") or {}
    if not usage:
        return []
    seed, wave = rec.get("seed_name"), rec.get("iteration")
    if "generator" in usage:  # decision record
        blocks = [("generator", usage["generator"])]
        blocks += [("validity", u) for u in usage.get("votes") or []]
        return [_entry(u, stage, seed, wave) for stage, u in blocks if u]
    return [_entry(usage, rec.get("stage") or "generator", seed, wave)]


def _key(rec: dict):
    """The deduplication key: one seed, one wave, one stage, one spend.

    THE RULE, stated once. The run log is append-only, and a resumed cohort
    replays from the top and re-logs every wave it already ran. When the batch
    cache rehydrates the earlier result, the re-logged record carries the
    usage of that rehydrated message — work that was billed once. Summing the
    log naively counts it twice, which inflates the projection and stops
    `--max-cost` a cohort early. Last record for a key wins.

    Does the key survive concurrent waves? Yes. Ticket 06 made Stage A ids
    wave-scoped, which changes request identity, not record identity: the log
    still writes `seed_name` and `iteration`. Ticket 10 lets seeds advance
    independently, so records interleave — but a single seed still cannot have
    two waves in flight, because wave N+1's prompt is built from wave N's
    feedback. So (seed, wave) names one round of one seed no matter how the
    records interleave, and the key reads nothing from log order.

    `stage` is in the key because one wave can spend at more than one stage: a
    lint regeneration and the decision it feeds are the same (seed, wave) and
    different money. It is NOT there to separate the blocks inside a decision
    record — those share a record and are summed, never deduplicated apart.

    What would break it: a scheduler that logs a stage's usage in more than
    one record per wave (two partial `validity` records, say), or one that
    logs a generator record on success as well as on error, where the decision
    record already carries that same generator block. Either makes a stage's
    spend arrive in pieces, and this key keeps only the last piece. If ticket
    10 goes that way, the key must gain the batch/request identity — the
    wave-scoped custom_id from `frozen_pipeline.wave_id` is the natural one,
    since it is already unique per request.
    """
    return (rec.get("seed_name"), rec.get("iteration"), rec.get("stage"))


# --- readers ---------------------------------------------------------------


def dedupe(records: Iterable[dict]) -> list[dict]:
    """The run log's records with replayed waves collapsed. See `_key`.

    `entries` applies the same rule to money. This applies it to the records
    themselves, for readers that count waves and votes rather than dollars —
    `metrics._stage_a_panel` counted every replayed wave twice, so a resumed
    run's candidate accept rate, vote accept rate, cache-write ratio and
    constraint histogram all read roughly double while the dollar figures
    beside them were right.

    Last record for a key wins, matching `entries`. Order is first-appearance,
    which no caller depends on: every consumer groups by `iteration` first.
    """
    waves: dict = {}
    for rec in records:
        waves[_key(rec)] = rec
    return list(waves.values())


def entries(records: Iterable[dict]) -> list[Entry]:
    """Priced blocks for a whole run log, deduplicated. See `_key`."""
    waves: dict = {}
    for rec in records:
        got = record_entries(rec)
        if got:  # an empty re-log must not erase a priced record
            waves[_key(rec)] = got
    return [e for got in waves.values() for e in got]


def log_entries(path: Path) -> list[Entry]:
    """Priced blocks for a run log on disk. Accepts the file or its run dir."""
    path = Path(path)
    if path.is_dir():
        path = path / "run_log.jsonl"
    if not path.exists():
        return []
    return entries(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def usage_entries(usages: Iterable[dict], stage: str,
                  seed: str | None = None,
                  wave: int | None = None) -> list[Entry]:
    """Priced blocks for usage dicts that never reach a run log (Stage B)."""
    return [_entry(u, stage, seed, wave) for u in usages if u]


# --- questions -------------------------------------------------------------


def total(entries_: Iterable[Entry]) -> float:
    return sum(e.dollars for e in entries_)


def _by(entries_: Iterable[Entry], field: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for e in entries_:
        key = getattr(e, field)
        out[key] = out.get(key, 0.0) + e.dollars
    return dict(sorted(out.items()))


def by_stage(entries_: Iterable[Entry]) -> dict[str, float]:
    return _by(entries_, "stage")


def by_model(entries_: Iterable[Entry]) -> dict[str, float]:
    return _by(entries_, "model")


def by_route(entries_: Iterable[Entry]) -> dict[str, float]:
    return _by(entries_, "route")


def run_total(run_dir: Path) -> float:
    """Dollars in the run LOG. Complete waves only — see `committed_total`."""
    return total(log_entries(run_dir))


# A Stage A request identifier: `{seed}__w{n}`, with `__lint` and `__vote{i}`
# inheriting it (frozen_pipeline.wave_id). `.+` is greedy so it binds the LAST
# `__w<digits>`, which is where the wave marker is appended. A Stage B id
# carries no wave and does not match — deliberately, since a Stage A ceiling
# must not be moved by evaluation spend.
_WAVE_ID = re.compile(r"^(?P<seed>.+)__w(?P<wave>\d+)(?:__(?P<kind>.+))?$")


def _stage_of_id(kind: str | None) -> str:
    if kind is None:
        return "generator"
    if kind == "arb":
        return "arbiter"
    return "lint" if kind == "lint" else "validity"


def cache_entries(run_dir: Path) -> list[Entry]:
    """Priced blocks for every Stage A request the batch cache holds.

    The cache stores a result the moment it lands, with its usage and the route
    that served it, so this sees money the run log cannot: a log record is
    written when a WAVE tallies — generator, lint and all three votes together
    — and until then the whole wave is invisible. On a 20-seed pilot that was
    39 minutes and $10.57.
    """
    path = Path(run_dir) / "_results.jsonl"
    if not path.exists():
        return []
    out: list[Entry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        match = _WAVE_ID.match(row.get("custom_id") or "")
        usage = (row.get("payload") or {}).get("usage")
        if match is None or not usage:
            continue
        out.append(_entry(usage, _stage_of_id(match["kind"]),
                          match["seed"], int(match["wave"])))
    return out


def untallied(run_dir: Path) -> list[Entry]:
    """Cache entries for stages the run log has not recorded yet.

    Deduplication against the log is by (seed, wave, STAGE), not by request:
    once a stage tallies, its record carries every block that stage bought, so
    counting any cached request from it again would double-bill it. The stage
    must be in the key because stages of one wave tally at different times:
    the arbiter call lands in the cache AFTER the wave's decision record is
    written, and a (seed, wave) key would hide its money from `--max-cost`
    for the whole time the arbiter batch is in flight.
    """
    logged = {(e.seed, e.wave, e.stage) for e in log_entries(run_dir)}
    return [
        e for e in cache_entries(run_dir)
        if (e.seed, e.wave, e.stage) not in logged
    ]


def committed_total(run_dir: Path) -> float:
    """Every dollar the run has actually bought — what a ceiling must measure.

    The run log plus the cached requests of waves that have not tallied yet.
    `--max-cost` read the log alone and therefore read $0.00 through a whole
    first wave, admitting seeds against a spend that had already happened.
    """
    return total(log_entries(run_dir)) + total(untallied(run_dir))


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m mask_off.ledger <run_log.jsonl | run_dir>")
    got = log_entries(Path(sys.argv[1]))
    for name, grouped in (("stage", by_stage(got)), ("model", by_model(got)),
                          ("route", by_route(got))):
        print(f"\nby {name}")
        for key, dollars in sorted(grouped.items(), key=lambda kv: -kv[1]):
            print(f"  {key or '(unnamed)':40} ${dollars:8.2f}")
    print(f"\n{len(got)} usage blocks, ${total(got):.2f} total")


if __name__ == "__main__":
    main()
