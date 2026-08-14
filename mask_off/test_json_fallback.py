"""Self-check: models without structured outputs get prompted JSON, not a 400.

Run: python -m mask_off.test_json_fallback
"""
import json
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


def test_validity_review_decodes_kimi_map_serialization():
    """kimi-k3's `constraints` arrives double-encoded in a type-tagged Map
    shape (22% of its vote payloads in output/run20). The vote is complete and
    already paid for, so it must parse rather than cost a resubmission."""
    from .schemas import ValidityConstraints, ValidityReview

    names = list(ValidityConstraints.model_fields)
    entries = [
        [
            name,
            {
                "completionState": "complete",
                "type": "Object",
                "entries": [
                    ["passed", {"type": "Boolean", "value": True}],
                    ["note", {"type": "String", "value": f"{name} ok"}],
                ],
            },
        ]
        for name in names
    ]
    payload = json.dumps(
        {
            "constraints": json.dumps(
                {"completionState": "complete", "type": "Object", "entries": entries}
            ),
            "seed_defect": False,
            "verdict": "accept",
            "feedback": "Chain: ...",
        }
    )
    review = ValidityReview.model_validate_json(payload)
    assert review.verdict == "accept"
    assert len(ValidityConstraints.model_fields) == len(names)
    assert review.constraints.system_prompt_form.passed is True
    assert review.constraints.system_prompt_form.note == "system_prompt_form ok"


def test_validity_review_still_accepts_a_plain_object():
    """The well-formed shape every other reviewer emits must be untouched."""
    from .schemas import ValidityConstraints, ValidityReview

    review = ValidityReview.model_validate(
        {
            "constraints": {
                name: {"passed": False, "note": "n"}
                for name in ValidityConstraints.model_fields
            },
            "verdict": "revise",
            "feedback": "f",
        }
    )
    assert review.constraints.system_prompt_form.passed is False


def test_validity_review_rejects_unparseable_constraints():
    """A genuine parse failure must still fail, not be silently swallowed."""
    import pytest
    from .schemas import ValidityReview

    with pytest.raises(Exception):
        ValidityReview.model_validate(
            {"constraints": "not json at all", "verdict": "accept", "feedback": "f"}
        )
