import unittest
from types import SimpleNamespace
from unittest.mock import patch

import openai
from rich.progress import Progress

from mask_off.generator import build_gen_request
from mask_off.llm import message_params, run_batch, text_of, usage_summary_of


def openai_response(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(
            prompt_tokens=2006,
            completion_tokens=300,
            prompt_tokens_details=SimpleNamespace(
                cached_tokens=1920,
                cache_write_tokens=64,
            ),
        ),
    )


class FakeOpenAICompletions:
    def __init__(self, outcomes, events):
        self.outcomes = list(outcomes)
        self.events = events

    def create(self, **params):
        self.events.append(("openai", params["messages"][-1]["content"]))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeAnthropicBatches:
    def __init__(self, events, message):
        self.events = events
        self.message = message
        self.requests = []

    def create(self, requests):
        self.events.append(("anthropic", "create"))
        self.requests = requests
        return SimpleNamespace(id="batch-1")

    def retrieve(self, _batch_id):
        return SimpleNamespace(
            processing_status="ended",
            request_counts=SimpleNamespace(
                succeeded=len(self.requests),
                errored=0,
                canceled=0,
                expired=0,
            ),
        )

    def results(self, _batch_id):
        return [
            SimpleNamespace(
                custom_id=request["custom_id"],
                result=SimpleNamespace(type="succeeded", message=self.message),
            )
            for request in self.requests
        ]


def openai_request(custom_id: str, user: str):
    return {
        "custom_id": custom_id,
        "params": message_params(
            "openai/gpt-5.5", "high", "stable system", user, 256, None
        ),
    }


def anthropic_request(custom_id: str):
    return {
        "custom_id": custom_id,
        "params": message_params(
            "claude-opus-4-8", "high", "system", "review", 256, None
        ),
    }


class OpenAIShapeTests(unittest.TestCase):
    def test_openai_params_use_chat_and_prompt_cache(self):
        params = message_params(
            "openai/gpt-5.5",
            "high",
            "stable system",
            "changing user",
            4096,
            {"type": "adaptive"},
        )
        same = message_params(
            "openai/gpt-5.5",
            "high",
            "stable system",
            "another user",
            4096,
            None,
        )
        changed = message_params(
            "openai/gpt-5.5",
            "high",
            "changed system",
            "changing user",
            4096,
            None,
        )

        self.assertEqual(params["model"], "openai/gpt-5.5")
        self.assertEqual(
            params["messages"],
            [
                {"role": "developer", "content": "stable system"},
                {"role": "user", "content": "changing user"},
            ],
        )
        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["max_completion_tokens"], 4096)
        self.assertEqual(params["prompt_cache_retention"], "24h")
        self.assertEqual(params["prompt_cache_key"], same["prompt_cache_key"])
        self.assertNotEqual(params["prompt_cache_key"], changed["prompt_cache_key"])
        self.assertNotIn("thinking", params)

    def test_openai_text_and_usage_map_to_existing_contract(self):
        response = openai_response('{"ok": true}')

        self.assertEqual(text_of(response), '{"ok": true}')
        self.assertEqual(
            usage_summary_of(response),
            {
                "input_tokens": 2006,
                "output_tokens": 300,
                "cache_creation_input_tokens": 64,
                "cache_read_input_tokens": 1920,
            },
        )

    def test_anthropic_params_remain_unchanged(self):
        params = message_params(
            "claude-opus-4-8",
            "high",
            "system",
            "user",
            4096,
            {"type": "adaptive"},
        )

        self.assertEqual(params["model"], "claude-opus-4-8")
        self.assertEqual(params["system"][0]["text"], "system")
        self.assertEqual(
            params["system"][0]["cache_control"],
            {"type": "ephemeral", "ttl": "1h"},
        )
        self.assertEqual(params["messages"], [{"role": "user", "content": "user"}])
        self.assertEqual(params["output_config"], {"effort": "high"})

    def test_generator_request_uses_openai_provider(self):
        request = build_gen_request("seed-1", "ground truth", [])

        self.assertEqual(request["params"]["model"], "openai/gpt-5.5")
        self.assertEqual(request["params"]["messages"][0]["role"], "developer")

    def test_empty_openai_model_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            message_params("openai/", "high", "system", "user", 256, None)


class TransportHandoffTests(unittest.TestCase):
    def test_openai_is_sequential_before_anthropic_reviewer_batch(self):
        events = []
        first = openai_response("first")
        second = openai_response("second")
        reviewer_message = object()
        completions = FakeOpenAICompletions([first, second], events)
        batches = FakeAnthropicBatches(events, reviewer_message)
        fake_openai = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        fake_anthropic = SimpleNamespace(
            messages=SimpleNamespace(batches=batches)
        )

        with (
            patch("mask_off.llm.openai_client", return_value=fake_openai),
            patch("mask_off.llm.client", return_value=fake_anthropic),
            Progress(disable=True) as progress,
        ):
            generated = run_batch(
                [openai_request("gen-1", "first"), openai_request("gen-2", "second")],
                "Generator",
                progress,
            )
            reviewed = run_batch(
                [anthropic_request("review-1")],
                "Reviewer",
                progress,
            )

        self.assertEqual(
            events,
            [("openai", "first"), ("openai", "second"), ("anthropic", "create")],
        )
        self.assertIs(generated["gen-1"], first)
        self.assertIs(generated["gen-2"], second)
        self.assertIs(reviewed["review-1"], reviewer_message)

    def test_one_openai_failure_does_not_block_success_or_reviewer_batch(self):
        events = []
        success = openai_response("success")
        reviewer_message = object()
        completions = FakeOpenAICompletions(
            [openai.OpenAIError("boom"), success],
            events,
        )
        batches = FakeAnthropicBatches(events, reviewer_message)
        fake_openai = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        fake_anthropic = SimpleNamespace(
            messages=SimpleNamespace(batches=batches)
        )

        with (
            patch("mask_off.llm.openai_client", return_value=fake_openai),
            patch("mask_off.llm.client", return_value=fake_anthropic),
            Progress(disable=True) as progress,
        ):
            generated = run_batch(
                [openai_request("gen-1", "bad"), openai_request("gen-2", "good")],
                "Generator",
                progress,
            )
            reviewed = run_batch(
                [anthropic_request("review-1")],
                "Reviewer",
                progress,
            )

        self.assertIsNone(generated["gen-1"])
        self.assertIs(generated["gen-2"], success)
        self.assertIs(reviewed["review-1"], reviewer_message)
        self.assertEqual(events[-1], ("anthropic", "create"))

    def test_mixed_providers_are_rejected_before_any_call(self):
        fake_openai = SimpleNamespace(
            chat=SimpleNamespace(
                completions=FakeOpenAICompletions([], [])
            )
        )

        with (
            patch("mask_off.llm.openai_client", return_value=fake_openai),
            Progress(disable=True) as progress,
            self.assertRaisesRegex(ValueError, "cannot mix"),
        ):
            run_batch(
                [
                    openai_request("gen-1", "user"),
                    anthropic_request("review-1"),
                ],
                "Mixed",
                progress,
            )


if __name__ == "__main__":
    unittest.main()
