import unittest
from unittest.mock import patch

from mask_off import llm


class LlmClientTest(unittest.TestCase):
    def tearDown(self):
        llm._client = None

    def test_anthropic_client_has_bounded_waits(self):
        llm._client = None

        with patch.object(llm.anthropic, "Anthropic") as anthropic_client:
            llm.client()

        anthropic_client.assert_called_once_with(max_retries=1, timeout=60.0)


if __name__ == "__main__":
    unittest.main()
