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
# ADR-0002 §10 hazard 4: batches occasionally hang in `finalizing`; use a wall
# clock, don't only trust the status field. Past the ceiling the poller gives
# up (the handle stays journaled and drainable) — 26h covers the 24h window
# plus finalizing.
FINALIZING_WARN_SECONDS = 3600
POLL_CEILING_SECONDS = 26 * 3600


class PollCeilingExceeded(Exception):
    """The batch outlived the poll ceiling. It stays journaled and drainable."""


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


def find_batch_by_input_file(input_file_id: str, client: httpx.Client) -> str | None:
    """The batch id created from an input file, or None.

    Recovers the window F6 names: the create response is the only place a
    batch id exists, so a dropped connection after the server accepted leaves
    a billed batch with no journal row. The uploaded file id IS journaled
    before create, so the batch is findable by listing.
    """
    data = client.get("/batches", params={"limit": 100}).json()
    for batch in data.get("data", []):
        if batch.get("input_file_id") == input_file_id:
            return batch["id"]
    return None


def submit(requests: list[dict], client: httpx.Client, on_upload=None) -> dict:
    """One group -> one batch. Returns the handle dict. All requests must
    share one model (§9/F10) — the caller partitions. `on_upload(file_id,
    custom_ids)` fires after the upload and before create, so a lost create
    response stays recoverable."""
    payload = _input_jsonl(requests)
    for attempt in range(3):
        upload = client.post(
            "/files",
            files={"file": ("batch.jsonl", io.BytesIO(payload), "application/jsonl")},
            data={"purpose": "batch"},
        )
        upload.raise_for_status()
        input_file_id = upload.json()["id"]
        if on_upload is not None:
            on_upload(input_file_id, [r["custom_id"] for r in requests])
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


def submit_chunked(
    requests: list[dict], client: httpx.Client, on_submit, on_upload=None
) -> list[dict]:
    """Submit, halving the group on enqueued-quota errors instead of raising
    (§9/F9). Returns the handle list; fires on_submit per accepted batch."""
    try:
        handle = submit(requests, client, on_upload)
    except httpx.HTTPStatusError as exc:
        if not _is_quota_error(exc.response) or len(requests) < 2:
            raise
        mid = len(requests) // 2
        return submit_chunked(
            requests[:mid], client, on_submit, on_upload
        ) + submit_chunked(requests[mid:], client, on_submit, on_upload)
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
    """Poll to a terminal status, or give up at POLL_CEILING_SECONDS.

    The ceiling exists because drain runs at every process start (§10 hazard
    4): without it, one batch stuck in `finalizing` blocks every later
    invocation of the run forever. Giving up is safe — the handle stays
    journaled and undrained, so the next invocation re-polls it.
    """
    started = time.monotonic()
    warned = False
    while True:
        data = poll(handle, client)
        if data["status"] in TERMINAL:
            return data
        waited = time.monotonic() - started
        if not warned and waited > FINALIZING_WARN_SECONDS:
            warned = True
            _say(progress, f"[openai_batch] {handle['batch_id']} still "
                           f"{data['status']} after {int(waited)}s")
        if waited > POLL_CEILING_SECONDS:
            _say(progress, f"[openai_batch] {handle['batch_id']} exceeded the "
                           f"{POLL_CEILING_SECONDS}s poll ceiling in "
                           f"{data['status']}; leaving it journaled for a later "
                           f"drain rather than blocking this run")
            raise PollCeilingExceeded(handle["batch_id"])
        time.sleep(POLL_SECONDS)


def fetch(handle: dict, client: httpx.Client, slug: str | None = None) -> dict:
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
        # The REQUESTED slug, not the response's: chat completions answer with
        # a dated snapshot (gpt-5.6-sol-2026-07-01) that no PRICES key matches,
        # which would silently cost the run $0. `slug` comes from the handle.
        msg.model = slug or f"openai/{response['body'].get('model', '')}"
        msg.route = "openai_batch"
        out[row["custom_id"]] = msg
    return out


def _say(progress, text: str) -> None:
    if progress is not None:
        progress.console.print(text, markup=False, highlight=False)
    else:
        print(text)


def run_openai_batch(
    requests, label, progress, on_submit, on_result, on_upload=None
) -> dict:
    """submit -> journal -> poll -> fetch for one mixed list of openai/*
    requests, partitioned per model (§9/F10)."""
    client = _http()
    groups: dict[str, list] = {}
    for r in requests:
        groups.setdefault(r["params"]["model"], []).append(r)
    handles = []
    for model in sorted(groups):
        def _upload(file_id, custom_ids, model=model):
            on_upload(model, file_id, custom_ids)

        handles += [
            dict(h, slug=model)
            for h in submit_chunked(
                groups[model], client, on_submit, _upload if on_upload else None
            )
        ]
    out = {}
    # ponytail: batches poll sequentially; they all process server-side in
    # parallel anyway, so this only costs the tail. Interleave the polls if a
    # Stage B cohort ever fans out to many models at once.
    for handle in handles:
        try:
            data = poll_until_done(handle, client, progress)
        except PollCeilingExceeded:
            continue  # journaled and drainable; this run does not block on it
        if data["status"] != "completed":
            _say(progress, f"[openai_batch] {handle['batch_id']} ended "
                           f"{data['status']}; harvesting partial results")
        out.update(fetch(handle, client, handle.get("slug")))
    for r in requests:
        msg = out.get(r["custom_id"])
        if on_result is not None:
            on_result(r["custom_id"], msg)
        out[r["custom_id"]] = msg
    return out


class RouteKeyMissing(Exception):
    """The journaled route's credential is absent. Harvest is deferred, never
    abandoned: the caller must leave the batch drainable (ADR-0002 §9/F6)."""


def drain_fetch(handle_row: dict, progress=None) -> dict | None:
    """Re-poll a journaled openai_batch handle in any process.

    None means the batch is genuinely gone server-side (>30d) and will never
    be harvestable. A missing key raises RouteKeyMissing instead, because
    "cannot read it today" must not be recorded as "gone forever".
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise RouteKeyMissing(
            f"journaled openai_batch {handle_row.get('batch_id')} cannot be "
            f"harvested: OPENAI_API_KEY is not set"
        )
    client = _http()
    handle = dict(handle_row)
    if not handle.get("batch_id") and handle.get("input_file_id"):
        # the create response was lost mid-submit; the file id was journaled
        # first, so the billed batch is still findable (F6)
        found = find_batch_by_input_file(handle["input_file_id"], client)
        if found is None:
            return None
        handle["batch_id"] = found
        _say(progress, f"[drain] recovered batch {found} from its input file")
    try:
        data = poll_until_done(handle, client, progress)
        if data["status"] != "completed":
            _say(progress, f"[drain] openai batch {handle['batch_id']} ended "
                           f"{data['status']}; harvesting partials")
        return fetch(handle, client, handle.get("slug"))
    except PollCeilingExceeded:
        return {}  # not gone: still journaled, drained by a later invocation
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise
