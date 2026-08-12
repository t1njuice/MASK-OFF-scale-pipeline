"""Self-checks: vote resubmission is bounded and complete; seed_defect is a
strict majority of parsed votes, decoupled from VALIDITY_ACCEPT.

Run: pytest mask_off/test_frozen_votes.py
"""
from types import SimpleNamespace
from unittest.mock import patch

from . import config
from .frozen_pipeline import resubmit_votes
from .schemas import ConstraintCheck, ValidityConstraints, ValidityReview
from .validity import parse_vote, tally


def _vote(verdict="revise", seed_defect=False):
    checks = {
        name: ConstraintCheck(passed=True, note="")
        for name in ValidityConstraints.model_fields
    }
    return ValidityReview(
        constraints=ValidityConstraints(**checks),
        seed_defect=seed_defect,
        verdict=verdict,
        feedback="Scope: frame\nrebuild the ask",
    )


def _msg(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _reqs(n):
    return [{"custom_id": f"cand-x__vote{i}", "params": {}} for i in range(n)]


def test_seed_defect_is_strict_majority_not_accept_threshold():
    original = config.VALIDITY_ACCEPT
    try:
        config.VALIDITY_ACCEPT = 3  # unanimity accept rule (P4 shape)
        two_of_three = [_vote(seed_defect=True), _vote(seed_defect=True), _vote()]
        assert tally(two_of_three)["seed_defect"], "2/3 majority must kill the seed"
        one_of_two = [_vote(seed_defect=True), _vote()]
        assert not tally(one_of_two)["seed_defect"], "a tie is not a majority"
    finally:
        config.VALIDITY_ACCEPT = original


def test_tally_scope_tie_break_is_deterministic():
    # Two revise votes with different scopes: a 1-1 scope tie. The winner must
    # not depend on set iteration order (hash randomization across processes).
    def vote_with_scope(scope):
        v = _vote()
        return v.model_copy(update={"feedback": f"Scope: {scope}\nrebuild"})

    votes = [vote_with_scope("frame"), vote_with_scope("ask")]
    assert tally(votes)["scope"] == "ask", "tie must break to the sorted-first scope"


def test_resubmit_votes_refills_missing_and_unparseable_then_stops():
    good = _msg(_vote().model_dump_json())
    calls = []

    def fake_retry(reqs, label, progress=None, refresh=None):
        calls.append([r["custom_id"] for r in reqs])
        return {r["custom_id"]: good for r in reqs}

    # vote0 parsed, vote1 unparseable, vote2 missing: one pass refills both.
    start = {"cand-x__vote0": good, "cand-x__vote1": _msg("not json")}
    with patch("mask_off.frozen_pipeline.run_batch_retry", fake_retry):
        out = resubmit_votes(_reqs(3), dict(start), progress=None)
    assert calls == [["cand-x__vote1", "cand-x__vote2"]]
    for i in range(3):
        parse_vote(out[f"cand-x__vote{i}"])  # every slot now parses

    # a slot that never recovers is retried exactly 3 times, then given up on.
    calls.clear()

    def never_recovers(reqs, label, progress=None, refresh=None):
        calls.append(label)
        return {r["custom_id"]: _msg("still not json") for r in reqs}

    with patch("mask_off.frozen_pipeline.run_batch_retry", never_recovers):
        resubmit_votes(_reqs(2), {}, progress=None)
    assert len(calls) == 3
