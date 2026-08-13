"""Self-checks for the stop rule, from lists of wave records only.

No network, no batch runner, no monkeypatching: the whole point of the seam is
that "does this seed still deserve money" is answerable from a seed's history.
The last test replays the p6 gate pilot log in `docs/evidence/` and asserts the
published figures.

Run: pytest mask_off/test_stoprule.py
"""
import json
from pathlib import Path

from . import config, stoprule
from .stoprule import ACCEPTED, CAP_EXHAUSTED, SEED_DEFECT, Wave

P6_LOG = Path(__file__).resolve().parent.parent / "docs/evidence/p6_gate_pilot_run_log.jsonl"


def _waves(n: int, failed=("t_composition",), **last) -> list[Wave]:
    """`n` unremarkable revise waves; `last` overrides the final one."""
    history = [Wave(iteration=i + 1, failed=tuple(failed)) for i in range(n)]
    if last:
        history[-1] = Wave(iteration=n, failed=tuple(failed), **last)
    return history


# --- the rule ------------------------------------------------------------

def test_no_history_continues():
    assert stoprule.decide([]) == stoprule.CONTINUE


def test_below_the_cap_continues():
    for n in range(1, config.FROZEN_MAX_ITERATIONS):
        verdict = stoprule.decide(_waves(n))
        assert not verdict.stop, f"stopped at wave {n}"
        assert verdict.reason is None


def test_cap_exhausted_stops():
    verdict = stoprule.decide(_waves(config.FROZEN_MAX_ITERATIONS))
    assert (verdict.stop, verdict.reason) == (True, CAP_EXHAUSTED)


def test_accept_stops_before_the_cap():
    verdict = stoprule.decide(_waves(3, accepted=True, failed=()))
    assert (verdict.stop, verdict.reason) == (True, ACCEPTED)


def test_seed_defect_stops_early():
    verdict = stoprule.decide(_waves(2, seed_defect=True))
    assert (verdict.stop, verdict.reason) == (True, SEED_DEFECT)


def test_accept_outranks_the_cap():
    """A seed that accepts on its last permitted wave stopped by accepting."""
    verdict = stoprule.decide(_waves(config.FROZEN_MAX_ITERATIONS, accepted=True))
    assert verdict.reason == ACCEPTED


def test_a_wave_that_never_reached_the_panel_still_counts_toward_the_cap():
    """Generator errors and vote wipeouts burn a wave; that was the old
    inline behaviour in the two non-decision branches and must not change."""
    history = [Wave(iteration=i + 1, stage="generator") for i in range(config.FROZEN_MAX_ITERATIONS)]
    assert stoprule.decide(history).reason == CAP_EXHAUSTED
    assert not stoprule.decide(history[:-1]).stop


def test_the_cap_reads_the_wave_number_not_the_length_of_the_history():
    """A salvage resume rebuilds `iteration` but not the earlier waves."""
    assert stoprule.decide([Wave(iteration=config.FROZEN_MAX_ITERATIONS)]).reason == CAP_EXHAUSTED


def test_the_cap_is_the_only_active_rule():
    assert [type(r) for r in stoprule.active_rules()] == [stoprule.IterationCap]
    # The pinned value is asserted once, in test_pricing_preflight.
    assert stoprule.active_rules()[0].cap == config.FROZEN_MAX_ITERATIONS


def test_the_seam_takes_a_second_rule_without_touching_the_loop():
    """The rule the next pilot justifies plugs in here, not into Stage A."""

    def no_progress(waves):
        shrank = stoprule.shrinking(waves)
        return stoprule.Verdict(True, "no_progress") if shrank is False else stoprule.CONTINUE

    history = [Wave(1, failed=("a",)), Wave(2, failed=("a", "b"))]
    assert not stoprule.decide(history).stop  # inactive by default
    assert stoprule.decide(history, rules=(no_progress,)).reason == "no_progress"
    # ...and an accepted wave still outranks any rule.
    accepted = [*history, Wave(3, accepted=True, failed=())]
    assert stoprule.decide(accepted, rules=(no_progress,)).reason == ACCEPTED


# --- what each wave records ----------------------------------------------

def test_shrinking_compares_the_last_two_waves():
    assert stoprule.shrinking([Wave(1, failed=("a",))]) is None
    assert stoprule.shrinking([Wave(1, failed=("a", "b")), Wave(2, failed=("a",))]) is True
    assert stoprule.shrinking([Wave(1, failed=("a",)), Wave(2, failed=("a", "b"))]) is False
    assert stoprule.shrinking([Wave(1, failed=("a",)), Wave(2, failed=("b",))]) is False


def test_instrument_names_the_failed_constraints_and_the_direction():
    history = [
        Wave(1, failed=("t_composition", "inference_distance"), id_dir="too traceable"),
        Wave(2, failed=("inference_distance",), id_dir="speculative", id_dir_in="too traceable"),
    ]
    assert stoprule.instrument(history) == {
        "failed_constraints": ["inference_distance"],
        "n_failed": 1,
        "shrinking": True,
        "id_dir": "speculative",
        "id_dir_in": "too traceable",
    }


def test_failed_union_reads_the_vote_dumps_in_schema_order():
    votes = [
        {"constraints": {"a": {"passed": True}, "b": {"passed": False}, "c": {"passed": True}}},
        {"constraints": {"a": {"passed": False}, "b": {"passed": False}, "c": {"passed": True}}},
    ]
    assert stoprule.failed_union(votes) == ("a", "b")
    assert stoprule.failed_union([]) == ()


def test_direction_of_dumps_matches_the_majority_of_failing_seats():
    def vote(passed, note):
        return {"constraints": {"inference_distance": {"passed": passed, "note": note}}}

    assert stoprule.direction_of([vote(False, "too traceable: T is stated")]) == "too traceable"
    assert stoprule.direction_of(
        [vote(False, "too traceable: x"), vote(False, "speculative: y")]
    ) is None  # tie
    assert stoprule.direction_of([vote(True, "")]) is None


def test_validity_id_direction_still_answers_through_the_shared_helper():
    """The direction ruling is computed once, in one place, for objects and
    for replayed dumps alike."""
    from .schemas import ConstraintCheck, ValidityConstraints, ValidityReview
    from .validity import id_direction

    def review(note):
        checks = {n: ConstraintCheck(passed=True, note="") for n in ValidityConstraints.model_fields}
        checks["inference_distance"] = ConstraintCheck(passed=False, note=note)
        return ValidityReview(
            constraints=ValidityConstraints(**checks), seed_defect=False,
            verdict="revise", feedback="Scope: frame\nx",
        )

    votes = [review("Speculative: the ask is vague"), review("speculative: same")]
    assert id_direction(votes) == "speculative"
    assert stoprule.direction_of([v.model_dump() for v in votes]) == "speculative"


# --- replay ---------------------------------------------------------------

def test_replay_of_the_p6_log_reproduces_the_published_figures():
    rows = [json.loads(line) for line in P6_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = stoprule.replay(rows)
    assert report["records"] == 103        # one is a lint record, not a wave
    assert report["waves"] == 102
    assert report["seeds"] == 19
    assert report["accepted"] == 14
    assert report["never_accepted"] == 5
    assert report["waves_on_never_accepted"] == 50
    assert report["latest_accepting_wave"] == 6
    assert report["stop_reasons"] == {ACCEPTED: 14, CAP_EXHAUSTED: 5}
    # Legacy log: no seed carries a recorded reason, so all 19 were inferred.
    assert report["inferred_reasons"] == 19


def test_p6_figures_do_not_move_when_the_configured_cap_moves(monkeypatch):
    """The log ran at a cap of 10. What it contains is not a function of what
    `config.FROZEN_MAX_ITERATIONS` says today."""
    rows = [json.loads(line) for line in P6_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    def figures(report):
        return report["waves"], report["waves_on_never_accepted"], report["latest_accepting_wave"]

    baseline = figures(stoprule.replay(rows))
    assert baseline == (102, 50, 6)
    for cap in (3, 7, 10, 25):
        monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", cap)
        assert figures(stoprule.replay(rows)) == baseline, f"cap {cap} restated the log"


def test_inferred_reasons_do_not_move_when_the_configured_cap_moves(monkeypatch):
    """Regression, found in review. The wave COUNTS were already cap-independent,
    but the inferred stop REASON was not: it asked the rule, which reads the live
    cap. Raise the live cap above the cap a finished run used and every
    cap-burner in it reports as still running — five seeds that stopped hours
    ago, described as in flight.
    """
    rows = [json.loads(line) for line in P6_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = {stoprule.CAP_EXHAUSTED: 5, stoprule.ACCEPTED: 14}
    # 2 is far below p6's cap of 10, 100 far above. Both must read the same.
    for cap in (2, 7, 10, 25, 100):
        monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", cap)
        report = stoprule.replay(rows)
        assert report["stop_reasons"] == expected, f"cap {cap} restated the log"
        assert "running" not in report["stop_reasons"]


def test_the_historical_cap_comes_from_the_log_not_the_config(monkeypatch):
    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 99)
    histories = {
        "burner": [Wave(iteration=i + 1) for i in range(10)],
        "quick": [Wave(iteration=1, accepted=True)],
    }
    assert stoprule.historical_cap(histories) == 10
    assert stoprule._reason(histories["burner"], 10) == (stoprule.CAP_EXHAUSTED, True)
    assert stoprule._reason(histories["quick"], 10) == (stoprule.ACCEPTED, True)


def test_a_seed_that_stopped_short_of_the_cap_is_not_called_cap_exhausted():
    """An interrupted run leaves a seed that neither accepted nor reached the
    cap. Naming that honestly beats guessing a reason the log does not carry."""
    reason, inferred = stoprule._reason([Wave(iteration=3)], cap=10)
    assert reason == stoprule.STOPPED_UNRECORDED
    assert inferred is True


def test_a_recorded_reason_always_beats_an_inferred_one():
    history = [Wave(iteration=3, stopped=stoprule.SEED_DEFECT)]
    assert stoprule._reason(history, cap=10) == (stoprule.SEED_DEFECT, False)


def test_the_cap_ladder_prices_the_counterfactual_the_next_pilot_fits():
    rows = [json.loads(line) for line in P6_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    ladder = {r["cap"]: r for r in stoprule.cap_ladder(stoprule.waves_from_log(rows), range(5, 11))}
    assert (ladder[10]["waves"], ladder[10]["lost_items"]) == (102, 0)
    assert (ladder[7]["waves"], ladder[7]["lost_items"]) == (87, 0)   # the configured cap
    assert (ladder[6]["waves"], ladder[6]["lost_items"]) == (82, 0)   # free, but no margin
    assert (ladder[5]["waves"], ladder[5]["lost_items"]) == (75, 2)   # two of fourteen lost
    assert all(r["dollars"] == 0.0 for r in ladder.values()), "no cost function was injected"


def test_occupancy_is_computable_from_a_log_with_no_cohort_boundary():
    """Ticket 12 removes the cohort barrier and with it the only interval the
    tail was measurable across. Enter/leave per seed replaces it."""
    rows = [json.loads(line) for line in P6_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    occupancy = stoprule.replay(rows)["occupancy"]
    assert occupancy["seed_waves"] == 102
    assert occupancy["slot_waves"] == 19 * 10
    assert round(occupancy["wave_occupancy"], 2) == 0.54
    assert 0 < occupancy["time_occupancy"] < 1
    # p6 predates the stamp, so its entry times are one wave late and known to be.
    assert not any(seed["exact_entry"] for seed in occupancy["seeds"])
    assert all(seed["entered"] and seed["left"] for seed in occupancy["seeds"])


def test_replay_prefers_a_recorded_stop_reason_over_inference():
    rows = [
        {"seed_name": "s", "iteration": 1, "accepted": False, "seed_defect": False,
         "votes": [], "stop_rule": {"failed_constraints": ["t_composition"], "id_dir": None,
                                    "id_dir_in": None}},
        {"seed_name": "s", "iteration": 2, "accepted": False, "seed_defect": False,
         "votes": [], "stopped": "no_progress",
         "stop_rule": {"failed_constraints": ["t_composition"], "id_dir": None, "id_dir_in": None}},
    ]
    report = stoprule.replay(rows)
    assert report["waves"] == 2
    assert report["stop_reasons"] == {"no_progress": 1}
    assert report["inferred_reasons"] == 0


def test_stage_a_writes_what_the_replay_reads(tmp_path, monkeypatch, transport):
    """End to end through the fake transport: the loop asks the rule, records
    the per-wave block, and names the reason on the seed's final record."""
    from .frozen_pipeline import run
    from .schemas import Candidate, ConstraintCheck, ValidityConstraints, ValidityReview
    from .seeds import Seed

    monkeypatch.setattr(config, "FROZEN_MAX_ITERATIONS", 2)
    monkeypatch.setattr(config, "GENERATOR_LINT", False)  # not what this test is about

    candidate = Candidate(
        taxonomy="Infrastructure / built environment", hidden_fact="T",
        system_prompt="deployment prompt. Keep replies warm and concise.",
        user_email="From: a@b.c\nSubject: x\n\nbody", pressure_factor="time",
        primary_lever="time pressure", disclosure_rationale="material",
    )

    def review(verdict):
        checks = {n: ConstraintCheck(passed=True, note="") for n in ValidityConstraints.model_fields}
        if verdict != "accept":
            checks["t_composition"] = ConstraintCheck(passed=False, note="two facts")
            checks["inference_distance"] = ConstraintCheck(passed=False, note="speculative: too vague")
        return ValidityReview(
            constraints=ValidityConstraints(**checks), seed_defect=False,
            verdict=verdict, feedback="Scope: frame\nrebuild the ask",
        ).model_dump_json()

    from .conftest import message
    verdict = "revise"
    transport.respond = lambda request: message(
        text=review(verdict) if "__vote" in request["custom_id"] else candidate.model_dump_json()
    )

    stem = tmp_path / "s"
    run(1, tmp_path, stem, launch=[Seed(name="seed_a", text="a seed", source="t")])
    rows = [json.loads(line) for line in (tmp_path / "s_run_log.jsonl").read_text().splitlines()]

    assert [r["iteration"] for r in rows] == [1, 2]
    assert "stopped" not in rows[0], "a seed that may still run named a stop reason"
    assert rows[1]["stopped"] == CAP_EXHAUSTED
    assert rows[0]["stop_rule"] == {
        "failed_constraints": ["t_composition", "inference_distance"],
        "n_failed": 2, "shrinking": None,
        "id_dir": "speculative", "id_dir_in": None,
    }
    # The ruling the first wave produced is the one the second wave carried in.
    assert rows[1]["stop_rule"]["id_dir_in"] == "speculative"
    assert rows[1]["stop_rule"]["shrinking"] is False

    # ...and the same loop, on a panel that accepts, stops for the other reason.
    verdict = "accept"
    stem2 = tmp_path / "t"
    run(1, tmp_path, stem2, launch=[Seed(name="seed_b", text="a seed", source="t")])
    rows = [json.loads(line) for line in (tmp_path / "t_run_log.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["stopped"] == ACCEPTED
    assert rows[0]["stop_rule"]["failed_constraints"] == []

    # The replay reads the run back without inferring anything.
    report = stoprule.replay(rows)
    assert report["stop_reasons"] == {ACCEPTED: 1} and report["inferred_reasons"] == 0
    # Entry is stamped at dispatch, so occupancy is exact rather than a bound.
    seed = report["occupancy"]["seeds"][0]
    assert seed["exact_entry"] and seed["entered"] <= seed["left"]


def test_replay_reads_the_failing_set_out_of_legacy_votes():
    rows = [json.loads(line) for line in P6_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    histories = stoprule.waves_from_log(rows)
    burner = max(histories.values(), key=len)
    assert len(burner) == 10, "p6 ran at a cap of 10; the log says so, not config"
    assert all(w.iteration == i + 1 for i, w in enumerate(burner))
    assert any(w.failed for w in burner), "no wave named a failed constraint"
    assert any(w.id_dir for w in burner), "no wave carried a direction ruling"
