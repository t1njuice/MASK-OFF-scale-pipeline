"""Thin Anthropic Messages API wrappers.

Two call styles:
  * call_text  -> plain generation (used by the TARGET; returns text + model id + reasoning summary)
  * call_json  -> instructed-JSON generation validated against a pydantic model
                  (used by GENERATOR and REVIEWER)

We deliberately use instructed-JSON rather than the structured-outputs helper so
that the effort parameter (output_config.effort) composes cleanly with our schema
across SDK versions. Frontier models are highly reliable at "return only JSON",
and a tolerant extractor + one retry closes the gap.
"""

import re

import anthropic

from . import config

_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=1, timeout=config.TIMEOUT)
    return _client


def text_of(response) -> str:
    """Join all text blocks (skips empty adaptive-thinking blocks)."""
    return "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ).strip()


def reasoning_summary_of(response) -> str:
    """Join returned thinking summaries from Anthropic thinking blocks."""
    chunks = []
    for block in response.content:
        if getattr(block, "type", None) != "thinking":
            continue
        text = (getattr(block, "thinking", "") or "").strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks)


def usage_summary_of(response) -> dict:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(
            usage,
            "cache_creation_input_tokens",
            0,
        )
        or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def attach_usage(obj, usage: dict):
    try:
        object.__setattr__(obj, "_llm_usage", usage)
    except Exception:  # noqa: BLE001 - usage is best-effort metadata
        pass
    return obj


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    return t


def _create(model, effort, system, user, max_tokens, thinking):
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral", "ttl": "5m"},
            }
        ],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort},
    )
    if thinking is not None:
        kwargs["thinking"] = thinking
    with client().messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def call_text(model, effort, system, user, max_tokens, thinking):
    resp = _create(model, effort, system, user, max_tokens, thinking)
    return (
        text_of(resp),
        resp.model,
        reasoning_summary_of(resp),
        usage_summary_of(resp),
    )


def call_json(model, effort, system, user, pydantic_model, max_tokens, retries=2):
    last = None
    u = user
    for _ in range(retries + 1):
        resp = _create(model, effort, system, u, max_tokens, config.REASONING_THINKING)
        raw = text_of(resp)
        try:
            return (
                pydantic_model.model_validate_json(_extract_json(raw)),
                resp.model,
                usage_summary_of(resp),
            )
        except Exception as e:  # noqa: BLE001 - validation/parse errors
            last = e
            u = (
                user
                + "\n\nIMPORTANT: your previous reply was not valid JSON. Respond with "
                "ONLY a single JSON object matching the schema — no prose, no markdown, "
                "no code fences."
            )
    raise RuntimeError(
        f"{model} did not return valid JSON after {retries + 1} attempts: {last}"
    )
