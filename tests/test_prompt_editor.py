import tempfile
import unittest
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

    def test_retries_once_then_discards_invalid_editor_output(self):
        from mask_off import prompt_editor

        responses = [
            schemas.PromptLessons(lessons=["Rewrite the JSON output format"]),
            schemas.PromptLessons(lessons=["Also change the schema"]),
        ]

        def fake_call_json(*_args, **_kwargs):
            return responses.pop(0), "claude-fable-5"

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

    def test_applies_valid_editor_output(self):
        from mask_off import prompt_editor

        def fake_call_json(*_args, **_kwargs):
            return schemas.PromptLessons(lessons=["Keep the ask narrow"]), "claude-fable-5"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generator_system.md"
            path.write_text(PROMPT, encoding="utf-8")

            with patch.object(prompt_editor, "call_json", fake_call_json):
                result = prompt_editor.edit_generator_prompt(
                    trigger="rejected",
                    signals=["feedback + metrics"],
                    prompt_path=path,
                )

            self.assertTrue(result["applied"])
            self.assertIn("- Keep the ask narrow", path.read_text(encoding="utf-8"))


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
