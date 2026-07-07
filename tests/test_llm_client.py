import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mask_off import llm


class LlmClientTest(unittest.TestCase):
    def tearDown(self):
        llm._client = None

    def test_anthropic_client_has_bounded_waits(self):
        llm._client = None

        with patch.object(llm.anthropic, "Anthropic") as anthropic_client:
            llm.client()

        anthropic_client.assert_called_once_with(max_retries=1, timeout=60.0)

    def test_create_uses_streaming_final_message(self):
        final_message = SimpleNamespace(model="claude-fable-5", content=[])

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def get_final_message(self):
                return final_message

        messages = SimpleNamespace(
            stream=MagicMock(return_value=Stream()),
            create=MagicMock(),
        )

        with patch.object(llm, "client", return_value=SimpleNamespace(messages=messages)):
            response = llm._create(
                "claude-fable-5",
                "xhigh",
                "System",
                "User",
                6000,
                {"type": "adaptive"},
            )

        self.assertIs(response, final_message)
        messages.create.assert_not_called()
        messages.stream.assert_called_once_with(
            model="claude-fable-5",
            max_tokens=6000,
            system=[
                {
                    "type": "text",
                    "text": "System",
                    "cache_control": {"type": "ephemeral", "ttl": "5m"},
                }
            ],
            messages=[{"role": "user", "content": "User"}],
            output_config={"effort": "xhigh"},
            thinking={"type": "adaptive"},
        )

    def test_usage_summary_includes_cache_tokens(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_creation_input_tokens=7,
                cache_read_input_tokens=3,
            )
        )

        self.assertEqual(
            llm.usage_summary_of(response),
            {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 7,
                "cache_read_input_tokens": 3,
            },
        )


if __name__ == "__main__":
    unittest.main()
