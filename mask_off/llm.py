"""Thin OpenAI Chat Completions and Anthropic Message Batches helpers."""

import hashlib
import json
import re
import time

import anthropic
import openai
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from . import config

_client = None
_openai_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=1, timeout=config.TIMEOUT)
    return _client


def openai_client():
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.OpenAI(max_retries=1, timeout=config.TIMEOUT)
    return _openai_client


def text_of(response) -> str:
    """Return visible text from either provider response."""
    if hasattr(response, "choices"):
        return (response.choices[0].message.content or "").strip()
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
    if hasattr(usage, "prompt_tokens"):
        details = getattr(usage, "prompt_tokens_details", None)
        return {
            "input_tokens": usage.prompt_tokens or 0,
            "output_tokens": usage.completion_tokens or 0,
            "cache_creation_input_tokens": (
                getattr(details, "cache_write_tokens", 0) or 0
            ),
            "cache_read_input_tokens": getattr(details, "cached_tokens", 0) or 0,
        }
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
    if model.startswith("openai/"):
        api_model = model.removeprefix("openai/")
        if not api_model:
            raise ValueError("OpenAI model ID cannot be empty")
        cache_key = hashlib.sha256(
            f"{api_model}\0{system}".encode("utf-8")
        ).hexdigest()
        return {
            "model": model,
            "messages": [
                {"role": "developer", "content": system},
                {"role": "user", "content": user},
            ],
            "reasoning_effort": effort,
            "max_completion_tokens": max_tokens,
            "prompt_cache_key": cache_key,
            "prompt_cache_retention": "24h",
        }

    params = dict(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system,
                # 1h rather than 5m: a wave's generator, target, and reviewer
                # batches run minutes to hours apart, so a 5-minute entry never
                # survives to the next wave and the ~10K-token system prompt is
                # rewritten almost every iteration. The 1h write costs 2x base
                # instead of 1.25x, so it pays for itself after two reads.
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort},
    )
    if thinking is not None:
        params["thinking"] = thinking
    return params


def _buffer_batches(requests: list[dict]) -> list[list[dict]]:
    """Split requests before either Message Batch cap is crossed."""
    batches = []
    buffered = []
    buffered_bytes = len(b'{"requests":[]}')
    for request in requests:
        request_bytes = len(
            json.dumps(
                request,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if request_bytes + len(b'{"requests":[]}') > config.MAX_BATCH_BYTES:
            raise ValueError(f"request {request['custom_id']} exceeds the batch byte cap")
        if buffered and (
            len(buffered) >= config.MAX_BATCH_REQUESTS
            or buffered_bytes + request_bytes + 1 > config.MAX_BATCH_BYTES
        ):
            batches.append(buffered)
            buffered = []
            buffered_bytes = len(b'{"requests":[]}')
        buffered_bytes += request_bytes + (1 if buffered else 0)
        buffered.append(request)
    if buffered:
        batches.append(buffered)
    return batches


def batch_progress() -> Progress:
    """The standard live display. rich allows one at a time — callers that run several
    stages (the wave loop) create it once and pass it into each run_batch call."""
    return Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        transient=True,
    )


def _connection_retry(call, progress: Progress):
    """Wait out local network blips: the batch is already paid for server-side, so
    abandoning the run on a dropped connection loses money for nothing."""
    while True:
        try:
            return call()
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            progress.console.print(
                f"connection error, retrying in {config.BATCH_POLL_SECONDS}s: {exc}",
                markup=False,
                highlight=False,
            )
            time.sleep(config.BATCH_POLL_SECONDS)


def run_batch(requests: list[dict], label: str, progress: Progress | None = None) -> dict:
    """Run sequential OpenAI chats or capped Anthropic Message Batches.

    Returns {custom_id: response | None}, where None means the request errored,
    expired, or was canceled. Pass ``progress`` to nest this stage's bars under
    an existing live display.
    """
    if not requests:
        return {}
    models = [request.get("params", {}).get("model", "") for request in requests]
    providers = {
        "openai" if model.startswith("openai/") else "anthropic"
        for model in models
    }
    if len(providers) != 1:
        raise ValueError("one run_batch call cannot mix OpenAI and Anthropic")
    if "openai" in providers and any(model == "openai/" for model in models):
        raise ValueError("OpenAI model ID cannot be empty")
    if progress is None:
        with batch_progress() as progress:
            return run_batch(requests, label, progress)
    if "openai" in providers:
        task = progress.add_task(label, total=len(requests))
        completions = openai_client().chat.completions
        out = {}
        try:
            for request in requests:
                params = dict(request["params"])
                params["model"] = params["model"].removeprefix("openai/")
                try:
                    out[request["custom_id"]] = completions.create(**params)
                except openai.OpenAIError as exc:
                    progress.console.print(
                        f"{request['custom_id']}: {exc}",
                        markup=False,
                        highlight=False,
                    )
                    out[request["custom_id"]] = None
                finally:
                    progress.update(task, advance=1, refresh=True)
        finally:
            progress.remove_task(task)
        return out

    batches = client().messages.batches
    buffered_batches = _buffer_batches(requests)
    # submit every chunk first so they all process server-side concurrently
    submitted = [
        _connection_retry(
            lambda buffered=buffered: batches.create(requests=buffered), progress
        )
        for buffered in buffered_batches
    ]
    tasks = [
        progress.add_task(
            label if len(submitted) == 1 else f"{label} {index}/{len(submitted)}",
            total=len(buffered),
        )
        for index, buffered in enumerate(buffered_batches, start=1)
    ]
    try:
        for batch, task in zip(submitted, tasks):
            while True:
                status = _connection_retry(
                    lambda: batches.retrieve(batch.id), progress
                )
                counts = status.request_counts
                progress.update(
                    task,
                    completed=counts.succeeded
                    + counts.errored
                    + counts.canceled
                    + counts.expired,
                    refresh=True,
                )
                if status.processing_status == "ended":
                    break
                # ponytail: fixed polling; add backoff only if runs become large
                time.sleep(config.BATCH_POLL_SECONDS)
    except KeyboardInterrupt:
        for batch in submitted:
            try:
                batches.cancel(batch.id)
            except Exception:  # noqa: BLE001 - already-ended chunks can't be canceled
                pass
        raise
    finally:
        for task in tasks:
            progress.remove_task(task)
    out = {}
    for batch in submitted:
        results = _connection_retry(
            lambda batch=batch: [
                (item.custom_id, item.result) for item in batches.results(batch.id)
            ],
            progress,
        )
        for custom_id, res in results:
            out[custom_id] = res.message if res.type == "succeeded" else None
    return out
