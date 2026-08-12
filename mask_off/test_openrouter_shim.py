"""The OpenRouter shim must read like an Anthropic message to the existing helpers."""

import json
from unittest.mock import patch

import pytest

from mask_off.llm import (
    _openrouter_call,
    _shim_message,
    reasoning_summary_of,
    text_of,
    usage_summary_of,
)


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
    # convention U (ADR-0002 §7): input_tokens EXCLUDES the 7 cached tokens —
    # the old passthrough double-counted them in usage_cost
    assert usage_summary_of(m) == {
        "model": None,
        "route": None,
        "input_tokens": 3,
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


PARAMS = {"model": "moonshotai/kimi-k3", "max_tokens": 10, "system": "s", "messages": []}
GOOD = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


class _Resp:
    """Minimal httpx.Response stand-in with a raw body."""

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.text)


def test_openrouter_retries_truncated_body(monkeypatch):
    # OpenRouter keep-alive padding with the JSON cut off — the exact pilot failure.
    monkeypatch.setattr("mask_off.llm.time.sleep", lambda _: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    bodies = ["\n" * 176, "\n" * 176, json.dumps(GOOD)]
    with patch("mask_off.llm.httpx.post", side_effect=[_Resp(b) for b in bodies]):
        assert text_of(_openrouter_call(PARAMS)) == "ok"


def test_openrouter_reports_body_after_exhausted_retries(monkeypatch):
    monkeypatch.setattr("mask_off.llm.time.sleep", lambda _: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    with patch("mask_off.llm.httpx.post", return_value=_Resp("\n" * 176)):
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            _openrouter_call(PARAMS)
