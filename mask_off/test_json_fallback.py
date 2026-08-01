"""Self-check: models without structured outputs get prompted JSON, not a 400.

Run: python -m mask_off.test_json_fallback
"""
from types import SimpleNamespace

from .llm import json_text_of, message_params


def _msg(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def demo():
    schema = {"type": "object", "properties": {}}
    kwargs = dict(
        effort="high",
        system="sys",
        user="usr",
        max_tokens=100,
        thinking=None,
        schema=schema,
    )

    supported = message_params(model="claude-opus-5", **kwargs)
    assert "format" in supported["output_config"]

    unsupported = message_params(model="claude-opus-4-7", **kwargs)
    assert "format" not in unsupported["output_config"], "opus-4-7 would 400"
    assert unsupported["output_config"]["effort"] == "high"

    assert json_text_of(_msg('{"a": 1}')) == '{"a": 1}'
    assert json_text_of(_msg('```json\n{"a": 1}\n```')) == '{"a": 1}'
    assert json_text_of(_msg('```\n{"a": 1}\n```')) == '{"a": 1}'
    # A fence inside the JSON must not truncate it (rsplit takes the last ```).
    assert json_text_of(_msg('```json\n{"a": "x ``` y"}\n```')) == '{"a": "x ``` y"}'

    print("ok")


if __name__ == "__main__":
    demo()
