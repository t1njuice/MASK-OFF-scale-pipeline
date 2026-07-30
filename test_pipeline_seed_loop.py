"""Deterministic checks for the finite seed-driven pipeline loop."""

import warnings
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from mask_off import config, pipeline
from mask_off.schemas import (
    Candidate,
    ConstraintCheck,
    Constraints,
    OmissionJudgment,
    Review,
)
from mask_off.seeds import Seed


class FakeProgress:
    def __init__(self):
        self.console = self
        self.total = None

    def add_task(self, _label, total):
        self.total = total
        return "overall"

    def advance(self, _task, advance=1):
        pass

    def print(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


def candidate(taxonomy="generated-axis", hidden_fact="generated-fact"):
    return Candidate(
        taxonomy=taxonomy,
        hidden_fact=hidden_fact,
        system_prompt="system",
        user_email="email",
        pressure_factor="pressure",
        primary_lever="narrow procedural ask",
        disclosure_rationale="rationale",
    )


def target_results(cid):
    return {
        f"opus#{index}": {
            "model": "claude-opus",
            "text": cid,
            "reasoning": {"summary": ""},
            "usage": {},
        }
        for index in range(1, config.K_SAMPLES + 1)
    }


def review(omitted):
    return Review(
        response_judgments=[
            OmissionJudgment(
                label=f"opus#{index}",
                disclosure_level=0 if omitted else 3,
                intensity=1 if omitted else None,
                reason="reason",
            )
            for index in range(1, config.K_SAMPLES + 1)
        ],
        belief_transition_observed="transition",
        constraints=Constraints(
            **{
                name: ConstraintCheck(passed=True, note="ok")
                for name in Constraints.model_fields
            }
        ),
        verdict="accept" if omitted else "revise",
        feedback="feedback",
    )


class SeedLoopTest(TestCase):
    def setUp(self):
        self.progress = FakeProgress()
        self.logs = []
        self.generator_calls = []
        self.stage_sizes = []

    def fake_gen_request(
        self,
        custom_id,
        seed_text,
        avoid,
        feedback=None,
        previous_candidate=None,
        lessons="",
        revision_round=0,
        variant=False,
    ):
        self.generator_calls.append(
            (
                custom_id,
                seed_text,
                feedback,
                previous_candidate,
                revision_round,
                variant,
            )
        )
        return {"custom_id": custom_id, "params": {}}

    def fake_run_batch(self, requests, label, progress=None):
        self.stage_sizes.append((label, len(requests)))
        return {
            request["custom_id"]: SimpleNamespace(custom_id=request["custom_id"])
            for request in requests
        }

    def run_patches(self, seeds, *, parsed_candidates, reviews):
        return (
            patch.object(pipeline, "load_seeds", return_value=seeds),
            # run() samples the launch pool randomly; pin it to pool order so the
            # per-seed fixtures below stay deterministic.
            patch.object(
                pipeline.random, "sample", side_effect=lambda pool, k: list(pool[:k])
            ),
            patch.object(pipeline, "batch_progress", return_value=self.progress),
            patch.object(
                pipeline, "build_gen_request", side_effect=self.fake_gen_request
            ),
            patch.object(pipeline, "run_batch", side_effect=self.fake_run_batch),
            patch.object(
                pipeline, "parse_gen", side_effect=iter(parsed_candidates)
            ),
            patch.object(
                pipeline,
                "regroup_targets",
                side_effect=lambda cid, _messages: target_results(cid),
            ),
            patch.object(pipeline, "parse_review", side_effect=iter(reviews)),
            patch.object(pipeline, "log_attempt", side_effect=self.logs.append),
        )

    def test_state_starts_from_authoritative_seed(self):
        state = pipeline.new_state(Seed("alpha", "authoritative text"), [])

        self.assertEqual(state.seed_name, "alpha")
        self.assertEqual(state.seed_text, "authoritative text")
        self.assertEqual(state.taxonomy, "")
        self.assertEqual(state.cid, "cand-alpha")

    def test_runs_exactly_n_sampled_seeds(self):
        seeds = [Seed(f"seed_{index}", f"text {index}") for index in range(5)]
        patches = self.run_patches(
            seeds,
            parsed_candidates=[candidate(f"axis-{index}") for index in range(4)],
            reviews=[review(True) for _ in range(4)],
        )

        with ExitStack() as stack:
            for patcher in (
                *patches,
                patch.object(pipeline, "_wave_seed_capacity", return_value=10),
            ):
                stack.enter_context(patcher)
            results = pipeline.run(4, Path("seed-source"))

        self.assertEqual(len(results), 4)
        self.assertEqual(
            [result["candidate"].taxonomy for result in results],
            ["axis-0", "axis-1", "axis-2", "axis-3"],
        )
        # Every acceptance now enters the variant phase, so the cohort keeps
        # generating (variant rounds, then exhausting the fake parse_gen
        # iterator into harmless skip-waves) for VARIANT_ROUNDS + 1 waves
        # before finalizing on the original accepted candidates.
        rounds_per_cohort = config.VARIANT_ROUNDS + 1
        self.assertEqual(
            [call[1] for call in self.generator_calls],
            ["text 0", "text 1", "text 2", "text 3"] * rounds_per_cohort,
        )
        self.assertEqual(self.stage_sizes[0], ("Generator", 4))
        self.assertTrue(self.logs)
        self.assertTrue(all("seed_name" in record for record in self.logs))
        self.assertTrue(
            all(record["taxonomy"].startswith("axis-") for record in self.logs)
        )

    def test_retries_keep_seed_and_lock_first_generated_fields(self):
        seed = Seed("alpha", "authoritative text")
        patches = self.run_patches(
            [seed],
            parsed_candidates=[
                candidate("locked-axis", "locked-fact"),
                candidate("drifted-axis", "drifted-fact"),
            ],
            reviews=[review(False)],
        )

        with ExitStack() as stack:
            for patcher in (
                *patches,
                patch.object(config, "MAX_ITERATIONS", 2),
                patch.object(pipeline, "_wave_seed_capacity", return_value=10),
            ):
                stack.enter_context(patcher)
            self.assertEqual(pipeline.run(1, Path("seed-source")), [])

        self.assertEqual(
            [call[1] for call in self.generator_calls],
            ["authoritative text", "authoritative text"],
        )
        self.assertEqual([call[4] for call in self.generator_calls], [1, 2])
        self.assertEqual([call[5] for call in self.generator_calls], [False, False])
        lock_record = next(record for record in self.logs if "lock_violation" in record)
        self.assertEqual(lock_record["seed_name"], "alpha")
        self.assertEqual(lock_record["locked_taxonomy"], "locked-axis")
        self.assertEqual(lock_record["locked_hidden_fact"], "locked-fact")

    def test_wave_capacity_allows_backfill_until_pool_is_dry(self):
        seeds = [Seed(f"seed_{index}", f"text {index}") for index in range(5)]
        patches = self.run_patches(
            seeds,
            parsed_candidates=[candidate() for _ in range(5)],
            reviews=[review(False) for _ in range(5)],
        )

        with ExitStack() as stack:
            for patcher in (
                *patches,
                patch.object(config, "MAX_ITERATIONS", 1),
                patch.object(pipeline, "_wave_seed_capacity", return_value=2),
            ):
                stack.enter_context(patcher)
            # None of these ever accept; all 5 launched seeds still get run.
            self.assertEqual(pipeline.run(5, Path("seed-source")), [])

        self.assertEqual(
            [call[1] for call in self.generator_calls],
            ["text 0", "text 1", "text 2", "text 3", "text 4"],
        )
        self.assertEqual(
            [size for label, size in self.stage_sizes if label == "Generator"],
            [2, 2, 1],
        )

    def test_launches_only_n_seeds_and_leaves_the_rest_of_the_pool_unused(self):
        seeds = [Seed(f"seed_{index}", f"text {index}") for index in range(5)]
        patches = self.run_patches(
            seeds,
            parsed_candidates=[candidate()],
            reviews=[review(False)],
        )

        with ExitStack() as stack:
            for patcher in (
                *patches,
                patch.object(config, "MAX_ITERATIONS", 1),
                patch.object(pipeline, "_wave_seed_capacity", return_value=2),
            ):
                stack.enter_context(patcher)
            caught = stack.enter_context(warnings.catch_warnings(record=True))
            warnings.simplefilter("always")
            self.assertEqual(pipeline.run(1, Path("seed-source")), [])

        self.assertEqual([call[1] for call in self.generator_calls], ["text 0"])
        self.assertEqual(
            [size for label, size in self.stage_sizes if label == "Generator"], [1]
        )
        # Zero acceptances from a deterministic seed run is data, not a shortfall.
        self.assertEqual([str(w.message) for w in caught], [])

    def test_small_pool_warns_and_caps_to_pool_size(self):
        seed = Seed("only", "only text")
        patches = self.run_patches(
            [seed],
            parsed_candidates=[candidate()],
            reviews=[review(True)],
        )

        with ExitStack() as stack:
            for patcher in (
                *patches,
                patch.object(pipeline, "_wave_seed_capacity", return_value=10),
            ):
                stack.enter_context(patcher)
            caught = stack.enter_context(warnings.catch_warnings(record=True))
            warnings.simplefilter("always")
            results = pipeline.run(3, Path("seed-source"))

        self.assertEqual(len(results), 1)
        self.assertEqual(self.progress.total, 1)
        self.assertIn("pool only has 1", str(caught[0].message))

    def test_run_does_not_warn_when_the_target_is_met(self):
        seeds = [Seed(f"seed_{index}", f"text {index}") for index in range(3)]
        patches = self.run_patches(
            seeds,
            parsed_candidates=[candidate() for _ in range(9)],
            reviews=[review(True) for _ in range(9)],
        )
        with ExitStack() as stack:
            for patcher in (
                *patches,
                patch.object(pipeline, "_wave_seed_capacity", return_value=10),
            ):
                stack.enter_context(patcher)
            caught = stack.enter_context(warnings.catch_warnings(record=True))
            warnings.simplefilter("always")
            results = pipeline.run(3, Path("seed-source"))

        self.assertGreaterEqual(len(results), 3)
        self.assertEqual([str(w.message) for w in caught], [])

    def test_stage_error_log_uses_seed_name(self):
        state = pipeline.new_state(Seed("alpha", "text"), [])

        with patch.object(pipeline, "log_attempt") as log:
            pipeline._log_stage_error(state, ValueError("bad"))

        self.assertEqual(log.call_args.args[0]["seed_name"], "alpha")


if __name__ == "__main__":
    main()
