"""The OpenRouter shim must read like an Anthropic message to the existing helpers."""

from mask_off.llm import _shim_message, reasoning_summary_of, text_of, usage_summary_of


def test_shim_message():
    data = {
        "choices": [
            {
                "message": {"content": "hello", "reasoning": "let me think"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 7},
        },
    }
    m = _shim_message(data)
    assert text_of(m) == "hello"
    assert reasoning_summary_of(m) == "let me think"
    assert usage_summary_of(m) == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 7,
    }
    assert m.stop_reason == "stop"


def test_shim_no_reasoning():
    data = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
    m = _shim_message(data)
    assert text_of(m) == "hi"
    assert reasoning_summary_of(m) == ""
