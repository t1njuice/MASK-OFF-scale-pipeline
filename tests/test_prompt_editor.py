import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from mask_off import schemas


PROMPT = """# Prompt

Keep stable instructions.

## Learned adjustments

<!-- prompt-editor:start -->
- Old lesson
<!-- prompt-editor:end -->

## Output

Return JSON.
"""


class PromptEditorTest(unittest.TestCase):
    def test_replaces_managed_section_and_keeps_prompt_contract(self):
        from mask_off.prompt_editor import replace_lessons

        updated = replace_lessons(PROMPT, ["New lesson", "Another lesson"])

        self.assertIn("- New lesson", updated)
        self.assertIn("- Another lesson", updated)
        self.assertNotIn("- Old lesson", updated)
        self.assertIn("<!-- prompt-editor:start -->", updated)
        self.assertIn("<!-- prompt-editor:end -->", updated)
        self.assertIn("## Output", updated)

    def test_rejects_more_than_eight_lessons(self):
        from mask_off.prompt_editor import validate_lessons

        with self.assertRaisesRegex(ValueError, "at most 8"):
            validate_lessons([f"Lesson {i}" for i in range(9)])

    def test_rejects_schema_or_output_format_edits(self):
        from mask_off.prompt_editor import validate_lessons

        with self.assertRaisesRegex(ValueError, "format"):
            validate_lessons(["Change the JSON schema to include reviewer feedback"])

    def test_repairs_prompt_missing_lesson_markers(self):
        from mask_off.prompt_editor import replace_lessons

        prompt = "# Prompt\n\n## Revision mode\n\nKeep the same T.\n"

        updated = replace_lessons(prompt, ["Keep the ask narrow"])

        self.assertIn("## Learned adjustments", updated)
        self.assertIn("<!-- prompt-editor:start -->", updated)
        self.assertIn("- Keep the ask narrow", updated)
        self.assertIn("## Revision mode", updated)

    def test_partial_lesson_markers_fail_loudly(self):
        from mask_off.prompt_editor import replace_lessons

        prompt = "# Prompt\n\n<!-- prompt-editor:start -->\n- Old lesson\n"

        with self.assertRaisesRegex(ValueError, "partial"):
            replace_lessons(prompt, ["Keep the ask narrow"])

    def test_retries_once_then_discards_invalid_editor_output(self):
        from mask_off import prompt_editor

        responses = [
            schemas.SeedLearningUpdate(
                seed_summary="bad",
                evidence="strong",
                proposed_lessons=["Rewrite the JSON output format"],
            ),
            schemas.SeedLearningUpdate(
                seed_summary="bad",
                evidence="strong",
                proposed_lessons=["Also change the schema"],
            ),
        ]

        def fake_call_json(*_args, **_kwargs):
            return responses.pop(0), "claude-fable-5", {"input_tokens": 1}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generator_system.md"
            path.write_text(PROMPT, encoding="utf-8")

            with patch.object(prompt_editor, "call_json", fake_call_json):
                result = prompt_editor.edit_generator_prompt(
                    trigger="rejected",
                    signals=["feedback + metrics"],
                    prompt_path=path,
                )

            self.assertFalse(result["applied"])
            self.assertIn("format", result["error"])
            self.assertEqual(path.read_text(encoding="utf-8"), PROMPT)
            self.assertEqual(len(responses), 0)

    def test_strong_learning_promotes_lesson(self):
        from mask_off import prompt_editor

        def fake_call_json(*_args, **_kwargs):
            return (
                schemas.SeedLearningUpdate(
                    seed_summary="Moving T farther helped.",
                    evidence="strong",
                    proposed_lessons=["Keep the ask narrow"],
                ),
                "claude-fable-5",
                {"input_tokens": 10, "cache_read_input_tokens": 5},
            )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generator_system.md"
            pool_path = Path(tmp) / "lesson_pool.json"
            path.write_text(PROMPT, encoding="utf-8")

            with patch.object(prompt_editor, "call_json", fake_call_json):
                result = prompt_editor.edit_generator_prompt(
                    trigger="rejected",
                    signals=["feedback + metrics"],
                    prompt_path=path,
                    pool_path=pool_path,
                )

            self.assertTrue(result["applied"])
            self.assertIn("- Keep the ask narrow", path.read_text(encoding="utf-8"))
            self.assertEqual(result["usage"]["input_tokens"], 10)
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            item = next(
                lesson
                for lesson in pool["lessons"]
                if lesson["text"] == "Keep the ask narrow"
            )
            self.assertEqual(item["support"], 1)
            self.assertTrue(item["promoted"])

    def test_weak_learning_updates_pool_without_prompt_change(self):
        from mask_off import prompt_editor

        def fake_call_json(*_args, **_kwargs):
            return (
                schemas.SeedLearningUpdate(
                    seed_summary="One weak signal.",
                    evidence="weak",
                    proposed_lessons=["Use dull operational wording"],
                ),
                "claude-fable-5",
                {},
            )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generator_system.md"
            pool_path = Path(tmp) / "lesson_pool.json"
            path.write_text(PROMPT, encoding="utf-8")

            with patch.object(prompt_editor, "call_json", fake_call_json):
                result = prompt_editor.edit_generator_prompt(
                    trigger="seed_end",
                    signals=["feedback + metrics"],
                    prompt_path=path,
                    pool_path=pool_path,
                )

            self.assertFalse(result["applied"])
            self.assertEqual(path.read_text(encoding="utf-8"), PROMPT)
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            item = next(
                lesson
                for lesson in pool["lessons"]
                if lesson["text"] == "Use dull operational wording"
            )
            self.assertFalse(item["promoted"])

    def test_repeated_weak_learning_promotes_lesson(self):
        from mask_off import prompt_editor

        updates = [
            schemas.SeedLearningUpdate(
                seed_summary="First weak signal.",
                evidence="weak",
                proposed_lessons=["Use dull operational wording"],
            ),
            schemas.SeedLearningUpdate(
                seed_summary="Second weak signal.",
                evidence="weak",
                proposed_lessons=["Use dull operational wording"],
            ),
        ]

        def fake_call_json(*_args, **_kwargs):
            return updates.pop(0), "claude-fable-5", {}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generator_system.md"
            pool_path = Path(tmp) / "lesson_pool.json"
            path.write_text(PROMPT, encoding="utf-8")

            with patch.object(prompt_editor, "call_json", fake_call_json):
                first = prompt_editor.edit_generator_prompt(
                    trigger="seed_end",
                    signals=["feedback + metrics"],
                    prompt_path=path,
                    pool_path=pool_path,
                )
                second = prompt_editor.edit_generator_prompt(
                    trigger="seed_end",
                    signals=["feedback + metrics"],
                    prompt_path=path,
                    pool_path=pool_path,
                )

            self.assertFalse(first["applied"])
            self.assertTrue(second["applied"])
            self.assertIn(
                "- Use dull operational wording",
                path.read_text(encoding="utf-8"),
            )

    def test_prompt_editor_prompt_names_short_lesson_cap(self):
        from mask_off import config

        prompt = (config.PROMPTS_DIR / "prompt_editor_system.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("180", prompt)


class GeneratorReloadTest(unittest.TestCase):
    def test_generator_system_reloads_from_disk_each_call(self):
        from mask_off import generator

        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = Path(tmp) / "generator_system.md"
            prompt_path.write_text("first", encoding="utf-8")

            with patch.object(generator.config, "PROMPTS_DIR", Path(tmp)):
                self.assertEqual(generator._system(), "first")
                prompt_path.write_text("second", encoding="utf-8")
                self.assertEqual(generator._system(), "second")


if __name__ == "__main__":
    unittest.main()
