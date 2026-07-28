import unittest
from types import SimpleNamespace

from mask_off.generator import build_gen_request
from mask_off.llm import message_params, text_of, usage_summary_of


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


if __name__ == "__main__":
    unittest.main()
