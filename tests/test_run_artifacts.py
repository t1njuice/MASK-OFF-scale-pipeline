import unittest

from mask_off import pipeline


class RunArtifactsTest(unittest.TestCase):
    def test_pilot_paths_share_one_timestamp(self):
        paths = pipeline.run_artifact_paths("pilot", 5, "20260704T010203Z")

        self.assertEqual(paths["summary"].name, "pilot_5_20260704T010203Z.csv")
        self.assertEqual(
            paths["log"].name,
            "pilot_5_20260704T010203Z_run_log.jsonl",
        )
        self.assertEqual(
            paths["omission_samples"].name,
            "pilot_5_20260704T010203Z_omission_samples.csv",
        )
        self.assertEqual(
            paths["last_attempts"].name,
            "pilot_5_20260704T010203Z_last_attempts.csv",
        )
        self.assertEqual(
            paths["all_responses"].name,
            "pilot_5_20260704T010203Z_all_responses.csv",
        )

    def test_scale_paths_include_requested_n_and_timestamp(self):
        paths = pipeline.run_artifact_paths("scale", 50, "20260704T010203Z")

        self.assertEqual(paths["summary"].name, "scaled_50_20260704T010203Z.csv")
        self.assertEqual(
            paths["log"].name,
            "scaled_50_20260704T010203Z_run_log.jsonl",
        )
        self.assertEqual(
            paths["last_attempts"].name,
            "scaled_50_20260704T010203Z_last_attempts.csv",
        )
        self.assertEqual(paths["all_responses"], None)


if __name__ == "__main__":
    unittest.main()
