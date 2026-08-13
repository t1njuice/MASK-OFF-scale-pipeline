"""The stop rule: from one seed's history, does it still deserve money?

Vocabulary is CONTEXT.md's. A **wave** is one generator -> validity round for
one seed; a **cohort** is a checkpoint and does not appear here. This module
sees one seed's waves and nothing else.

It is pure by construction — stdlib plus `config`, and nothing that opens a
connection. That is the point of the ticket: the rule can be fitted, replayed
and tested from a list of `Wave` records with no network at all. Do not import
the batch runner, the progress display, or anything that makes a request.

What Stage A writes per wave (`instrument`), so a rule can be fitted offline:
the constraints the panel failed, whether that failing set is shrinking, and
the inference-distance direction ruling the wave carried in and ruled out.
The seed's final log record additionally carries `"stopped": <reason>`, so a
later analysis separates accepted / stopped-early / cap-exhausted without
inferring it. (`"stopped"`, not `"stop_reason"`: the generator-error record
already uses `stop_reason` for the provider's own field.)

**The iteration cap is the only ACTIVE rule.** The direction-lock fix for
inference-distance oscillation landed 2026-08-13 and is unvalidated; it targets
exactly the failure mode that produced the cap-burners, so every cap number
measured before it is stale. A second rule plugs into `decide(..., rules=...)`
and becomes active by joining `active_rules()` — after a pilot measures it, not
before.

Replay a run log through the records:

    python -m mask_off.stoprule docs/evidence/p6_gate_pilot_run_log.jsonl
"""

import datetime
import json
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import config

# Why a seed left Stage A.
ACCEPTED = "accepted"
SEED_DEFECT = "seed_defect"
CAP_EXHAUSTED = "cap_exhausted"
# A legacy log can show a seed that stopped without accepting and without
# reaching its run's cap. Something ended it early and the log does not say
# what. Naming that is honest; guessing "cap_exhausted" is not.
STOPPED_UNRECORDED = "stopped_unrecorded"

# The two failing directions of the inference_distance constraint, as the
# reviewer prompt prefixes its note. `validity.id_direction` rules between them.
ID_DIRECTIONS = ("too traceable", "speculative")


@dataclass(frozen=True)
class Wave:
    """One generator -> validity round of one seed, as the stop rule sees it.

    `failed` are the constraint names failed by at least one seat, in schema
    order. `id_dir` is the direction ruling this wave's votes produced;
    `id_dir_in` is the ruling carried in from the wave before, which is the one
    the direction lock applied to.

    The last three are record metadata that `decide` never reads: `stopped` is
    a reason a run already recorded, and `ts`/`entered` are when the wave
    finished and when its seed entered flight, which `flight` measures
    occupancy across.
    """

    iteration: int
    accepted: bool = False
    seed_defect: bool = False
    failed: tuple[str, ...] = ()
    id_dir: str | None = None
    id_dir_in: str | None = None
    stage: str = "decision"
    stopped: str | None = None
    ts: str | None = None
    entered: str | None = None


@dataclass(frozen=True)
class Verdict:
    stop: bool
    reason: str | None = None


CONTINUE = Verdict(False, None)


@dataclass(frozen=True)
class IterationCap:
    """Stop once the seed has burned `cap` waves. The only active rule.

    Reads the wave number rather than the length of the history, because a
    salvage resume rebuilds `iteration` from a prior run log without rebuilding
    the waves that came before it.
    """

    cap: int

    def __call__(self, waves: Sequence[Wave]) -> Verdict:
        if waves and waves[-1].iteration >= self.cap:
            return Verdict(True, CAP_EXHAUSTED)
        return CONTINUE


def active_rules() -> tuple:
    """Every rule Stage A currently enforces. Exactly one, deliberately."""
    return (IterationCap(config.FROZEN_MAX_ITERATIONS),)


def decide(waves: Sequence[Wave], rules: Sequence | None = None) -> Verdict:
    """Does this seed get another wave, and if not, why not.

    The two terminal outcomes of a wave come first — a seed that accepted
    stopped by accepting even on its last permitted wave, and a seed the panel
    called defective stopped on the defect, not on the cap. Then each rule in
    turn; the first that fires names the reason.
    """
    if not waves:
        return CONTINUE
    last = waves[-1]
    if last.accepted:
        return Verdict(True, ACCEPTED)
    if last.seed_defect:
        return Verdict(True, SEED_DEFECT)
    for rule in (active_rules() if rules is None else rules):
        verdict = rule(waves)
        if verdict.stop:
            return verdict
    return CONTINUE


def shrinking(waves: Sequence[Wave]) -> bool | None:
    """Is the failing set smaller than it was one wave ago? None on wave 1."""
    if len(waves) < 2:
        return None
    return len(waves[-1].failed) < len(waves[-2].failed)


def instrument(waves: Sequence[Wave]) -> dict:
    """The per-wave block Stage A writes to the run log for the latest wave."""
    last = waves[-1]
    return {
        "failed_constraints": list(last.failed),
        "n_failed": len(last.failed),
        "shrinking": shrinking(waves),
        "id_dir": last.id_dir,
        "id_dir_in": last.id_dir_in,
    }


# --- reading votes, live or replayed --------------------------------------
# Both take the vote dumps a decision record already carries, so the live path
# and the replay path name the failing set the same way.

def failed_union(votes: Iterable[Mapping]) -> tuple[str, ...]:
    """Constraint names failed by at least one seat, in schema field order."""
    order: dict[str, None] = {}
    failed = set()
    for vote in votes:
        checks = vote.get("constraints") or {}
        order.update(dict.fromkeys(checks))
        failed |= {n for n, c in checks.items() if not c.get("passed", True)}
    return tuple(n for n in order if n in failed)


def majority_direction(notes: Iterable[str]) -> str | None:
    """The direction a set of failing inference_distance notes rules for.

    None on a tie or when nothing failed. `validity.id_direction` calls this
    with live votes; `direction_of` calls it with replayed dumps.
    """
    counts = dict.fromkeys(ID_DIRECTIONS, 0)
    for note in notes:
        text = (note or "").strip().lower()
        for direction in ID_DIRECTIONS:
            if text.startswith(direction):
                counts[direction] += 1
    if counts["too traceable"] == counts["speculative"]:
        return None
    return max(counts, key=counts.get)


def direction_of(votes: Iterable[Mapping]) -> str | None:
    """`majority_direction` over the vote dumps in a logged wave."""
    checks = [(v.get("constraints") or {}).get("inference_distance") or {} for v in votes]
    return majority_direction(c.get("note", "") for c in checks if not c.get("passed", True))


# --- offline replay -------------------------------------------------------

def waves_from_log(rows: Iterable[Mapping]) -> dict[str, list[Wave]]:
    """One seed's waves per seed name, from run-log records.

    A lint record is not a wave: it shares its wave with the decision record of
    the same seed and iteration. Records written before this instrumentation
    landed carry no `stop_rule` block, so the failing set and the direction
    ruling are re-derived from the vote dumps the record already holds.
    """
    histories: dict[str, list[Wave]] = {}
    carried: dict[str, str | None] = {}
    for row in rows:
        if row.get("stage") == "lint" or "seed_name" not in row:
            continue
        seed = row["seed_name"]
        block = row.get("stop_rule") or {}
        votes = row.get("votes") or []
        is_decision = "accepted" in row
        wave = Wave(
            iteration=row.get("iteration", len(histories.get(seed, ())) + 1),
            accepted=bool(row.get("accepted")),
            seed_defect=bool(row.get("seed_defect")),
            failed=tuple(block["failed_constraints"]) if "failed_constraints" in block
            else failed_union(votes),
            id_dir=block["id_dir"] if "id_dir" in block else direction_of(votes),
            id_dir_in=block.get("id_dir_in", carried.get(seed)),
            stage=row.get("stage", "decision" if is_decision else "unknown"),
            stopped=row.get("stopped"),
            ts=row.get("ts"),
            entered=row.get("entered"),
        )
        histories.setdefault(seed, []).append(wave)
        if is_decision:
            carried[seed] = wave.id_dir
    for history in histories.values():
        history.sort(key=lambda w: w.iteration)
    return histories


def historical_cap(histories: Mapping[str, list[Wave]]) -> int:
    """The cap the run that wrote this log was configured with, as evidenced by
    the log: the deepest wave any seed reached.

    A run stops a seed at its cap, so no seed can exceed it and at least one
    cap-burner reaches it. This is a lower bound — a run where every seed
    accepted early never demonstrates its cap — but it is the only cap the log
    itself attests to, and it does not move when today's setting moves.
    """
    return max((w.iteration for h in histories.values() for w in h), default=0)


def _reason(history: list[Wave], cap: int,
            infer: bool = True) -> tuple[str | None, bool]:
    """(reason, inferred). Prefer the reason the run recorded; else infer it
    from the log, against the cap THAT log ran at.

    Inference must never consult `config.FROZEN_MAX_ITERATIONS`. A log records
    what a past run did; re-reading it under today's setting restates history.
    Raise the live cap above a finished run's cap and every cap-burner in it
    would be reported as still running. `cap_ladder` is where the
    counterfactual lives, and it takes its caps as an argument.
    """
    if not history:
        return None, True
    last = history[-1]
    if last.stopped:
        return last.stopped, False
    if last.accepted:
        return ACCEPTED, True
    if last.seed_defect:
        return SEED_DEFECT, True
    # Everything above reads a field the wave RECORDED. Everything below reads
    # the cap, and on a live log the deepest wave reached is not the cap — it
    # is how far the run has got. So a live caller stops here: this seed has
    # not accepted, is not defective, and is still revising.
    if not infer:
        return None, False
    if last.iteration >= cap:
        return CAP_EXHAUSTED, True
    # It did not accept, was not defective, and never reached the cap this log
    # attests to. Something ended the run early — an interrupt, a cost ceiling,
    # a rule that run had and this one does not. Do not guess which.
    return STOPPED_UNRECORDED, True


def replay(rows: Iterable[Mapping], live: Iterable[str] = (),
           infer: bool = True) -> dict:
    """Per-wave figures for a whole run log, replayed through the stop rule.

    `live` names the seeds still in flight and `infer` says whether the log is
    finished. Both exist because inference reads the cap the log attests to —
    the deepest wave any seed reached — and on a RUNNING log that is not the
    cap, it is only how far the run has got. Every seed of a 20-seed run part
    way through wave 1 therefore looked `cap_exhausted` against an inferred cap
    of 1, which is the opposite of the truth: they were all about to revise.

    A finished log is the default and infers as it always did. A caller that
    knows the run is alive passes `infer=False`, and then only a reason the run
    RECORDED is reported; everything else is `running`, which is what it is.
    `live` additionally protects a seed that is in flight in a log that looks
    finished. Neither ever consults `config.FROZEN_MAX_ITERATIONS`.
    """
    rows = list(rows)
    live = frozenset(live)
    histories = waves_from_log(rows)
    cap = historical_cap(histories)
    per_seed = []
    for name, history in sorted(histories.items()):
        if name in live:
            reason, inferred = None, False
        else:
            reason, inferred = _reason(history, cap, infer=infer)
        accepted = any(w.accepted for w in history)
        per_seed.append({
            "seed_name": name,
            "waves": len(history),
            "accepted": accepted,
            "reason": reason,
            "inferred": inferred,
        })
    accepting = [w.iteration for h in histories.values() for w in h if w.accepted]
    reasons: dict[str, int] = {}
    for row in per_seed:
        key = row["reason"] or "running"
        reasons[key] = reasons.get(key, 0) + 1
    never = [row for row in per_seed if not row["accepted"]]
    return {
        "records": len(rows),
        "waves": sum(len(h) for h in histories.values()),
        "seeds": len(histories),
        "accepted": sum(1 for row in per_seed if row["accepted"]),
        "never_accepted": len(never),
        "waves_on_never_accepted": sum(row["waves"] for row in never),
        "latest_accepting_wave": max(accepting, default=None),
        "stop_reasons": reasons,
        "inferred_reasons": sum(1 for row in per_seed if row["inferred"]),
        "occupancy": flight(histories),
        "per_seed": per_seed,
    }


def accepting_wave(history: Sequence[Wave]) -> int | None:
    """The wave this seed accepted on, or None if it never did."""
    return next((w.iteration for w in history if w.accepted), None)


def cap_ladder(
    histories: Mapping[str, list[Wave]],
    caps: Iterable[int],
    cost_of: Callable[[str, "Wave"], float] | None = None,
) -> list[dict]:
    """What each candidate cap would have cost this run, and what it would
    have lost. The counterfactual the next pilot fits its cap from.

    A seed that accepted on wave k keeps its item at any cap >= k and loses it
    below; a seed that never accepted simply stops earlier.
    `cost_of(seed_name, wave)` is optional and injected — pricing lives outside
    this module so the rule stays free of the price table.
    """
    rows = []
    for cap in caps:
        waves, dollars, lost = 0, 0.0, 0
        for name, history in histories.items():
            accepted_at = accepting_wave(history)
            kept = min(accepted_at or len(history), cap)
            waves += kept
            if cost_of is not None:
                dollars += sum(cost_of(name, w) for w in history[:kept])
            if accepted_at and accepted_at > cap:
                lost += 1
        rows.append({"cap": cap, "waves": waves, "lost_items": lost, "dollars": dollars})
    return rows


def _hours(start: str, end: str) -> float:
    fmt = datetime.datetime.fromisoformat
    return (fmt(end) - fmt(start)).total_seconds() / 3600


def flight(histories: Mapping[str, list[Wave]]) -> dict:
    """When each seed entered and left flight, and the occupancy that implies.

    Occupancy is the fraction of the run's slot time that actually bought a
    wave. Under a cohort barrier a seed that accepts early leaves its slot idle
    until the cohort's slowest seed finishes, and that idle share is the tail
    ticket 12 removes — so this must be computable in both regimes, from any
    run log, without a cohort boundary to measure between.

    Two readings, because both are asked for:
      `wave_occupancy` — seed-waves bought over slots x rounds held open.
      `time_occupancy` — seed hours in flight over slots x run wall clock.

    A seed enters flight when its first wave is dispatched. Logs written before
    the `entered` stamp existed only date a wave when it FINISHES, so their
    enter time is read from the first record and is one wave late; that makes
    `time_occupancy` a lower bound on those logs, and exact on new ones.
    """
    seeds = {}
    for name, history in sorted(histories.items()):
        entered = history[0].entered or history[0].ts
        seeds[name] = {
            "seed_name": name,
            "entered": entered,
            "left": history[-1].ts,
            "waves": len(history),
            "exact_entry": history[0].entered is not None,
        }
    rounds = max((w.iteration for h in histories.values() for w in h), default=0)
    slots = len(histories)
    stamps = [s for row in seeds.values() for s in (row["entered"], row["left"]) if s]
    seed_waves = sum(row["waves"] for row in seeds.values())
    out = {
        "seeds": list(seeds.values()),
        "seed_waves": seed_waves,
        "slot_waves": slots * rounds,
        "wave_occupancy": seed_waves / (slots * rounds) if slots and rounds else None,
        "time_occupancy": None,
        "hours": None,
    }
    if len(stamps) >= 2 and all(row["entered"] and row["left"] for row in seeds.values()):
        hours = _hours(min(stamps), max(stamps))
        in_flight = sum(_hours(row["entered"], row["left"]) for row in seeds.values())
        out["hours"] = hours
        out["time_occupancy"] = in_flight / (slots * hours) if hours else None
    return out


DEFAULT_LOG = Path(__file__).resolve().parent.parent / "docs/evidence/p6_gate_pilot_run_log.jsonl"


def _pct(fraction: float | None) -> str:
    return "n/a" if fraction is None else f"{fraction:.0%}"


def main(argv: Sequence[str] | None = None) -> None:
    # The price table is an import of the CLI, not of the rule: `replay`,
    # `decide` and `cap_ladder` stay answerable with nothing but records.
    from .pricing import usage_cost

    path = Path((argv or sys.argv[1:] or [str(DEFAULT_LOG)])[0])
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = replay(rows)
    print(path)
    for name, value in report.items():
        if name not in ("per_seed", "occupancy"):
            print(f"{name:26} {value}")
    def cost_of(seed_name: str, wave: Wave) -> float:
        """Every seat of one wave: the generator, plus each panel vote."""
        usage = seats.get((seed_name, wave.iteration)) or {}
        blocks = [usage["generator"], *(usage.get("votes") or [])] if "generator" in usage else [usage]
        return sum(usage_cost(b) for b in blocks if b)

    seats = {
        (r["seed_name"], r["iteration"]): r.get("usage") or {}
        for r in rows if r.get("stage") != "lint" and "seed_name" in r
    }
    occupancy = report["occupancy"]
    print(f"{'seed-waves bought':26} {occupancy['seed_waves']} of "
          f"{occupancy['slot_waves']} slot-waves held open "
          f"({_pct(occupancy['wave_occupancy'])})")
    if occupancy["time_occupancy"] is not None:
        exact = all(s["exact_entry"] for s in occupancy["seeds"])
        print(f"{'seed hours in flight':26} {_pct(occupancy['time_occupancy'])} of "
              f"{occupancy['hours']:.2f} h x {len(occupancy['seeds'])} slots"
              + ("" if exact else "  (lower bound: entry read from the first record)"))

    histories = waves_from_log(rows)
    longest = max(len(h) for h in histories.values())
    # Priced before the header: pricing warns on stderr about legacy rows, and
    # a warning landing mid-table makes the table unreadable.
    ladder = cap_ladder(histories, range(2, longest + 1), cost_of)
    print(f"\n{'cap':>4} {'waves':>6} {'dollars':>9} {'items lost':>11}")
    for row in ladder:
        active = " <- config.FROZEN_MAX_ITERATIONS" if row["cap"] == config.FROZEN_MAX_ITERATIONS else ""
        print(f"{row['cap']:>4} {row['waves']:>6} {row['dollars']:>9.2f} "
              f"{row['lost_items']:>11}{active}")

    print(f"\n{'seed':52} {'waves':>5}  reason")
    for row in sorted(report["per_seed"], key=lambda r: (-r["waves"], r["seed_name"])):
        mark = "" if not row["inferred"] else " (inferred)"
        print(f"{row['seed_name'][:52]:52} {row['waves']:>5}  {row['reason']}{mark}")


if __name__ == "__main__":
    main()
