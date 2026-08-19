import marimo

__generated_with = "0.23.15"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import json
    import os
    from pathlib import Path

    import marimo as mo

    from openrouter import OpenRouterClient

    ENV_FILE = Path(__file__).resolve().parent / "mask" / "mask" / ".env"
    return ENV_FILE, OpenRouterClient, json, mo, os


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # OpenRouter playground

    Set a system prompt, pick a model, chat, and read the reasoning trace and the
    response metadata of every assistant turn.
    """)
    return


@app.cell(hide_code=True)
def _(ENV_FILE, os):
    def read_env_key(name):
        env_key = os.environ.get(name)
        if env_key:
            return env_key
        if not ENV_FILE.exists():
            return None
        for line in ENV_FILE.read_text().splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
        return None

    api_key = read_env_key("OPENROUTER_API_KEY")
    anthropic_key = read_env_key("ANTHROPIC_API_KEY")
    return anthropic_key, api_key


@app.function(hide_code=True)
def jsonable(value):
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return str(value)


@app.function(hide_code=True)
def code_block(text):
    import html

    return (
        '<pre style="white-space: pre-wrap; overflow-wrap: anywhere; '
        'max-width: 100%; background-color: #e5e7eb; color: #1f2937;">'
        f"<code>{html.escape(text)}</code></pre>"
    )


@app.function(hide_code=True)
def chat_message_to_dict(message):
    role = getattr(message, "role", "user") or "user"
    content = getattr(message, "content", None)
    if content is None:
        parts = getattr(message, "parts", [])
        content = "\n".join(str(getattr(part, "text", part)) for part in parts)
    return {"role": role, "content": str(content)}


@app.function(hide_code=True)
def trace_returned(record):
    return bool(
        record.get("reasoning")
        or record.get("reasoning_details")
        or record.get("reasoning_tokens")
    )


@app.function(hide_code=True)
def chat_result_record(result):
    return {
        "text": result.text,
        "finish_reason": result.finish_reason,
        "native_finish_reason": result.native_finish_reason,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "reasoning_tokens": result.reasoning_tokens,
        "cost_usd": result.cost_usd,
        "latency_ms": result.latency_ms,
        "cached": result.cached,
        "error": result.error,
        "request_hash": result.request_hash,
        "message": jsonable(result.message),
        "reasoning": result.reasoning,
        "reasoning_details": jsonable(result.reasoning_details),
    }


@app.function(hide_code=True)
def anthropic_model_id(model):
    """Map an OpenRouter model id to the first-party Anthropic model id."""
    return model.removeprefix("anthropic/").replace(".", "-")


@app.function(hide_code=True)
async def anthropic_chat_record(api_key, model, messages, system, max_tokens, reasoning):
    """Call the Anthropic API directly. Return a turn record in the playground shape."""
    import time

    from anthropic import AsyncAnthropic

    kwargs = {}
    if reasoning:
        kwargs["thinking"] = reasoning["thinking"]
        kwargs["output_config"] = {"effort": reasoning["effort"]}

    record = {
        "model": model,
        "requested_reasoning": reasoning,
        "text": "",
        "finish_reason": None,
        "native_finish_reason": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,  # the Anthropic API does not report this
        "cost_usd": None,  # the Anthropic API does not report this
        "latency_ms": 0,
        "cached": False,
        "error": None,
        "request_hash": None,
        "message": None,
        "reasoning": None,
        "reasoning_details": None,
    }
    started = time.monotonic()
    try:
        async with AsyncAnthropic(api_key=api_key) as client:
            async with client.messages.stream(
                model=anthropic_model_id(model),
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                **kwargs,
            ) as stream:
                message = await stream.get_final_message()
    except Exception as exc:  # show the failure in the turn record, not as a traceback
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["latency_ms"] = int((time.monotonic() - started) * 1000)
        return record

    thinking = "\n\n".join(b.thinking for b in message.content if b.type == "thinking")
    record.update(
        text="".join(b.text for b in message.content if b.type == "text"),
        finish_reason=message.stop_reason,
        native_finish_reason=message.stop_reason,
        prompt_tokens=message.usage.input_tokens,
        completion_tokens=message.usage.output_tokens,
        latency_ms=int((time.monotonic() - started) * 1000),
        message=jsonable(message.model_dump()),
        reasoning=thinking or None,
        reasoning_details=(
            [
                {
                    "type": "reasoning.summary",
                    "format": "anthropic-claude-v1",
                    "summary": thinking,
                }
            ]
            if thinking
            else None
        ),
    )
    return record


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## 1. Configure the model call
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    MODELS = [
        "openai/gpt-5.4-mini",
        "openai/gpt-5.4",
        "openai/gpt-5.5",
        "anthropic/claude-fable-5",
        "anthropic/claude-opus-4.8",
        "anthropic/claude-opus-4.7",
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-4.6",
        "anthropic/claude-sonnet-5",
        "google/gemini-3.1-pro-preview",
        "deepseek/deepseek-v4-pro",
        "moonshotai/kimi-k3",
        "openai/gpt-5.6-sol",
        "x-ai/grok-4.5",
    ]
    # OpenRouter normalizes the effort per provider: native effort for OpenAI and
    # Grok, thinkingLevel for Gemini 3, a token budget for Anthropic.
    REASONING_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]

    model_id = mo.ui.dropdown(
        options=MODELS,
        value="anthropic/claude-opus-4.8",
        label="OpenRouter model id",
        full_width=True,
    )
    temperature = mo.ui.slider(start=0.0, stop=2.0, step=0.1, value=0.0, label="Temperature")
    max_tokens = mo.ui.slider(start=1, stop=32768, step=1, value=16384, label="Max tokens")
    seed = mo.ui.text(value="42", label="Optional seed", full_width=True)
    reasoning_level = mo.ui.dropdown(
        options=REASONING_LEVELS,
        value="high",
        label="Reasoning effort",
        full_width=True,
    )
    system_prompt = mo.ui.text_area(
        value="You are a helpful assistant.",
        rows=6,
        label="System prompt",
        full_width=True,
    )

    mo.vstack([model_id, temperature, max_tokens, seed, reasoning_level, system_prompt])
    return (
        max_tokens,
        model_id,
        reasoning_level,
        seed,
        system_prompt,
        temperature,
    )


@app.cell(hide_code=True)
def _(max_tokens, mo, model_id, reasoning_level, seed, temperature):
    model_id_value = model_id.value.strip()
    mo.stop(not model_id_value, mo.md("**Model id is required.**"))

    seed_text = seed.value.strip()
    try:
        seed_value = int(seed_text) if seed_text else None
    except ValueError:
        mo.stop(True, mo.md("**Seed must be an integer or blank.**"))

    def build_reasoning(level, model):
        if level == "none":
            return None
        if model.startswith("anthropic/"):
            # Native Anthropic shape: adaptive thinking plus an effort level.
            # A token budget is rejected by Opus 4.7 and later.
            return {
                "thinking": {"type": "adaptive", "display": "summarized"},
                "effort": "low" if level == "minimal" else level,
            }
        return {"effort": level, "exclude": False}

    model_params = {
        "model": model_id_value,
        "temperature": float(temperature.value),
        "max_tokens": int(max_tokens.value),
        "seed": seed_value,
        "reasoning": build_reasoning(reasoning_level.value, model_id_value),
    }
    return model_id_value, model_params, seed_value


@app.cell(hide_code=True)
def _(mo):
    get_turn_results, set_turn_results = mo.state({})
    return get_turn_results, set_turn_results


@app.cell(hide_code=True)
def _(get_turn_results):
    turn_results = get_turn_results()
    return (turn_results,)


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    ## 2. Chat
    """)
    return


@app.cell(hide_code=True)
def _(
    OpenRouterClient,
    anthropic_key,
    api_key,
    get_turn_results,
    mo,
    model_id_value,
    model_params,
    seed_value,
    set_turn_results,
    system_prompt,
):
    is_anthropic = model_id_value.startswith("anthropic/")

    async def openrouter_chat(chat_messages, config):
        history = [chat_message_to_dict(message) for message in chat_messages]
        turn_idx = sum(1 for m in history if m.get("role") == "assistant") + 1

        if is_anthropic:
            # Anthropic models go to the first-party API, not to OpenRouter.
            if not anthropic_key:
                return "`ANTHROPIC_API_KEY` not set. Export it or add it to `mask/mask/.env`."
            record = await anthropic_chat_record(
                anthropic_key,
                model_id_value,
                history,
                system_prompt.value,
                model_params["max_tokens"],
                model_params["reasoning"],
            )
        else:
            if not api_key:
                return "`OPENROUTER_API_KEY` not set. Export it or add it to `mask/mask/.env`."
            async with OpenRouterClient(api_key) as client:
                result = await client.chat(
                    model=model_id_value,
                    messages=[
                        {"role": "system", "content": system_prompt.value},
                        *history,
                    ],
                    temperature=model_params["temperature"],
                    max_tokens=model_params["max_tokens"],
                    cache_dir=None,  # always re-run; disk cache disabled
                    seed=seed_value,
                    reasoning=model_params["reasoning"],
                )
            record = chat_result_record(result)
            record["model"] = model_id_value
            record["requested_reasoning"] = model_params["reasoning"]

        set_turn_results({**get_turn_results(), str(turn_idx): record})
        return record["text"] if record["text"] else f"[ERROR: {record['error']}]"

    chat = mo.ui.chat(
        openrouter_chat,
        prompts=[],
        max_height=520,
        disabled=not bool(anthropic_key if is_anthropic else api_key),
    )
    chat
    return


@app.cell
def _():
    return


@app.cell(hide_code=True)
def _(json, mo, turn_results):
    def render_detail(detail):
        if not isinstance(detail, dict):
            return code_block(str(detail))

        dtype = detail.get("type", "reasoning")
        fmt = detail.get("format")
        fmt_note = f" · format `{fmt}`" if fmt else ""

        if dtype == "reasoning.summary":
            banner = ""
            if fmt == "anthropic-claude-v1":
                banner = (
                    "> ⚠️ **Summarized reasoning** — Anthropic returns a condensed "
                    "summary, not the full chain of thought.\n\n"
                )
            return (
                f"**`reasoning.summary`**{fmt_note}\n\n"
                f"{banner}{code_block(str(detail.get('summary', '')))}"
            )
        if dtype == "reasoning.encrypted":
            data = str(detail.get("data") or "")
            return (
                f"**`reasoning.encrypted`**{fmt_note}\n\n"
                f"_[encrypted/redacted — {len(data)} chars, not human-readable]_"
            )
        if dtype == "reasoning.text":
            sig_note = "\n\n_signed_ ✅" if detail.get("signature") else ""
            return (
                f"**`reasoning.text`**{fmt_note}\n\n"
                f"{code_block(str(detail.get('text', '')))}{sig_note}"
            )
        return (
            f"**`{dtype}`**{fmt_note}\n\n"
            f"{code_block(json.dumps(detail, indent=2, ensure_ascii=False, default=str))}"
        )

    def render_turn(turn_idx, record):
        parts = [f"### Assistant turn {turn_idx}"]

        parts.append(
            "**model:** `{model}` · **finish_reason:** `{finish}` · "
            "**tokens:** `{pt}` in / `{ct}` out / `{rt}` reasoning · "
            "**cost:** `{cost}` · **latency:** `{ms} ms`".format(
                model=record.get("model"),
                finish=record.get("finish_reason"),
                pt=record.get("prompt_tokens"),
                ct=record.get("completion_tokens"),
                rt=record.get("reasoning_tokens"),
                cost=record.get("cost_usd"),
                ms=record.get("latency_ms"),
            )
        )
        if record.get("error"):
            parts.append(f"**error:** {code_block(str(record['error']))}")

        parts.append("**response**\n\n" + code_block(str(record.get("text") or "")))

        if trace_returned(record):
            details = record.get("reasoning_details") or []
            if details:
                parts.append("\n\n".join(render_detail(d) for d in details))
            elif record.get("reasoning"):
                # Some providers only return the flat `reasoning` string.
                parts.append("**reasoning**\n\n" + code_block(str(record["reasoning"])))
        else:
            requested = json.dumps(
                record.get("requested_reasoning"), indent=2, ensure_ascii=False, default=str
            )
            parts.append(
                "_No reasoning trace was returned by the selected model/provider._\n\n"
                f"**requested reasoning**\n\n{code_block(requested)}"
            )
        return "\n\n".join(parts)

    if turn_results:
        output = mo.md(
            "## Reasoning and response\n\n"
            + "\n\n".join(
                render_turn(idx, rec)
                for idx, rec in sorted(turn_results.items(), key=lambda i: int(i[0]))
            )
        )
    else:
        output = mo.md("## Reasoning and response\n\n_No OpenRouter turns have completed yet._")

    output
    return


if __name__ == "__main__":
    app.run()
