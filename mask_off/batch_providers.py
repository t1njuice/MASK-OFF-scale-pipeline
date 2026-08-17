"""The OpenAI flex transport: synchronous chat completions at Batch API rates.

The route decision lives in `routes.py`, the one place that answers "how does
this request reach a model". `run_openai_flex` is reached through
`routes.dispatch` and assumes the route is already chosen.

The native Batch adapter that used to live beside it was removed 2026-08-16:
flex carries the same 50% discount with no 24-hour window, so the batch route
never won the price comparison and had no remaining caller.
"""

import os
import time

import httpx

OPENAI_BASE = "https://api.openai.com/v1"


# --- request translation --------------------------------------------------


def _system_text(system) -> str:
    """Anthropic-shaped system blocks -> one string (cache_control must not
    reach OpenAI; its prefix cache is automatic)."""
    if isinstance(system, str):
        return system
    return "".join(block["text"] for block in system)


def openai_body(params: dict) -> dict:
    """Anthropic-shaped `message_params` output -> an OpenAI chat body."""
    body = {
        "model": params["model"].removeprefix("openai/"),
        "max_completion_tokens": params["max_tokens"],
        "messages": [
            {"role": "system", "content": _system_text(params["system"])},
            *params["messages"],
        ],
    }
    effort = (params.get("output_config") or {}).get("effort")
    if params.get("thinking") and effort:
        body["reasoning_effort"] = effort
    fmt = (params.get("output_config") or {}).get("format")
    if fmt:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "strict": True, "schema": fmt["schema"]},
        }
    return body


# --- openai_flex (synchronous, Batch API rates) ---------------------------

# Flex trades latency for price and may return 429 resource_unavailable, which
# is NOT billed. Retry with backoff, then fall back to standard rather than
# forfeit the wave: a stalled gate vote costs a whole sequential round.
FLEX_ATTEMPTS = 3
FLEX_BACKOFF_SECONDS = (10, 30)
# A gate vote at high effort measured ~190s; the SDK default of 10 minutes is
# the documented floor for lengthy prompts, so allow well past it.
FLEX_TIMEOUT = 1200


def _flex_client() -> httpx.Client:
    return httpx.Client(
        base_url=OPENAI_BASE,
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        timeout=FLEX_TIMEOUT,
    )


def _is_resource_unavailable(resp: httpx.Response) -> bool:
    return resp.status_code == 429 and "resource_unavailable" in resp.text.lower()


def flex_call(params: dict, client: httpx.Client | None = None):
    """One synchronous chat completion at the flex tier, standard as fallback.

    Returns a shimmed message carrying `route`, so the cost table prices the
    tier that actually served the request — a fallback to standard must not
    be billed at flex rates in the report.
    """
    from .llm import _shim_message

    client = client or _flex_client()
    body = openai_body(params)
    for attempt in range(FLEX_ATTEMPTS):
        tier = "flex" if attempt < FLEX_ATTEMPTS - 1 else "auto"
        resp = client.post("/chat/completions", json={**body, "service_tier": tier})
        if resp.status_code < 400:
            data = resp.json()
            msg = _shim_message(data)
            msg.model = params["model"]  # requested slug, not a dated snapshot
            # what the server actually served, not what we asked for
            msg.route = (
                "openai_flex" if data.get("service_tier") == "flex" else "openai_sync"
            )
            return msg
        if not _is_resource_unavailable(resp) or attempt == FLEX_ATTEMPTS - 1:
            resp.raise_for_status()
        time.sleep(FLEX_BACKOFF_SECONDS[min(attempt, len(FLEX_BACKOFF_SECONDS) - 1)])
    raise RuntimeError("unreachable")


def run_openai_flex(requests, label, progress, on_result=None) -> dict:
    """Threaded flex fan-out: {custom_id: message | None}. No journal — a
    synchronous call has no server-side handle to orphan, so a crash loses
    only what `_results.jsonl` has not yet recorded (ADR-0002 §4).

    The pool is sized by this route's own entry in the registry: flex and
    OpenRouter have unrelated rate limits and no longer share one number.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from . import routes

    out = {}
    task = progress.add_task(f"{label} (flex)", total=len(requests)) if progress else None
    client = _flex_client()
    try:
        with ThreadPoolExecutor(
            max_workers=routes.ADAPTERS["openai_flex"].concurrency
        ) as pool:
            futures = {
                pool.submit(flex_call, r["params"], client): r["custom_id"]
                for r in requests
            }
            for future in as_completed(futures):
                cid = futures[future]
                try:
                    msg = future.result()
                except Exception as exc:  # noqa: BLE001 - None = errored, as batch
                    _say(progress, f"flex {cid} failed: {exc}")
                    msg = None
                if on_result is not None:
                    on_result(cid, msg)
                out[cid] = msg
                if task is not None:
                    progress.advance(task)
    finally:
        if task is not None:
            progress.remove_task(task)
    return out


def _say(progress, text: str) -> None:
    if progress is not None:
        progress.console.print(text, markup=False, highlight=False)
    else:
        print(text)
