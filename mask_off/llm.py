"""Thin Anthropic Message Batches API helpers."""

import re
import time

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


def message_params(model, effort, system, user, max_tokens, thinking) -> dict:
    params = dict(
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
        params["thinking"] = thinking
    return params


def run_batch(requests: list[dict]) -> dict:
    """Submit one Message Batches job and block until it ends.

    Requests use Anthropic's native ``{custom_id, params}`` shape.
    Returns {custom_id: anthropic Message | None}, where None means the request errored,
    expired, or was canceled. Half price vs. per-message calls; the shared system prompt
    across a stage's requests also earns prompt-cache hits.
    """
    if not requests:
        return {}
    batch = client().messages.batches.create(requests=requests)
    while client().messages.batches.retrieve(batch.id).processing_status != "ended":
        # ponytail: fixed poll interval; add backoff only if runs get large enough to matter
        time.sleep(config.BATCH_POLL_SECONDS)
    out = {}
    for item in client().messages.batches.results(batch.id):
        res = item.result
        out[item.custom_id] = res.message if res.type == "succeeded" else None
    return out
