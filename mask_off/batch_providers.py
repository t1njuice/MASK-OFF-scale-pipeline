"""Native OpenAI batch adapter and the price-driven route decision (ADR-0002).

Route: the per-model choice between a discounted batch endpoint and a
synchronous call, decided by comparing pinned prices in config.PRICES — never
by which lab owns the model. Latency class (§3) gates eligibility:

- "wave": a sequential iteration turn (the Stage A generator/validity loop).
  A 24h-window route is never eligible — five waves through a 24h window is
  five days. Eligible: anthropic_batch, openrouter_sync.
- "day": Stage B cells and seed authoring. All routes eligible; cheapest wins.

The adapter speaks JSON-safe handle dicts: {"batch_id", "input_file_id"} plus
"output_file_id" once poll sees it. The handle IS the `_batches.jsonl` journal
row; `drain_orphans` re-polls it in any process (ADR-0002 §4).

Batch input files are partitioned per model (§9/F10: partition, don't sort),
and lines within one file are sorted by (schema, system prefix) so stable
prefixes sit adjacent for OpenAI's automatic prefix cache (§7).
"""

import io
import json
import os
import time

import httpx

from . import config

OPENAI_BASE = "https://api.openai.com/v1"

# Poll cadence for OpenAI batches. Wider than BATCH_POLL_SECONDS: the window
# is 24h, so a 60s cadence loses nothing and stays far from rate limits.
POLL_SECONDS = 60
# ADR-0002 §10 hazard 4: batches occasionally hang in `finalizing`; warn on a
# wall clock, don't only trust the status field.
FINALIZING_WARN_SECONDS = 3600


def _http() -> httpx.Client:
    return httpx.Client(
        base_url=OPENAI_BASE,
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        timeout=300,
    )


def route(model: str, latency: str) -> str:
    """The route for one model at one latency class, from pinned prices."""
    if model.startswith("claude"):
        return "anthropic_batch"
    batch_rates = config.PRICES.get((model, "openai_batch"))
    sync_rates = config.PRICES.get((model, "openrouter_sync"))
    if (
        latency == "day"
        and model.startswith("openai/")
        and os.environ.get("OPENAI_API_KEY")
        and batch_rates is not None
        # price-driven, not provider-driven: batch must actually be cheaper
        and (sync_rates is None or batch_rates["in"] < sync_rates["in"])
    ):
        return "openai_batch"
    return "openrouter_sync"


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


def _input_jsonl(requests: list[dict]) -> bytes:
    lines = [
        {
            "custom_id": r["custom_id"],
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": openai_body(r["params"]),
        }
        for r in requests
    ]
    # stable-prefix adjacency for the automatic prefix cache (§7)
    lines.sort(
        key=lambda l: (
            json.dumps(l["body"].get("response_format", {}), sort_keys=True),
            l["body"]["messages"][0]["content"][:1024],
            l["custom_id"],
        )
    )
    return "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines).encode()


# --- submit / poll / fetch ------------------------------------------------


def _is_quota_error(resp: httpx.Response) -> bool:
    if resp.status_code not in (400, 429):
        return False
    text = resp.text.lower()
    return "enqueued" in text or "token_limit_exceeded" in text or "quota" in text


def submit(requests: list[dict], client: httpx.Client) -> dict:
    """One group -> one batch. Returns the handle dict. All requests must
    share one model (§9/F10) — the caller partitions."""
    payload = _input_jsonl(requests)
    for attempt in range(3):
        upload = client.post(
            "/files",
            files={"file": ("batch.jsonl", io.BytesIO(payload), "application/jsonl")},
            data={"purpose": "batch"},
        )
        upload.raise_for_status()
        input_file_id = upload.json()["id"]
        created = client.post(
            "/batches",
            json={
                "input_file_id": input_file_id,
                "endpoint": "/v1/chat/completions",
                "completion_window": "24h",
            },
        )
        if created.status_code < 400:
            return {"batch_id": created.json()["id"], "input_file_id": input_file_id}
        # §10 hazard 3: launch-window model_not_found is transient — retry
        if "model_not_found" in created.text and attempt < 2:
            time.sleep(30)
            continue
        created.raise_for_status()
    raise RuntimeError("unreachable")


def submit_chunked(requests: list[dict], client: httpx.Client, on_submit) -> list[dict]:
    """Submit, halving the group on enqueued-quota errors instead of raising
    (§9/F9). Returns the handle list; fires on_submit per accepted batch."""
    try:
        handle = submit(requests, client)
    except httpx.HTTPStatusError as exc:
        if not _is_quota_error(exc.response) or len(requests) < 2:
            raise
        mid = len(requests) // 2
        return submit_chunked(requests[:mid], client, on_submit) + submit_chunked(
            requests[mid:], client, on_submit
        )
    on_submit(handle, [r["custom_id"] for r in requests])
    return [handle]


TERMINAL = {"completed", "expired", "cancelled", "failed"}


def poll(handle: dict, client: httpx.Client) -> dict:
    """One status read; enriches the handle with output/error file ids."""
    data = client.get(f"/batches/{handle['batch_id']}").json()
    for key in ("output_file_id", "error_file_id"):
        if data.get(key):
            handle[key] = data[key]
    return data


def poll_until_done(handle: dict, client: httpx.Client, progress=None) -> dict:
    started = time.monotonic()
    while True:
        data = poll(handle, client)
        if data["status"] in TERMINAL:
            return data
        if (
            data["status"] == "finalizing"
            and time.monotonic() - started > FINALIZING_WARN_SECONDS
        ):
            _say(progress, f"[openai_batch] {handle['batch_id']} stuck finalizing "
                           f">{FINALIZING_WARN_SECONDS}s; still waiting")
        time.sleep(POLL_SECONDS)


def fetch(handle: dict, client: httpx.Client) -> dict:
    """{custom_id: msg | None} from the output file. Works on expired and
    cancelled batches too — partials are returned and billed, so they are
    harvested, never discarded (§5 invariant 5)."""
    from .llm import _shim_message

    out = {}
    if not handle.get("output_file_id"):
        return out
    content = client.get(f"/files/{handle['output_file_id']}/content")
    content.raise_for_status()
    for line in content.text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        response = row.get("response") or {}
        if response.get("status_code") != 200:
            out[row["custom_id"]] = None
            continue
        msg = _shim_message(response["body"])
        # keep the OpenRouter-style slug so pricing and fingerprints match
        msg.model = f"openai/{response['body'].get('model', '')}"
        msg.route = "openai_batch"
        out[row["custom_id"]] = msg
    return out


def _say(progress, text: str) -> None:
    if progress is not None:
        progress.console.print(text, markup=False, highlight=False)
    else:
        print(text)


def run_openai_batch(requests, label, progress, on_submit, on_result) -> dict:
    """submit -> journal -> poll -> fetch for one mixed list of openai/*
    requests, partitioned per model (§9/F10)."""
    client = _http()
    groups: dict[str, list] = {}
    for r in requests:
        groups.setdefault(r["params"]["model"], []).append(r)
    handles = []
    for model in sorted(groups):
        handles += submit_chunked(groups[model], client, on_submit)
    out = {}
    for handle in handles:
        data = poll_until_done(handle, client, progress)
        if data["status"] != "completed":
            _say(progress, f"[openai_batch] {handle['batch_id']} ended "
                           f"{data['status']}; harvesting partial results")
        out.update(fetch(handle, client))
    for r in requests:
        msg = out.get(r["custom_id"])
        if on_result is not None:
            on_result(r["custom_id"], msg)
        out[r["custom_id"]] = msg
    return out


def drain_fetch(handle_row: dict, progress=None) -> dict | None:
    """Re-poll a journaled openai_batch handle in any process; None when the
    batch or its files are gone (>30d)."""
    if not os.environ.get("OPENAI_API_KEY"):
        _say(progress, "[drain] WARNING: journaled openai_batch handle but "
                       "OPENAI_API_KEY is not set — results NOT harvested")
        return None
    client = _http()
    handle = dict(handle_row)
    try:
        data = poll_until_done(handle, client, progress)
        if data["status"] != "completed":
            _say(progress, f"[drain] openai batch {handle['batch_id']} ended "
                           f"{data['status']}; harvesting partials")
        return fetch(handle, client)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise
