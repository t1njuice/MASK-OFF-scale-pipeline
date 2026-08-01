"""Thin Anthropic Message Batches helpers."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

import anthropic
import httpx
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


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=1, timeout=config.TIMEOUT)
    return _client


def text_of(response) -> str:
    return "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ).strip()


# Models that accept output_config.format. Everything else (opus-4-7, opus-4-6)
# 400s on it and has to be prompted into JSON instead — see message_params.
STRUCTURED_OUTPUT_MODELS = frozenset(
    {
        "claude-fable-5",
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "claude-opus-4-5",
        "claude-opus-4-1",
    }
)


def json_text_of(response) -> str:
    """Response text with a markdown fence stripped, if the model added one.

    Only needed on the no-schema path: with output_config.format the response is
    guaranteed bare JSON, but a prompted model often wraps it in ```json.
    """
    text = text_of(response)
    if not text.startswith("```"):
        return text
    body = text[3:].rsplit("```", 1)[0]
    _, _, body = body.partition("\n")  # drop the language tag line
    return body.strip()


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


def _attach(obj, name: str, value):
    try:
        object.__setattr__(obj, name, value)
    except Exception:  # noqa: BLE001 - side-channel metadata is best-effort
        pass
    return obj


def attach_usage(obj, usage: dict):
    return _attach(obj, "_llm_usage", usage)


def attach_reasoning(obj, summary: str):
    """Carry a parsed object's own thinking summary alongside it."""
    return _attach(obj, "_llm_reasoning", summary)


def strict_schema(model) -> dict:
    """A Pydantic model's JSON Schema, tightened to what structured outputs needs.

    The API requires every object closed (`additionalProperties: false`) and every
    property listed in `required`. Pydantic emits neither: it omits defaulted
    fields from `required`, which would let the model drop them again — the exact
    failure the defaults in schemas.py were added to survive.
    """

    def tighten(node):
        if isinstance(node, dict):
            if "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for item in node:
                tighten(item)
        return node

    return tighten(model.model_json_schema())


def message_params(
    model, effort, system, user, max_tokens, thinking, schema=None
) -> dict:
    # `format` constrains the response to valid JSON matching `schema`. Models
    # outside STRUCTURED_OUTPUT_MODELS reject it, so they get plain text and the
    # caller parses with json_text_of — the prompts already spell out the shape.
    output_config = {"effort": effort}
    if schema is not None and model in STRUCTURED_OUTPUT_MODELS:
        output_config["format"] = {"type": "json_schema", "schema": schema}
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
        output_config=output_config,
    )
    if thinking is not None:
        params["thinking"] = thinking
    return params


# --- OpenRouter (non-Anthropic targets, e.g. moonshotai/kimi-k3) ----------
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def is_anthropic_model(model: str) -> bool:
    return model.startswith("claude")


def _shim_message(data: dict):
    """Wrap an OpenAI-style chat completion so text_of / reasoning_summary_of /
    usage_summary_of read it exactly like an Anthropic message."""
    choice = data["choices"][0]
    msg = choice["message"]
    content = []
    # ponytail: reads message.reasoning only; add reasoning_details if a model needs it
    reasoning = (msg.get("reasoning") or "").strip()
    if reasoning:
        content.append(SimpleNamespace(type="thinking", thinking=reasoning))
    content.append(SimpleNamespace(type="text", text=msg.get("content") or ""))
    usage = data.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return SimpleNamespace(
        content=content,
        usage=SimpleNamespace(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cache_creation_input_tokens=0,
            cache_read_input_tokens=details.get("cached_tokens", 0) or 0,
        ),
        stop_reason=choice.get("finish_reason"),
    )


def _openrouter_call(params: dict):
    """One synchronous chat completion from Anthropic-shaped `params`."""
    body = {
        "model": params["model"],
        "max_tokens": params["max_tokens"],
        "messages": [
            # Anthropic system blocks are already OpenRouter content parts, so
            # cache_control passes through: explicit-caching providers (Anthropic,
            # Qwen) use the breakpoint, automatic ones (Moonshot/kimi) ignore it
            # and cache on their own.
            {"role": "system", "content": params["system"]},
            *params["messages"],
        ],
    }
    if params.get("thinking"):
        body["reasoning"] = {"enabled": True}
    for attempt in range(3):
        try:
            resp = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"
                },
                json=body,
                # thinking models run minutes; config.TIMEOUT guards Anthropic only
                timeout=600,
            )
            resp.raise_for_status()
            return _shim_message(resp.json())
        except (httpx.HTTPError, KeyError, IndexError):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def _run_openrouter(requests: list[dict], label: str, progress: Progress) -> dict:
    """Threaded stand-in for the Batches API: {custom_id: message | None}."""
    task = progress.add_task(f"{label} (openrouter)", total=len(requests))
    out = {}
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(_openrouter_call, r["params"]): r["custom_id"]
                for r in requests
            }
            for future in as_completed(futures):
                cid = futures[future]
                try:
                    out[cid] = future.result()
                except Exception as exc:  # noqa: BLE001 - None = errored sample, same as batch
                    progress.console.print(
                        f"openrouter {cid} failed: {exc}", markup=False, highlight=False
                    )
                    out[cid] = None
                progress.advance(task)
    finally:
        progress.remove_task(task)
    return out


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
    """Run capped Anthropic Message Batches.

    Returns {custom_id: response | None}, where None means the request errored,
    expired, or was canceled. Pass ``progress`` to nest this stage's bars under
    an existing live display.
    """
    if not requests:
        return {}
    if progress is None:
        with batch_progress() as progress:
            return run_batch(requests, label, progress)

    external = [r for r in requests if not is_anthropic_model(r["params"]["model"])]
    if external:
        native = [r for r in requests if is_anthropic_model(r["params"]["model"])]
        # ponytail: sequential; overlap the pool with the batch poll if wall-clock matters
        out = _run_openrouter(external, label, progress)
        out.update(run_batch(native, label, progress))
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
