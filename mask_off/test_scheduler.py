"""The Stage A scheduler: seed state, stage concurrency, and durability.

Two halves.

The first half is the accept / revise / exhaust policy, driven as pure state
transitions — a `Scheduler`, a list of fake messages, and three lists standing
in for the run log, the accepted file and the console. No network, no batch
runner, nothing monkeypatched. These are the defects the lockstep loop could
only show by running a paid wave: which seed advanced, which feedback was
attached, whether the direction ruling carried forward.

The second half is the executor and the durability it must not lose: two
stages in flight at once, one batch per stage, the batch-cache Policy reaching
the stage thread, and an interrupted run resuming from the journal with no
re-billing. Those run against the `transport` fixture in conftest.py — one fake
adapter registered across all four routes — with the real cache, the real
journal and the real drain underneath.

Run: pytest mask_off/test_scheduler.py
"""

import dataclasses
import json
import threading
import time

import pytest

from . import batchcache, config, routes
from .conftest import message
from .frozen_pipeline import (
    GENERATOR,
    Work,
    LINT,
    VALIDITY,
    VOTE_RESUBMITS,
    Scheduler,
    SeedState,
    drive,
    run,
)
from .schemas import Candidate, ConstraintCheck, ValidityConstraints, ValidityReview
from .seeds import Seed
from .stoprule import ACCEPTED, CAP_EXHAUSTED, SEED_DEFECT

TONE = "Keep replies warm and concise."


@pytest.fixture(autouse=True)
def fresh_cache_state():
    batchcache._CACHES.clear()
    yield
    batchcache._CACHES.clear()


# --- fixtures on the wire format ------------------------------------------


def _candidate(words: int = 100) -> Candidate:
    return Candidate(
        taxonomy="Infrastructure / built environment",
        hidden_fact="The lot ledger carries consigned units.",
        system_prompt="word " * words + TONE,
        user_email="From: a@b.c\nSubject: x\n\nbody",
        pressure_factor="time pressure",
        primary_lever="time pressure",
        disclosure_rationale="the sender's asset is exposed",
    )


CLEAN = _candidate().model_dump_json()
DIRTY = _candidate(words=240).model_dump_json()  # over the lint's word ceiling


def _review(verdict="revise", seed_defect=False, id_note=None) -> str:
    checks = {
        name: ConstraintCheck(passed=True, note="")
        for name in ValidityConstraints.model_fields
    }
    if verdict != "accept":
        checks["t_composition"] = ConstraintCheck(passed=False, note="two facts")
        if id_note:
            checks["inference_distance"] = ConstraintCheck(
                passed=False, note=f"{id_note}: the chain collapses"
            )
    return ValidityReview(
        constraints=ValidityConstraints(**checks),
        seed_defect=seed_defect,
        verdict=verdict,
        feedback="Scope: frame\nrebuild the ask",
    ).model_dump_json()


def _seed(name: str) -> Seed:
    return Seed(name=name, text=f"MATERIAL FACT: {name}", source="t")


class Harness:
    """A scheduler plus the three side effects it is given, as lists."""

    def __init__(self, *names, refill=None):
        self.log, self.items, self.notes = [], [], []
        self.states = {n: SeedState(seed=_seed(n)) for n in names}
        self.scheduler = Scheduler(
            list(self.states.values()),
            log=self.log.append,
            on_accept=lambda state, item: self.items.append(item),
            note=self.notes.append,
            refill=refill,
        )

    def step(self, stage, respond):
        """Submit `stage`'s batch and deliver `respond(custom_id)` for each."""
        work = self.scheduler.ready(stage)
        assert work is not None, f"{stage} had nothing waiting"
        self.scheduler.deliver(
            work, {r["custom_id"]: respond(r["custom_id"]) for r in work.requests}
        )
        return work

    def wave(self, respond):
        """One whole wave for every seed currently at the generator."""
        self.step(GENERATOR, respond)
        if self.scheduler.waiting(LINT):
            self.step(LINT, respond)
        return self.step(VALIDITY, respond)


def votes_say(verdict, candidate=CLEAN, id_note=None):
    """A responder: candidates for generator ids, one verdict for every vote."""
    def respond(custom_id):
        if "__vote" in custom_id:
            return message(text=_review(verdict, id_note=id_note))
        return message(text=candidate)

    return respond


# --- the policy, as state transitions -------------------------------------


def test_a_clean_candidate_reaches_the_panel_while_its_sibling_regenerates():
    """The lint barrier, gone. A draft that lints clean needs nothing from the
    regeneration of a dirty sibling, and no longer waits behind it."""
    h = Harness("clean_seed", "dirty_seed")
    h.step(GENERATOR, lambda cid: message(text=DIRTY if "dirty" in cid else CLEAN))

    assert h.states["clean_seed"].stage == VALIDITY
    assert h.states["dirty_seed"].stage == LINT

    # both stages have work at the same instant, and each claims only its own
    lint = h.scheduler.ready(LINT)
    panel = h.scheduler.ready(VALIDITY)
    assert [s.seed.name for s in lint.seeds] == ["dirty_seed"]
    assert [s.seed.name for s in panel.seeds] == ["clean_seed"]
    assert [r["custom_id"] for r in lint.requests] == ["dirty_seed__w1__lint"]
    assert all(r["custom_id"].startswith("clean_seed__w1__vote")
               for r in panel.requests)


def test_a_stage_never_submits_a_second_batch_while_its_first_is_in_flight():
    h = Harness("a", "b")
    first = h.scheduler.ready(GENERATOR)
    assert len(first.requests) == 2
    assert h.scheduler.ready(GENERATOR) is None, "a second batch on top of the first"
    # a seed that arrives mid-flight waits, and the next submission sweeps it up
    h.scheduler.deliver(first, {r["custom_id"]: message(text=CLEAN)
                                for r in first.requests})
    h.step(VALIDITY, votes_say("revise"))
    second = h.scheduler.ready(GENERATOR)
    assert sorted(r["custom_id"] for r in second.requests) == ["a__w2", "b__w2"]


def test_each_seed_is_revised_with_its_own_diagnosis_not_a_siblings():
    """The ordering defect the ticket names first, and the one that was
    invisible until now.

    Mutation-tested: rotating `feedback` and `previous` by one across the
    generator batch — every seed handed its neighbour's diagnosis and its
    neighbour's draft — left the entire suite green before this test existed.
    Every fixture gave all seeds byte-identical feedback, so a crossed wire
    produced identical output either way.

    The fix is to make the seeds distinguishable. Each panel here names its own
    seed in the diagnosis, and each seed's draft carries its own marker, so a
    swap shows up as a marker in the wrong request.
    """
    def review_naming(seed_name):
        checks = {n: ConstraintCheck(passed=True, note="")
                  for n in ValidityConstraints.model_fields}
        checks["t_composition"] = ConstraintCheck(passed=False, note="two facts")
        return ValidityReview(
            constraints=ValidityConstraints(**checks), seed_defect=False,
            verdict="revise",
            feedback=f"Scope: frame\nDIAGNOSIS_FOR_{seed_name}",
        ).model_dump_json()

    def draft_naming(seed_name):
        candidate = _candidate()
        candidate.system_prompt = f"DRAFT_OF_{seed_name} " + candidate.system_prompt
        return candidate.model_dump_json()

    h = Harness("alpha", "bravo")

    def respond(custom_id):
        name = custom_id.split("__")[0]
        return message(text=review_naming(name) if "__vote" in custom_id
                       else draft_naming(name))

    h.step(GENERATOR, respond)
    h.step(VALIDITY, respond)

    # Wave 2's requests are where a crossed wire would surface.
    work = h.scheduler.ready(GENERATOR)
    sent = {r["custom_id"].split("__")[0]: json.dumps(r["params"]) for r in work.requests}
    assert set(sent) == {"alpha", "bravo"}
    for name, other in (("alpha", "bravo"), ("bravo", "alpha")):
        assert f"DIAGNOSIS_FOR_{name}" in sent[name], "own diagnosis missing"
        assert f"DIAGNOSIS_FOR_{other}" not in sent[name], "sibling's diagnosis crossed in"
        assert f"DRAFT_OF_{name}" in sent[name], "own previous draft missing"
        assert f"DRAFT_OF_{other}" not in sent[name], "sibling's draft crossed in"


def test_each_seed_locks_against_its_own_direction_ruling():
    """The second ordering defect: the inference-distance ruling a wave
    produced must be the one THAT seed's next wave locks against. Two seeds
    ruled in opposite directions in the same wave must not swap."""
    h = Harness("alpha", "bravo")
    directions = {"alpha": "too traceable", "bravo": "speculative"}

    def respond(custom_id):
        name = custom_id.split("__")[0]
        if "__vote" in custom_id:
            return message(text=_review("revise", id_note=directions[name]))
        return message(text=CLEAN)

    h.step(GENERATOR, respond)
    h.step(VALIDITY, respond)
    assert h.states["alpha"].id_dir == "too traceable"
    assert h.states["bravo"].id_dir == "speculative"

    # The ruling is carried into the next wave's PANEL prompt, not the
    # generator's: `build_vote_requests` takes it as `prev_direction`, and the
    # direction lock is a rule the reviewers apply.
    h.step(GENERATOR, respond)
    work = h.scheduler.ready(VALIDITY)
    sent = {}
    for r in work.requests:
        sent.setdefault(r["custom_id"].split("__")[0], []).append(json.dumps(r["params"]))
    # Match the rendered lock line, not the bare word: both directions appear
    # in the reviewer's own rubric, so a substring search would always hit.
    def locked_to(direction):
        return f"failed inference_distance with the prefix `{direction}:`"

    for name, other in (("alpha", "bravo"), ("bravo", "alpha")):
        body = " ".join(sent[name])
        assert locked_to(directions[name]) in body, f"{name} lost its own ruling"
        assert locked_to(directions[other]) not in body, (
            f"{name} locked against {other}'s ruling"
        )


class _AlwaysOffering:
    """A scheduler stub that keeps offering work for two stages.

    The guard only matters at one moment: a stage's batch is still pending,
    ANOTHER stage's batch completes, and the loop re-scans. Until something
    completes the loop sits in `wait(FIRST_COMPLETED)` and cannot resubmit
    anything, which is why a single-stage stub proves nothing.
    """

    def __init__(self, offers: int = 6):
        self.offers, self.made, self.delivered = offers, 0, []

    def top_up(self):
        return 0

    def ready(self, stage):
        if stage not in (GENERATOR, VALIDITY) or self.made >= self.offers:
            return None
        self.made += 1
        return Work(stage, stage, [], frozenset(), ())

    def deliver(self, work, msgs):
        self.delivered.append(work)


def test_drive_skips_a_stage_whose_batch_is_still_out():
    """`drive`'s own in-flight guard, tested directly.

    Without `if stage in flight: continue`, the loop resubmits a stage the
    moment it has more work, even while its batch is out. That overwrites
    `flight[stage]`, so the first future is never delivered and its seeds stay
    in flight forever — `drive` never returns. No money is lost, because the
    on_result hook still appends every result to the cache and a re-run
    replays them as hits, but the run hangs.

    Held deterministically: the generator batch never completes until the test
    releases it, and the validity batch completes immediately, so the loop is
    guaranteed to re-scan while the generator is still in flight.
    """
    lock = threading.Lock()
    live: dict[str, int] = {}
    peak: dict[str, int] = {}
    release = threading.Event()
    rescanned = threading.Event()

    def submit(work):
        with lock:
            live[work.stage] = live.get(work.stage, 0) + 1
            peak[work.stage] = max(peak.get(work.stage, 0), live[work.stage])
        try:
            if work.stage == GENERATOR:
                release.wait(timeout=5)
            else:
                rescanned.set()   # a completion the loop will act on
            return {}
        finally:
            with lock:
                live[work.stage] -= 1

    scheduler = _AlwaysOffering()
    thread = threading.Thread(target=drive, args=(scheduler, submit))
    thread.start()
    rescanned.wait(timeout=5)
    for _ in range(100):          # give the loop many chances to double-submit
        if peak.get(GENERATOR, 0) > 1:
            break
        time.sleep(0.002)
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive(), "drive did not return"
    assert peak.get(GENERATOR, 0) == 1, f"the generator held two batches: {peak}"


def test_accept_ends_the_seed_and_hands_over_the_item():
    h = Harness("a")
    h.wave(votes_say("accept"))
    state = h.states["a"]
    assert state.done and state.accepted_item is not None
    assert h.items == [state.accepted_item]
    assert state.accepted_item["seed_name"] == "a"
    assert state.accepted_item["iterations"] == 1
    assert h.log[-1]["stopped"] == ACCEPTED
    assert h.scheduler.ready(GENERATOR) is None, "an accepted seed must not run on"


def test_revise_carries_the_feedback_and_the_direction_ruling_forward():
    """The two ordering defects the lockstep loop could only show by paying:
    the diagnosis has to reach the NEXT generator prompt, and the direction
    ruling this wave produced has to be the one the next wave locks against."""
    h = Harness("a")
    h.wave(votes_say("revise", id_note="speculative"))
    state = h.states["a"]
    assert not state.done and state.stage == GENERATOR
    assert state.feedback.startswith("VALIDITY REVISION")
    assert "rebuild the ask" in state.feedback
    assert state.previous is not None, "the rejected draft must be shown back"
    assert state.id_dir == "speculative"
    assert h.log[-1]["stop_rule"]["id_dir_in"] is None, "wave 1 carried nothing in"

    gen = h.scheduler.ready(GENERATOR)
    assert "rebuild the ask" in str(gen.requests[0]["params"]), \
        "the feedback never reached the generator"
    h.scheduler.deliver(gen, {r["custom_id"]: message(text=CLEAN)
                              for r in gen.requests})
    panel = h.scheduler.ready(VALIDITY)
    assert "`speculative:`" in str(panel.requests[0]["params"]), \
        "the direction lock never reached the panel"
    h.scheduler.deliver(panel, {r["custom_id"]: message(text=_review(id_note="speculative"))
                                for r in panel.requests})
    assert h.log[-1]["stop_rule"]["id_dir_in"] == "speculative"


def test_exhaust_stops_the_seed_at_the_cap(monkeypatch):
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 2)
    h = Harness("a")
    h.wave(votes_say("revise"))
    assert not h.states["a"].done
    h.wave(votes_say("revise"))
    assert h.states["a"].done and h.items == []
    assert h.log[-1]["stopped"] == CAP_EXHAUSTED
    assert [r["iteration"] for r in h.log] == [1, 2]
    assert h.notes[-1] == "exhausted a"


def test_a_defective_seed_stops_on_the_defect_not_the_cap():
    h = Harness("a")
    h.wave(lambda cid: message(
        text=_review(seed_defect=True) if "__vote" in cid else CLEAN
    ))
    assert h.states["a"].done
    assert h.log[-1]["stopped"] == SEED_DEFECT
    assert "seed defect" in h.notes[-1]


def test_a_generator_failure_spends_the_wave_and_the_seed_tries_again():
    h = Harness("a")
    h.step(GENERATOR, lambda cid: message(text="not json"))
    state = h.states["a"]
    assert not state.done and state.stage == GENERATOR, "the seed gets another wave"
    assert h.log[-1]["stage"] == GENERATOR and "error" in h.log[-1]
    assert "stopped" not in h.log[-1]
    assert len(state.waves) == 1, "a wave that never reached the panel is still spent"
    assert h.scheduler.ready(VALIDITY) is None, "nothing to vote on"
    assert [r["custom_id"] for r in h.scheduler.ready(GENERATOR).requests] == ["a__w2"]


def test_a_wave_whose_whole_panel_is_unreadable_is_spent_and_retried():
    """Resubmission is tried first and bounded; only then is the wave written
    off. The seed keeps its remaining waves — an unreadable panel is a
    transport failure, not a verdict."""
    h = Harness("a")
    h.step(GENERATOR, lambda cid: message(text=CLEAN))
    state = h.states["a"]
    for _ in range(1 + VOTE_RESUBMITS):
        h.step(VALIDITY, lambda cid: message(text="not json"))
    assert state.stage == GENERATOR and not state.done
    assert h.log[-1]["stage"] == VALIDITY and h.log[-1]["error"]
    assert len(state.waves) == 1


def test_a_bad_vote_slot_is_resubmitted_under_its_own_id_and_bounded():
    """Resubmission reuses the identifier and rides the refresh set, so a
    stale cached row is superseded rather than accumulated (ticket 06)."""
    h = Harness("a")
    h.step(GENERATOR, lambda cid: message(text=CLEAN))
    good = _review("accept")

    def one_bad_slot(custom_id):
        return message(text="not json" if custom_id.endswith("vote1") else good)

    first = h.step(VALIDITY, one_bad_slot)
    assert first.refresh == frozenset(), "a first submission refreshes nothing"

    resubmit = h.scheduler.ready(VALIDITY)
    assert [r["custom_id"] for r in resubmit.requests] == ["a__w1__vote1"]
    assert resubmit.refresh == {"a__w1__vote1"}, \
        "a resubmitted slot must supersede its cached row, not sit beside it"
    h.scheduler.deliver(resubmit, {"a__w1__vote1": message(text=good)})
    assert h.states["a"].done and h.log[-1]["stopped"] == ACCEPTED
    assert h.log[-1]["vote_errors"] == []


def test_a_slot_that_never_recovers_is_given_up_on_after_a_bounded_retry():
    h = Harness("a")
    h.step(GENERATOR, lambda cid: message(text=CLEAN))
    good = _review("accept")
    respond = lambda cid: message(
        text="not json" if cid.endswith("vote1") else good
    )
    submissions = [h.step(VALIDITY, respond)]
    while h.states["a"].stage == VALIDITY and not h.states["a"].done:
        submissions.append(h.step(VALIDITY, respond))
    assert len(submissions) == 1 + VOTE_RESUBMITS
    # the wave is still tallied, on what parsed, and says so
    assert h.log[-1]["short_votes"] is True
    assert h.log[-1]["n_votes"] == config.VALIDITY_VOTES - 1
    assert h.states["a"].done and h.log[-1]["stopped"] == ACCEPTED


def test_seeds_advance_independently_and_land_on_different_waves(monkeypatch):
    """Three seeds, three fates, one shared set of stages. This is the smoke
    run: the same items the lockstep loop accepted, on the same waves."""
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 2)
    h = Harness("accepts_first", "accepts_second", "never_accepts")

    def respond(custom_id):
        if "__vote" not in custom_id:
            return message(text=CLEAN)
        seed, wave = custom_id.split("__w")[0], custom_id.split("__w")[1][0]
        accept = seed == "accepts_first" or (seed == "accepts_second" and wave == "2")
        return message(text=_review("accept" if accept else "revise"))

    h.wave(respond)
    assert [item["seed_name"] for item in h.items] == ["accepts_first"]
    assert h.states["accepts_first"].done
    assert h.states["accepts_second"].stage == GENERATOR
    # wave 2 carries only the two seeds still running
    second = h.scheduler.ready(GENERATOR)
    assert sorted(r["custom_id"] for r in second.requests) == [
        "accepts_second__w2", "never_accepts__w2"
    ]
    h.scheduler.deliver(second, {r["custom_id"]: respond(r["custom_id"])
                                 for r in second.requests})
    h.step(VALIDITY, respond)

    assert {item["seed_name"]: item["iterations"] for item in h.items} == {
        "accepts_first": 1, "accepts_second": 2
    }
    assert h.states["never_accepts"].done
    # one decision record per (seed, wave) and no more: the ledger's dedup key
    # is (seed_name, iteration, stage) and a stage split across records breaks it
    keys = [(r["seed_name"], r["iteration"], r.get("stage")) for r in h.log]
    assert len(keys) == len(set(keys)) == 5


# --- the executor and its durability --------------------------------------


class Overlap:
    """A `submit` that holds each batch until a second stage joins it."""

    def __init__(self, respond, want=2):
        self.respond, self.want = respond, want
        self.cond = threading.Condition()
        self.live = self.peak = 0
        self.stages = []

    def __call__(self, work):
        with self.cond:
            self.stages.append(work.stage)
            self.live += 1
            self.peak = max(self.peak, self.live)
            self.cond.notify_all()
            # a lone batch must not hang the run, so the wait is bounded
            self.cond.wait_for(lambda: self.live >= self.want, timeout=0.25)
            self.live -= 1
        return {r["custom_id"]: self.respond(r["custom_id"]) for r in work.requests}


def test_two_stages_hold_a_batch_in_flight_at_the_same_time(monkeypatch):
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 1)
    h = Harness("clean_seed", "dirty_seed")
    submit = Overlap(lambda cid: message(
        text=_review("accept") if "__vote" in cid
        else (DIRTY if cid == "dirty_seed__w1" else CLEAN)
    ))
    drive(h.scheduler, submit)

    assert submit.peak >= 2, f"stages never overlapped: {submit.stages}"
    assert {LINT, VALIDITY} <= set(submit.stages)
    assert len(h.items) == 2, "both seeds accepted"
    assert all(s.done for s in h.states.values())


def test_drive_returns_only_when_every_seed_is_done(monkeypatch):
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 3)
    h = Harness("a", "b")
    calls = []

    def submit(work):
        calls.append(work.stage)
        return {r["custom_id"]: message(
            text=_review("revise") if "__vote" in r["custom_id"] else CLEAN
        ) for r in work.requests}

    drive(h.scheduler, submit)
    assert all(s.done and s.iteration == 3 for s in h.states.values())
    assert calls.count(GENERATOR) == 3, "one generator batch per wave, cohort-wide"


def _accept_everything(work):
    return {r["custom_id"]: message(
        text=_review("accept") if "__vote" in r["custom_id"] else CLEAN
    ) for r in work.requests}


def test_a_refill_source_admits_seeds_mid_run_and_they_run_to_completion(
    monkeypatch,
):
    """Ticket 12's seam on the real scheduler, not on a stand-in for it.

    One slot. The refill source hands over the next seed only once the slot is
    free, so the run is three seeds long and never holds two. Three things are
    load-bearing here and each fails alone: `drive` must consult the source
    every pass, `top_up` must ADMIT what it gets rather than only ask, and
    `admit` must extend the seed set the scheduler already owns.
    """
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 1)
    queue = [_seed("second"), _seed("third")]
    asked = []

    def refill(running):
        asked.append([s.seed.name for s in running])
        if running or not queue:
            return []
        return [queue.pop(0)]

    h = Harness("first", refill=refill)
    drive(h.scheduler, _accept_everything)

    assert [item["seed_name"] for item in h.items] == ["first", "second", "third"]
    assert [s.seed.name for s in h.scheduler.states] == [
        "first", "second", "third"
    ], "an admitted seed never joined the scheduler's set"
    assert asked[0] == ["first"], "the source was not asked before anything finished"
    assert [] in asked, "the source was never asked with a free slot"
    assert all(s.done for s in h.scheduler.states)


def test_run_counts_the_seeds_a_refill_source_admitted(
    tmp_path, monkeypatch, transport
):
    """`run` launched one seed and finished two. Its report, its accepted list
    and its yield all have to be over the set the scheduler ended with."""
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 1)
    transport.respond = lambda r: message(
        text=_review("accept") if "__vote" in r["custom_id"] else CLEAN
    )
    queue = [_seed("second")]
    accepted, _ = run(
        1, tmp_path, tmp_path / "s", launch=[_seed("first")],
        refill=lambda running: [] if running or not queue else [queue.pop(0)],
    )
    assert sorted(item["seed_name"] for item in accepted) == ["first", "second"]


def _one_seed_run(tmp_path, name="seed_a"):
    return run(1, tmp_path, tmp_path / "s", launch=[_seed(name)])


def test_the_batch_policy_reaches_the_stage_thread(tmp_path, monkeypatch, transport):
    """A stage runs on a worker thread, and `run_batch_retry` reads the cache
    Policy from a contextvar ONCE on its calling thread. A bare thread starts
    from an empty context: without the context copy in `drive` the stage would
    silently run uncached and unjournaled, and a paid batch would be
    unrecoverable. The journal and the results file are the proof it arrived.
    """
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 1)
    transport.respond = lambda r: message(
        text=_review("revise") if "__vote" in r["custom_id"] else CLEAN
    )
    with batchcache.policy(run_dir=tmp_path):
        _one_seed_run(tmp_path)
    assert (tmp_path / "_results.jsonl").exists(), "the stage thread saw no cache"
    journal = [json.loads(line) for line
               in (tmp_path / "_batches.jsonl").read_text().splitlines()]
    assert any(row["kind"] == "handle" and row["route"] == "anthropic_batch"
               for row in journal), "the generator batch was never journaled"

    # replaying the same cohort re-bills nothing
    transport.calls.clear()
    batchcache._CACHES.clear()  # a new process
    with batchcache.policy(run_dir=tmp_path):
        _one_seed_run(tmp_path)
    assert transport.calls == [], "a replayed wave must be all hits, no misses"


def test_an_interrupted_run_resumes_from_the_journal_with_no_re_billing(
    tmp_path, monkeypatch, transport
):
    """Death mid-poll: the generator batch is submitted and journaled, then the
    process dies before its results are read. The drain must find it in a later
    process, fold it into the cache, and the replay must report a hit."""
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 1)
    candidate = message(text=CLEAN)

    def die_after_submit(requests, label, progress, hooks):
        hooks.on_handle("anthropic_batch", {"batch_id": "b-gen"},
                        [r["custom_id"] for r in requests])
        raise RuntimeError("process died while polling")

    monkeypatch.setitem(
        routes.ADAPTERS, "anthropic_batch",
        dataclasses.replace(routes.ADAPTERS["anthropic_batch"], run=die_after_submit),
    )
    with pytest.raises(RuntimeError, match="died while polling"):
        with batchcache.policy(run_dir=tmp_path):
            _one_seed_run(tmp_path)
    assert not (tmp_path / "_results.jsonl").exists(), "nothing was harvested yet"

    # --- a later process ---
    batchcache._CACHES.clear()
    transport.install(monkeypatch)  # the healthy adapters are back
    monkeypatch.setattr(batchcache, "_fetch_anthropic",
                        lambda batch_id: {"seed_a__w1": candidate})
    assert batchcache.drain_orphans(tmp_path) == 1, "the paid batch was lost"

    transport.respond = lambda r: message(
        text=_review("revise") if "__vote" in r["custom_id"] else CLEAN
    )
    transport.calls.clear()
    with batchcache.policy(run_dir=tmp_path):
        _one_seed_run(tmp_path)
    submitted = [cid for call in transport.calls for cid in call]
    assert "seed_a__w1" not in submitted, "the drained generator wave was re-billed"
    assert submitted, "the votes never ran, so they must be misses"
    assert all("__vote" in cid for cid in submitted)
