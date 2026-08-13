"""Continuous refill: seeds in flight, checkpoints, quota, ceiling, resume.

Ticket 12. A cohort used to be a scheduling barrier — cohort N+1's first seed
could not start until cohort N's last straggler finished. It is now what
CONTEXT.md always said it was: a checkpoint. Stage A holds a target number of
seeds in flight and replaces each one as it finishes.

Four things have to survive that, and each has a test here:

  the stratified draw    a stream of one-slot refills must spread across
                         domains exactly as one large draw does, or a domain
                         whose gate is harsh eats every slot and the domains
                         after it are never attempted at all
  the resume contract    restated over the set of in-flight seeds rather than
                         over a cohort: an interrupted run relaunches exactly
                         what was in flight, and every completed request
                         replays from the batch cache
  the cost ceiling       read only where stopping strands nothing — it closes
                         admission, and never takes a slot away from a seed
  the checkpoint         state written, metrics recorded, run yield updated,
                         and nothing waiting on any of it

Run: pytest mask_off/test_refill.py
"""

import dataclasses
import json
import random
from collections import Counter
from pathlib import Path

import pytest

from . import batchcache, config, routes, scale
from .conftest import message
from .frozen_pipeline import SeedState
from .seeds import Seed, harm_class

DOMAINS = ("care", "privacy", "safety")  # alphabetical, and that matters below


def _seed(name: str, domain: str = "safety") -> Seed:
    text = f"MATERIAL FACT: fact for {name} [{domain}]\nSETTING/ROLE: office"
    return Seed(name=name, text=text, source="test")


def _corpus(per_domain: int = 20) -> list[Seed]:
    return [
        _seed(f"{d}_{i:02d}", d) for d in DOMAINS for i in range(per_domain)
    ]


def _domain_of(seeds, name: str) -> str:
    return harm_class(next(s for s in seeds if s.name == name).text)


# --- a Stage A that finishes seeds on demand -------------------------------


class FakeStageA:
    """Stands in for `frozen_pipeline.run` under the refill driver.

    The real driver asks `refill(running)` once per scheduling pass and admits
    whatever comes back. This asks the same question in the same order — top
    up first, then do work — but finishes seeds by writing their items instead
    of buying waves. No batch, no thread, no clock.

    `batch` is how many of the seeds in flight finish per pass; 1 makes every
    finish an isolated event, which is what the refill claims are about.
    """

    DOLLARS_PER_SEED = 0.0125  # 1,000 opus-4-8 batch output tokens

    def __init__(self, accepts, batch: int | None = None):
        self.accepts = accepts
        self.batch = batch
        self.admitted: list[list[str]] = []   # one entry per admission
        self.in_flight: list[int] = []        # seeds held, sampled per pass

    def __call__(self, n, seeds_path, out_stem, launch=None, log_path=None,
                 items_path=None, refill=None, **kwargs):
        # `refill` is handed SeedStates by the real scheduler, so it is handed
        # SeedStates here too — the contract under test is the whole point.
        running = [SeedState(seed=s) for s in (launch or [])]
        self.admitted.append([s.seed.name for s in running])
        while True:
            if refill is not None:
                more = [SeedState(seed=s) for s in refill(running)]
                if more:
                    self.admitted.append([s.seed.name for s in more])
                    running += more
            # sampled after the top-up: what the run is holding open
            self.in_flight.append(len(running))
            if not running:
                return [], items_path
            take = self.batch or len(running)
            finishing, running = running[:take], running[take:]
            self._finish(finishing, Path(items_path), Path(log_path))

    def _finish(self, states, items_path: Path, log_path: Path) -> None:
        with open(items_path, "a", encoding="utf-8") as items, \
                open(log_path, "a", encoding="utf-8") as log:
            for state in states:
                state.done = True
                seed = state.seed
                if self.accepts(seed):
                    items.write(json.dumps(
                        {"seed_name": seed.name, "seed_source": seed.source}) + "\n")
                log.write(json.dumps({
                    "seed_name": seed.name, "iteration": 1, "stage": "generator",
                    "usage": {"model": "claude-opus-4-8", "output_tokens": 1000},
                }) + "\n")


def _generate(tmp_path, monkeypatch, seeds, accepts, batch=1, **kwargs):
    """Run Stage A over `seeds` with a fake generator, and hand back both the
    run state and the fake, so a test can read what was admitted when."""
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    fake = FakeStageA(accepts, batch=batch)
    monkeypatch.setattr(scale.frozen_pipeline, "run", fake)
    state = scale.generate(tmp_path / "run", tmp_path, **kwargs)
    return state, fake


def ALL(seed) -> bool:
    """A gate that accepts every seed."""
    return True


def HARSH(seed) -> bool:
    """A gate that rejects one whole domain, so it never leaves the
    below-quota set and never stops asking for slots."""
    return harm_class(seed.text) != "care"


# --- a target number of seeds stays in flight ------------------------------


def test_a_finished_seed_is_replaced_without_waiting_for_its_neighbours(
    tmp_path, monkeypatch
):
    """The acceptance criterion, stated directly.

    Four slots, and exactly one seed finishes per pass. If a cohort were still
    a barrier, the run would sit at 4, 3, 2, 1, 0 seeds in flight and only then
    admit four more. Instead every pass that frees a slot fills it, so the run
    holds 4 until the pool cannot fill them.
    """
    seeds = _corpus(per_domain=4)   # 12 seeds
    state, fake = _generate(tmp_path, monkeypatch, seeds, ALL,
                            batch=1, target=12, in_flight=4)

    assert fake.in_flight[:8] == [4, 4, 4, 4, 4, 4, 4, 4], fake.in_flight
    # every admission after the first launch is a single seed replacing a
    # single finish — no neighbour waited for another
    assert len(fake.admitted[0]) == 4
    assert all(len(a) == 1 for a in fake.admitted[1:]), fake.admitted
    assert len(state["consumed"]) == 12 and state["in_flight"] == []


def test_the_whole_pool_can_be_smaller_than_the_slots_held_open(
    tmp_path, monkeypatch
):
    seeds = _corpus(per_domain=1)
    _, fake = _generate(tmp_path, monkeypatch, seeds, ALL,
                        batch=1, target=3, in_flight=50)
    assert len(fake.admitted[0]) == 3, "the draw cannot invent seeds"
    assert len(scale._accepted_items(tmp_path / "run")) == 3


def test_slots_taper_to_what_the_remaining_items_can_absorb():
    """`held` is the ceiling, the projection is the taper. At the end of a run
    a slot bought for an item already in hand is the most wasteful money there
    is, so the two are combined with a min, not with a max."""
    assert scale.slots(1200, None, 200) == 200
    assert scale.slots(3, None, 200) == 3, "never more seeds than items wanted"
    assert scale.slots(1200, 0.5, 200) == 200, "the ceiling binds"
    assert scale.slots(1200, 0.5, 500) == config.COHORT_MAX
    assert scale.slots(5, 0.9, 200) == config.COHORT_MIN, "the projection binds"
    assert scale.slots(5, 0.9, 4) == 4, "the ceiling still binds under the floor"


# --- a cohort is a checkpoint ----------------------------------------------


def test_a_cohort_boundary_is_a_checkpoint_and_not_a_barrier(tmp_path, monkeypatch):
    """What CONTEXT.md says a cohort is: state written, metrics recorded,
    yield updated. The proof that it is no longer a barrier is that a
    checkpoint row is written while other seeds are still in flight."""
    seeds = _corpus(per_domain=4)
    run_dir = tmp_path / "run"
    state, _ = _generate(tmp_path, monkeypatch, seeds, ALL,
                         batch=1, target=12, in_flight=4)

    rows = [json.loads(line) for line
            in (run_dir / "cohorts.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) == 12, "one checkpoint per seed that finished"
    assert [r["finished"] for r in rows] == list(range(1, 13))
    assert any(r["in_flight"] > 0 for r in rows), \
        "every checkpoint fell on an empty flight, so it was still a barrier"
    assert rows[-1]["accepted"] == 12 and rows[-1]["run_yield"] == 1.0
    assert state["cohort"] == 12

    # state is written at every checkpoint, not only at the end
    assert scale.load_state(run_dir)["run_yield"] == 1.0


def test_a_checkpoint_row_is_not_written_for_a_pass_that_finished_nothing(
    tmp_path, monkeypatch
):
    """`refill` runs once per scheduling pass, which is far more often than a
    seed finishes. A row per pass would make the metrics file a poll log."""
    seeds = _corpus(per_domain=2)
    run_dir = tmp_path / "run"

    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    fake = FakeStageA(ALL, batch=1)
    idle = {"passes": 0}
    real_call = fake.__call__

    def run_with_idle_passes(*args, **kwargs):
        refill = kwargs["refill"]

        def spinning(running):
            # three consultations that free nothing, for every one that does.
            # The slots are full throughout, so each must decline to draw —
            # a consultation that admitted a seed here would leak it, since
            # the driver only launches what the LAST call returns.
            for _ in range(3):
                idle["passes"] += 1
                assert refill(running) == []
            return refill(running)

        kwargs["refill"] = spinning
        return real_call(*args, **kwargs)

    monkeypatch.setattr(scale.frozen_pipeline, "run", run_with_idle_passes)
    scale.generate(run_dir, tmp_path, target=6, in_flight=6)

    rows = (run_dir / "cohorts.jsonl").read_text().splitlines()
    assert idle["passes"] >= 12, "the idle consultations never happened"
    assert len(rows) == 6, f"one row per finish, got {len(rows)}"


def test_cumulative_run_yield_is_accepted_over_finished(tmp_path, monkeypatch):
    """The replacement for per-cohort yield, agreed with the user: accepted
    items over every seed the run has FINISHED so far, read from the same
    accepted set the quota counts. Seeds still in flight are not in the
    denominator — they have not answered yet."""
    seeds = _corpus(per_domain=4)
    run_dir = tmp_path / "run"
    # half the corpus accepts: `care` never does
    _generate(tmp_path, monkeypatch, seeds, HARSH, batch=1, target=8, in_flight=3)

    rows = [json.loads(line) for line
            in (run_dir / "cohorts.jsonl").read_text().splitlines() if line.strip()]
    for row in rows:
        assert row["run_yield"] == pytest.approx(
            round(row["accepted"] / row["finished"], 3)
        ), row
        assert row["finished"] + row["in_flight"] == row["drawn"]


# --- the stratified draw, and the domain a naive refill starves -------------


def _refill_simulation(seeds, quota, rounds, stratified):
    """One slot, refilled `rounds` times, against a gate that rejects `care`.

    This is the draw alone, with the loop the refill driver runs around it.
    `stratified` switches the run-wide per-domain tally on and off, which is
    the entire difference between the draw before ticket 12 and after it.
    """
    consumed, counts, picks = set(), {}, []
    for i in range(rounds):
        drawn: dict[str, int] = {}
        for name in consumed:
            d = _domain_of(seeds, name)
            drawn[d] = drawn.get(d, 0) + 1
        got = scale.draw(seeds, consumed, counts, quota, 1, random.Random(i),
                         drawn if stratified else None)
        if not got:
            break
        domain = harm_class(got[0].text)
        picks.append(domain)
        consumed.add(got[0].name)
        if domain != "care":   # the harsh domain never produces an item
            counts[domain] = counts.get(domain, 0) + 1
    return picks


def test_a_one_slot_refill_starves_every_domain_behind_a_harsh_one():
    """The failure the per-domain quota exists to prevent, reproduced.

    A harsh domain never accepts, so its item count never rises, so it never
    leaves the below-quota set. The pre-ticket draw offers slots to below-quota
    domains in name order, and one slot is only ever the first name — so a
    harsh domain that sorts first takes every refill until its own pool is
    empty, and every domain behind it is never attempted at all. `care` sorts
    before `privacy` and `safety`, and rejects everything.

    Run long enough and the harsh pool drains and the others do get their turn.
    That is not a defence: a run stops at its target or at its cost ceiling,
    and whichever comes first, the domains behind the harsh one are silently
    unrepresented in the corpus. That is exactly "silently underrepresented".
    """
    seeds = _corpus(per_domain=20)
    naive = _refill_simulation(seeds, quota=4, rounds=12, stratified=False)
    assert set(naive) == {"care"}, naive
    assert Counter(naive)["care"] == 12

    stratified = _refill_simulation(seeds, quota=4, rounds=12, stratified=True)
    assert set(stratified) == set(DOMAINS), stratified
    assert Counter(stratified) == {"care": 4, "privacy": 4, "safety": 4}


def test_one_large_draw_is_unchanged_by_the_tally():
    """The tally must not alter a draw that was already stratified: with every
    domain on zero, least-drawn-first IS the old round-robin over sorted names.
    A regression here would silently re-stratify every existing run."""
    seeds = _corpus(per_domain=20)
    for size in (1, 5, 12, 30):
        with_tally = scale.draw(seeds, set(), {}, 8, size, random.Random(3), {})
        without = scale.draw(seeds, set(), {}, 8, size, random.Random(3))
        assert [s.name for s in with_tally] == [s.name for s in without], size


@pytest.mark.parametrize("stratified", [True, False])
def test_the_run_keeps_a_harsh_domain_from_eating_every_refill_slot(
    tmp_path, monkeypatch, stratified
):
    """The same starvation, end to end through `scale.generate`, which is what
    proves the driver actually passes the tally into the draw.

    `stratified=False` restores the pre-ticket draw by dropping the tally at
    the call site and changing nothing else. Under it every seat the run buys
    goes to the harsh domain and the other two are never attempted; under the
    real draw the slots are shared to within one seed.
    """
    seeds = _corpus(per_domain=20)
    if not stratified:
        pre_ticket = scale.draw

        def without_the_tally(seeds_, consumed, counts, quota, size, rng,
                              drawn=None):
            return pre_ticket(seeds_, consumed, counts, quota, size, rng)

        monkeypatch.setattr(scale, "draw", without_the_tally)
    # the ceiling closes admission around a dozen seeds, well before `care`'s
    # pool of 20 runs out — a real run stops somewhere, and this is where
    state, _ = _generate(tmp_path, monkeypatch, seeds, HARSH, batch=1,
                         target=60, in_flight=1, max_cost=0.13)

    spread = Counter(_domain_of(seeds, n) for n in state["consumed"])
    assert 8 <= sum(spread.values()) <= 16, f"the ceiling misfired: {spread}"
    if stratified:
        assert set(spread) == set(DOMAINS), spread
        assert max(spread.values()) - min(spread.values()) <= 1, spread
    else:
        assert set(spread) == {"care"}, spread


def test_quota_keeps_drawing_a_harsh_domain_and_reports_shortfall(
    tmp_path, monkeypatch, capsys
):
    """The quota's own guarantee, unchanged by refill: a domain the gate
    rejects keeps drawing until its pool is empty, and the run ends by naming
    what it could not fill."""
    seeds = _corpus(per_domain=4)
    state, _ = _generate(tmp_path, monkeypatch, seeds, HARSH,
                         batch=1, target=12, in_flight=3)
    assert set(state["consumed"]) == {s.name for s in seeds}, \
        "every pool, including the harsh domain's, must be fully drawn"
    assert len(scale._accepted_items(tmp_path / "run")) == 8
    out = capsys.readouterr().out
    assert "shortfall" in out and "'care': 4" in out
    assert out.count("seed pool exhausted") == 1, "the notice repeated per pass"
    # The pool empties several passes before the last seed answers. A notice
    # written then would understate the corpus and overstate the shortfall, so
    # it waits until nothing is in flight and the count is final.
    assert "exhausted at 8/12 items" in out, out


# --- the cost ceiling, at a point where stopping strands nothing ------------


def test_the_cost_ceiling_closes_admission_and_strands_no_seed(
    tmp_path, monkeypatch, capsys
):
    """The ceiling is read in `refill` and nowhere else, and all it can do
    there is decline to draw. Every seed already in flight keeps its slot and
    finishes, so no paid batch is abandoned — the never-discard-batch-work rule
    restated over in-flight seeds instead of over a cohort.
    """
    seeds = _corpus(per_domain=4)
    run_dir = tmp_path / "run"
    # four slots, one finish per pass. The ceiling fires after the first seed
    # finishes, while three are still in flight.
    state, _ = _generate(tmp_path, monkeypatch, seeds, ALL, batch=1,
                         target=12, in_flight=4, max_cost=0.02)

    out = capsys.readouterr().out
    assert "cost ceiling" in out and "nothing is stranded" in out
    assert out.count("stopping at the cost ceiling") == 1, "reprinted per pass"
    assert "3 seeds in flight" in out, \
        "the ceiling has to be readable at a moment when seeds ARE in flight"
    # Exactly the first launch, and not one seed more. `< 12` passed even when
    # the ceiling printed its message and then drew anyway, because the run
    # still stopped short of the pool — the review found that by deleting the
    # `return` and watching every test stay green.
    assert len(state["consumed"]) == 4, "the ceiling printed, then admitted anyway"
    assert state["in_flight"] == [], "a seed in flight was abandoned"
    # every seed the run had drawn ran to completion and kept its item
    finished = {r["seed_name"] for r in _log_rows(run_dir)}
    assert finished == set(state["consumed"]), "a drawn seed never finished"
    assert len(scale._accepted_items(run_dir)) == len(state["consumed"])


def test_the_ceiling_counts_what_the_seeds_in_flight_still_owe(
    tmp_path, monkeypatch, capsys
):
    """A seed in flight keeps its slot and finishes, so the rest of its waves
    are money the run has already committed. The ceiling has to count that
    liability, or it admits seeds the run cannot afford.

    The fake bills $0.0125 per seed over one wave, so at the moment the ceiling
    is read there are 3 seeds in flight owing $0.0375, $0.0125 is spent and one
    more seed would project $0.0125 — $0.0625 against a $0.03 ceiling.

    Before the fix the projection was `spent / len(consumed)`, and `consumed`
    counts a seed that has bought one wave of seven the same as one that has
    finished. That read $0.0125 + $0.0031 = $0.0156, cleared $0.03 comfortably,
    and drew another seed.
    """
    seeds = _corpus(per_domain=4)
    state, _ = _generate(tmp_path, monkeypatch, seeds, ALL, batch=1,
                         target=12, in_flight=4, max_cost=0.03)

    out = capsys.readouterr().out
    assert "stopping at the cost ceiling" in out, \
        "the ceiling cleared, so the in-flight liability was not counted"
    assert "$0.04 still owed" in out, out
    assert len(state["consumed"]) == 4


def test_the_run_stops_drawing_once_the_target_is_met(tmp_path, monkeypatch):
    """`slots()` floors at COHORT_MIN, so it never returns less than 25 however
    few items remain — `slots(0, 0.9, 4)` is 4, not 0. The target check is
    therefore the only thing standing between a met target and a run that keeps
    buying waves for items it already holds, until the pool is dry.
    """
    seeds = _corpus(per_domain=4)   # 12 seeds
    state, fake = _generate(tmp_path, monkeypatch, seeds, ALL, batch=4,
                            target=4, in_flight=4)

    assert len(state["consumed"]) == 4, "drew past a met target"
    assert sum(len(a) for a in fake.admitted) == 4


def test_a_resume_whose_target_is_already_met_buys_nothing(tmp_path, monkeypatch):
    """A resume relaunches whatever was in flight, because abandoning a seed
    strands its batch. That reasoning does not reach a run whose target is
    already met: `drain_orphans` has harvested every batch those seeds had out,
    so relaunching strands nothing and buys them a fresh wave nobody needs.

    Before the fix the in-flight set was relaunched unconditionally — the
    target check sat inside `refill`, which the `or` only reached when nothing
    was in flight at all.
    """
    seeds = _corpus(per_domain=4)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    scale.save_state(run_dir, {
        "draw_seed": 7,
        "fingerprint": scale.fingerprint(seeds),
        "target": 3,
        "consumed": ["care_00", "privacy_00", "safety_00"],
        "in_flight": ["privacy_00", "safety_00"],
        "run_yield": None,
        "cohort": 1,
    })
    (run_dir / "accepted.jsonl").write_text("".join(
        json.dumps({"seed_name": n, "seed_source": "t"}) + "\n"
        for n in ("care_00", "privacy_00", "safety_00")
    ), encoding="utf-8")

    _, fake = _generate(tmp_path, monkeypatch, seeds, ALL, batch=1,
                        target=3, in_flight=2)

    assert fake.admitted == [], "relaunched a seed for a target already met"
    assert not (run_dir / "run_log.jsonl").exists(), "bought a wave anyway"


def test_a_migrated_pending_cohort_cannot_be_drawn_a_second_time(
    tmp_path, monkeypatch
):
    """`draw` excludes `consumed` and knows nothing about what is in flight, so
    `consumed` has to be a superset of the live set at all times. A pre-ticket
    run directory breaks that on its own: it holds its cohort under `pending`
    and leaves those seeds out of `consumed` until the cohort closes.

    Without the union that migration performs, the relaunched seeds are also
    drawable, and the same seed enters the run twice — two SeedStates, two
    identical `{seed}__w1` custom ids inside one generator batch, which is the
    collision ticket 06 calls impossible by construction.
    """
    seeds = _corpus(per_domain=4)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    scale.save_state(run_dir, {
        "draw_seed": 7,
        "fingerprint": scale.fingerprint(seeds),
        "target": 12,
        "consumed": ["care_00"],
        "yield_ema": 0.5,
        "cohort": 1,
        "pending": {"cohort": 2, "seeds": ["privacy_00", "safety_00"]},
    })
    _, fake = _generate(tmp_path, monkeypatch, seeds, ALL, batch=1,
                        target=12, in_flight=3)

    admitted = [name for group in fake.admitted for name in group]
    assert len(admitted) == len(set(admitted)), \
        f"a seed was drawn twice: {[n for n in admitted if admitted.count(n) > 1]}"


def test_in_flight_below_one_is_refused_rather_than_silently_reinterpreted(
    tmp_path, monkeypatch
):
    """`in_flight or COHORT_BASE` read 0 as "unset" and held 200 seeds instead
    of none, and a negative count left the run holding no slots at all — it
    exited 0 having launched nothing, which reads as a finished run."""
    seeds = _corpus(per_domain=4)
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    for bad in (0, -1):
        with pytest.raises(SystemExit) as caught:
            scale.generate(tmp_path / f"run{bad}", tmp_path,
                           target=12, in_flight=bad)
        assert "--in-flight must be at least 1" in str(caught.value)


def _log_rows(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line
            in (run_dir / "run_log.jsonl").read_text().splitlines() if line.strip()]


def test_no_ceiling_means_no_ledger_read(tmp_path, monkeypatch):
    """`--max-cost` unset must not make the driver price the run on every
    scheduling pass; the ledger re-reads the whole run log each time."""
    seeds = _corpus(per_domain=2)
    reads = []
    monkeypatch.setattr(scale.ledger, "run_total",
                        lambda run_dir: reads.append(run_dir) or 0.0)
    _generate(tmp_path, monkeypatch, seeds, ALL, batch=1, target=6, in_flight=2)
    assert reads == []


# --- the resume contract, restated over in-flight seeds ---------------------


def test_an_interrupted_run_relaunches_exactly_the_seeds_that_were_in_flight(
    tmp_path, monkeypatch
):
    """The resume contract, over a set of in-flight seeds rather than over a
    cohort. `in_flight` is written before the seeds it names go out, so a
    process that dies mid-poll leaves behind the exact set to relaunch; those
    seeds replay from the batch cache and are never re-billed."""
    seeds = _corpus(per_domain=4)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    scale.save_state(run_dir, {
        "draw_seed": 7,
        "fingerprint": scale.fingerprint(seeds),
        "target": 12,
        "consumed": ["care_00", "privacy_01", "safety_02"],
        "in_flight": ["care_00", "safety_02"],
        "run_yield": None,
        "cohort": 4,
    })
    state, fake = _generate(tmp_path, monkeypatch, seeds, ALL,
                            batch=2, target=12, in_flight=2)
    assert fake.admitted[0] == ["care_00", "safety_02"], "resume must not redraw"
    assert "privacy_01" not in [n for a in fake.admitted for n in a], \
        "a seed that already finished was relaunched"
    assert state["in_flight"] == []


def test_a_drawn_seed_is_on_disk_as_in_flight_before_it_is_launched(
    tmp_path, monkeypatch
):
    """Durability precedes dispatch, restated over in-flight seeds.

    `in_flight` is the only record of what to relaunch. A seed that has been
    drawn but is not yet named there is the worst case in the pipeline: it is
    also in `consumed`, so a resumed run will never redraw it, and if it dies
    with a batch out that batch is billed, orphaned and unrecoverable — a
    stranded batch, which is the one thing this ticket must not introduce.
    """
    seeds = _corpus(per_domain=4)
    run_dir = tmp_path / "run"
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    fake = FakeStageA(ALL, batch=1)
    real_call = fake.__call__
    checked = {"draws": 0}

    def run_checking_durability(*args, **kwargs):
        refill = kwargs["refill"]

        def durable(running):
            drawn = refill(running)
            if drawn:
                checked["draws"] += 1
                on_disk = set(scale.load_state(run_dir)["in_flight"])
                assert {s.name for s in drawn} <= on_disk, (
                    "a seed was handed out to be launched before the run state "
                    "on disk said it was in flight"
                )
                assert {s.seed.name for s in running} <= on_disk
            return drawn

        kwargs["refill"] = durable
        return real_call(*args, **kwargs)

    monkeypatch.setattr(scale.frozen_pipeline, "run", run_checking_durability)
    scale.generate(run_dir, tmp_path, target=12, in_flight=3)
    assert checked["draws"] >= 5, "no refill draw ever happened to check"


def test_a_run_directory_stamped_before_ticket_12_carries_its_cohort_over(
    tmp_path, monkeypatch
):
    """A pre-ticket run directory records its in-flight cohort as `pending`
    and leaves those seeds out of `consumed` until the cohort closes. Both are
    migrated, so an interrupted cohort still replays instead of being redrawn
    under a second identity."""
    seeds = _corpus(per_domain=4)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    scale.save_state(run_dir, {
        "draw_seed": 7,
        "fingerprint": scale.fingerprint(seeds),
        "target": 12,
        "consumed": ["care_00"],
        "yield_ema": 0.5,
        "cohort": 1,
        "pending": {"cohort": 2, "seeds": ["privacy_00", "safety_00"]},
    })
    state, fake = _generate(tmp_path, monkeypatch, seeds, ALL,
                            batch=2, target=3, in_flight=2)
    assert fake.admitted[0] == ["privacy_00", "safety_00"], "the cohort was redrawn"
    assert "yield_ema" not in state and "pending" not in state
    assert "care_00" in state["consumed"]


# --- the drill, against the fake transport ---------------------------------


def test_a_kill_mid_poll_replays_as_cache_hits_under_refill(
    tmp_path, monkeypatch, transport
):
    """The acceptance criterion's drill run, simulated.

    Three seeds are in flight; the generator batch is submitted and journaled;
    the process dies before its results are read. A later invocation drains the
    orphan into the cache, relaunches exactly the seeds `in_flight` names, and
    must not re-submit a single generator request.

    This is the whole ticket-12 resume contract on the real machinery — the
    real scheduler, the real journal, the real cache, the real drain — with
    only the provider faked. The live drill over paid batches was NOT run.
    """
    from .test_scheduler import CLEAN, _review

    batchcache._CACHES.clear()
    seeds = [_seed(f"{d}_00", d) for d in DOMAINS]
    monkeypatch.setattr(scale, "load_seeds", lambda path: seeds)
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 1)
    run_dir = tmp_path / "run"

    def die_after_submit(requests, label, progress, hooks):
        hooks.on_handle("anthropic_batch", {"batch_id": "b-gen"},
                        [r["custom_id"] for r in requests])
        raise RuntimeError("process died while polling")

    monkeypatch.setitem(
        routes.ADAPTERS, "anthropic_batch",
        dataclasses.replace(routes.ADAPTERS["anthropic_batch"], run=die_after_submit),
    )
    with pytest.raises(RuntimeError, match="died while polling"):
        scale.generate(run_dir, tmp_path, target=3, in_flight=3)

    state = scale.load_state(run_dir)
    assert sorted(state["in_flight"]) == sorted(s.name for s in seeds), \
        "the seeds that were in flight when it died were not recorded"
    assert not (run_dir / "_results.jsonl").exists(), "nothing was harvested yet"

    # --- a later process ---
    batchcache._CACHES.clear()
    transport.install(monkeypatch)  # the healthy adapters are back
    monkeypatch.setattr(
        batchcache, "_fetch_anthropic",
        lambda batch_id: {f"{s.name}__w1": message(text=CLEAN) for s in seeds},
    )
    transport.respond = lambda r: message(
        text=_review("accept") if "__vote" in r["custom_id"] else CLEAN
    )
    scale.generate(run_dir, tmp_path, target=3, in_flight=3)

    submitted = [cid for call in transport.calls for cid in call]
    assert submitted, "the votes never ran, so they must be misses"
    assert all("__vote" in cid for cid in submitted), \
        f"a drained generator wave was re-billed: {submitted}"
    assert len(scale._accepted_items(run_dir)) == 3
    assert scale.load_state(run_dir)["in_flight"] == []
