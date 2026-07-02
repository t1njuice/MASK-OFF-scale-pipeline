import json
import re
import unittest

from mask_off import config
from mask_off.schemas import Candidate


class GeneratorPromptContractTest(unittest.TestCase):
    def test_output_example_matches_candidate_fields(self):
        prompt = (config.PROMPTS_DIR / "generator_system.md").read_text(
            encoding="utf-8"
        )
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", prompt, re.S)
        self.assertIsNotNone(match)

        example = json.loads(match.group(1))

        self.assertEqual(list(example), list(Candidate.model_fields))
        self.assertNotIn("axes", example)


if __name__ == "__main__":
    unittest.main()
