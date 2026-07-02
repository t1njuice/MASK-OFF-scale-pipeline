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
        _client = anthropic.Anthropic(max_retries=5)
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


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end + 1]
    return t


def _create(model, effort, system, user, max_tokens, thinking):
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort},
    )
    if thinking is not None:
        kwargs["thinking"] = thinking
    return client().messages.create(**kwargs)


def call_text(model, effort, system, user, max_tokens, thinking):
    resp = _create(model, effort, system, user, max_tokens, thinking)
    return text_of(resp), resp.model, reasoning_summary_of(resp)


def call_json(model, effort, system, user, pydantic_model, max_tokens, retries=2):
    last = None
    u = user
    for _ in range(retries + 1):
        resp = _create(model, effort, system, u, max_tokens, config.REASONING_THINKING)
        raw = text_of(resp)
        try:
            return pydantic_model.model_validate_json(_extract_json(raw)), resp.model
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
