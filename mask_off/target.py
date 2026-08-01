"""TARGET agent: the model(s) under test."""

from . import config
from .llm import message_params, reasoning_summary_of, text_of, usage_summary_of


def short_name(model: str) -> str:
    if "opus" in model:
        return "opus"
    elif "fable" in model:
        return "fable"
    elif "kimi" in model:
        return "kimi"
    else:
        return "sonnet"


# short name -> requested model id; shorts are unique across TARGET_MODELS.
_MODEL_BY_SHORT = {short_name(m): m for m in config.TARGET_MODELS}


def _labels() -> list[tuple[str, str]]:
    """(label, model) for every sample, e.g. ("opus#1", "claude-opus-4-8")."""
    return [
        (f"{short_name(model)}#{i + 1}", model)
        for model in config.TARGET_MODELS
        for i in range(config.K_SAMPLES)
    ]


def build_target_requests(cand_id: str, system_prompt: str, user_email: str) -> list[dict]:
    """Build API-safe batch requests for every target sample."""
    return [
        {
            "custom_id": f"{cand_id}__{label.replace('#', '_')}",
            "params": message_params(
                model,
                config.TARGET_EFFORT,
                system_prompt,
                user_email,
                config.TARGET_MAX_TOKENS,
                config.TARGET_THINKING,
            ),
        }
        for label, model in _labels()
    ]


def regroup_targets(cand_id: str, messages: dict) -> dict:
    """Group one candidate's batch results by sample label.

    A None message (errored/expired sample) becomes an empty response, which
    compute_rates already skips.
    """
    prefix = f"{cand_id}__"
    results = {}
    for custom_id, message in messages.items():
        if not custom_id.startswith(prefix):
            continue
        short, sample = custom_id[len(prefix):].rsplit("_", 1)
        label = f"{short}#{sample}"
        model = _MODEL_BY_SHORT[short]
        if message is None:
            results[label] = {
                "model": model,
                "text": "",
                "reasoning": {"summary": ""},
                "usage": {},
            }
        else:
            results[label] = {
                "model": model,
                "text": text_of(message),
                "reasoning": {"summary": reasoning_summary_of(message)},
                "usage": usage_summary_of(message),
            }
    return results
