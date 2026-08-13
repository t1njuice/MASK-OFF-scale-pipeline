"""openai_batch adapter wire tests over httpx.MockTransport. No API calls.

Run: pytest mask_off/test_batch_providers.py
"""
import dataclasses
import json
import threading
import time

import httpx
import pytest

from . import batch_providers, config, llm, pricing, routes


def _client(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=batch_providers.OPENAI_BASE,
    )


def _req(cid, model="openai/gpt-5.6-sol", user="hi"):
    return {
        "custom_id": cid,
        "params": {
            "model": model,
            "max_tokens": 100,
            "system": [{"type": "text", "text": "sys", "cache_control": {"ttl": "1h"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": "high"},
            "thinking": {"type": "adaptive"},
        },
    }


def test_route_is_price_and_latency_driven(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert routes.route("claude-opus-4-8", "day") == "anthropic_batch"
    # flex carries batch rates synchronously, so it wins at BOTH classes —
    # including the wave loop, where a 24h window is ineligible (ADR-0002 §3)
    assert routes.route("openai/gpt-5.6-sol", "day") == "openai_flex"
    assert routes.route("openai/gpt-5.6-sol", "wave") == "openai_flex"
    # terra IS pinned on flex, so it routes like sol at both classes
    assert routes.route("openai/gpt-5.6-terra", "day") == "openai_flex"
    assert routes.route("openai/gpt-5.6-terra", "wave") == "openai_flex"
    # an openai/* slug with no pinned native discount falls back to OpenRouter
    assert routes.route("openai/gpt-5.6-luna", "day") == "openrouter_sync"
    assert routes.route("moonshotai/kimi-k3", "day") == "openrouter_sync"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert routes.route("openai/gpt-5.6-sol", "day") == "openrouter_sync"


def test_route_override_forces_batch_for_a_large_fanout(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(
        config, "ROUTE_OVERRIDES", {"openai/gpt-5.6-sol": "openai_batch"}
    )
    assert routes.route("openai/gpt-5.6-sol", "wave") == "openai_batch"


def test_flex_falls_back_to_standard_after_resource_unavailable(monkeypatch):
    monkeypatch.setattr(batch_providers, "FLEX_BACKOFF_SECONDS", (0, 0))
    tiers = []

    def handler(request: httpx.Request) -> httpx.Response:
        tier = json.loads(request.read())["service_tier"]
        tiers.append(tier)
        if tier == "flex":  # not billed when this happens
            return httpx.Response(429, json={"error": {
                "code": "resource_unavailable", "message": "no capacity"}})
        return httpx.Response(200, json={
            "model": "gpt-5.6-sol", "service_tier": "default",
            "choices": [{"message": {"content": "served"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    msg = batch_providers.flex_call(_req("a")["params"], _client(handler))
    assert tiers == ["flex", "flex", "auto"], "backoff on flex, then standard"
    # priced at the tier that actually served it, not the one requested
    assert msg.route == "openai_sync"
    assert config.PRICES[("openai/gpt-5.6-sol", "openai_sync")]["out"] == 30.0

    # The same path through the route's own pool, which is what a raised
    # concurrency limit would exercise: a capacity 429 arriving on every
    # worker at once. Each fallback must still be stamped and priced at
    # standard, because a silent stampede of fallbacks at twice the flex rate
    # is how raising the limit doubles the price of the stage.
    tiers.clear()
    monkeypatch.setattr(batch_providers, "_flex_client", lambda: _client(handler))
    out = batch_providers.run_openai_flex(
        [_req(f"c{i}") for i in range(4)], "t", None
    )
    assert len(out) == 4 and all(m is not None for m in out.values())
    assert {m.route for m in out.values()} == {"openai_sync"}
    # workers interleave, so count rather than sequence
    assert sorted(tiers) == sorted(["flex", "flex", "auto"] * 4), (
        "every worker retried on flex twice, then fell back once"
    )
    standard = config.PRICES[("openai/gpt-5.6-sol", "openai_sync")]
    flex = config.PRICES[("openai/gpt-5.6-sol", "openai_flex")]
    billed = sum(pricing.usage_cost(llm.usage_summary_of(m)) for m in out.values())
    assert billed == pytest.approx(
        4 * (10 * standard["in"] + 2 * standard["out"]) / 1e6
    )
    assert standard["out"] == 2 * flex["out"], "a fallback costs twice flex"


def test_the_flex_pool_reads_its_limit_from_the_route_not_a_literal(monkeypatch):
    """Concurrency belongs to the route. Flex and OpenRouter have unrelated
    rate limits, so one number for both throttled the generous provider to the
    strict one's ceiling."""
    monkeypatch.setitem(
        routes.ADAPTERS, "openai_flex",
        dataclasses.replace(routes.ADAPTERS["openai_flex"], concurrency=2),
    )
    lock = threading.Lock()
    live = peak = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.02)
        with lock:
            live -= 1
        return httpx.Response(200, json={
            "model": "gpt-5.6-sol", "service_tier": "flex",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    monkeypatch.setattr(batch_providers, "_flex_client", lambda: _client(handler))
    out = batch_providers.run_openai_flex(
        [_req(f"c{i}") for i in range(8)], "t", None
    )
    assert len(out) == 8
    assert 1 < peak <= 2, "the pool runs concurrently, capped by its own route"
    assert routes.ADAPTERS["openrouter_sync"].concurrency == 8, (
        "the other synchronous route keeps its own limit"
    )
    # A batch route hands the whole group to the provider, which fans it out
    # server-side. There is no request pool here, so there is no honest number.
    assert routes.ADAPTERS["openai_batch"].concurrency is None
    assert routes.ADAPTERS["anthropic_batch"].concurrency is None


def test_flex_success_is_priced_at_flex_rates():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.read())["service_tier"] == "flex"
        return httpx.Response(200, json={
            "model": "gpt-5.6-sol-2026-07-01", "service_tier": "flex",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5,
                      "prompt_tokens_details": {"cached_tokens": 90}}})

    msg = batch_providers.flex_call(_req("a")["params"], _client(handler))
    assert msg.route == "openai_flex"
    assert msg.model == "openai/gpt-5.6-sol"  # requested slug, not the snapshot
    assert msg.usage.input_tokens == 10  # convention U
    assert msg.usage.cache_read_input_tokens == 90
    rates = config.PRICES[("openai/gpt-5.6-sol", "openai_flex")]
    assert rates["out"] == 15.0, "flex bills at Batch API rates"


def test_a_non_429_error_is_not_retried_as_capacity(monkeypatch):
    monkeypatch.setattr(batch_providers, "FLEX_BACKOFF_SECONDS", (0, 0))
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad schema"}})

    with pytest.raises(httpx.HTTPStatusError):
        batch_providers.flex_call(_req("a")["params"], _client(handler))
    assert len(calls) == 1, "a programmer error must raise, not burn retries"


def test_openai_body_translation():
    body = batch_providers.openai_body(_req("a")["params"])
    assert body["model"] == "gpt-5.6-sol"
    assert body["max_completion_tokens"] == 100
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["reasoning_effort"] == "high"
    assert "cache_control" not in json.dumps(body)


def test_submit_poll_fetch_round_trip():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/files" and request.method == "POST":
            seen["upload"] = request.read()
            return httpx.Response(200, json={"id": "file-in"})
        if request.url.path == "/v1/batches" and request.method == "POST":
            seen["create"] = json.loads(request.read())
            return httpx.Response(200, json={"id": "batch-1", "status": "validating"})
        if request.url.path == "/v1/batches/batch-1":
            return httpx.Response(200, json={
                "id": "batch-1", "status": "completed", "output_file_id": "file-out",
            })
        if request.url.path == "/v1/files/file-out/content":
            line = {
                "custom_id": "a",
                "response": {"status_code": 200, "body": {
                    "model": "gpt-5.6-sol",
                    "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2,
                              "prompt_tokens_details": {"cached_tokens": 4}},
                }},
            }
            return httpx.Response(200, text=json.dumps(line) + "\n")
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    client = _client(handler)
    handle = batch_providers.submit([_req("a")], client)
    assert handle == {"batch_id": "batch-1", "input_file_id": "file-in"}
    assert seen["create"]["completion_window"] == "24h"
    data = batch_providers.poll(handle, client)
    assert data["status"] == "completed" and handle["output_file_id"] == "file-out"
    out = batch_providers.fetch(handle, client)
    msg = out["a"]
    assert msg.content[-1].text == "hello"
    assert msg.model == "openai/gpt-5.6-sol"
    assert msg.route == "openai_batch"
    assert msg.usage.input_tokens == 6  # convention U: cached excluded


def test_quota_error_halves_the_group_instead_of_raising():
    submitted_sizes = []
    last_upload = [b""]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/files":
            last_upload[0] = request.read()
            return httpx.Response(200, json={"id": f"file-{len(submitted_sizes)}"})
        if request.url.path == "/v1/batches" and request.method == "POST":
            # the custom_ids live in the uploaded file, not the create body
            n = last_upload[0].count(b'"custom_id"')
            submitted_sizes.append(n)
            if n == 4:  # the full group trips the enqueued-token quota
                return httpx.Response(400, json={"error": {
                    "message": "Enqueued token limit exceeded for gpt-5.6-sol"}})
            return httpx.Response(200, json={"id": f"batch-{len(submitted_sizes)}"})
        raise AssertionError(request.url.path)

    handles = []
    client = _client(handler)
    got = batch_providers.submit_chunked(
        [_req(f"c{i}") for i in range(4)], client,
        on_submit=lambda h, cids: handles.append((h["batch_id"], sorted(cids))),
    )
    assert len(got) == 2
    assert [n for n in submitted_sizes if n == 2] == [2, 2]
    assert sorted(cids for _, cids in handles) == [["c0", "c1"], ["c2", "c3"]]


def test_fetch_harvests_partials_from_an_expired_batch():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/files/file-out/content":
            lines = [
                {"custom_id": "a", "response": {"status_code": 200, "body": {
                    "model": "gpt-5.6-sol",
                    "choices": [{"message": {"content": "partial"},
                                 "finish_reason": "stop"}], "usage": {}}}},
                {"custom_id": "b", "response": {"status_code": 500, "body": {}}},
            ]
            return httpx.Response(200, text="\n".join(json.dumps(l) for l in lines))
        raise AssertionError(request.url.path)

    out = batch_providers.fetch(
        {"batch_id": "x", "output_file_id": "file-out"}, _client(handler)
    )
    assert out["a"].content[-1].text == "partial"  # billed partials harvested
    assert out["b"] is None


def test_truncation_maps_to_max_tokens_and_is_never_cached():
    def handler(request: httpx.Request) -> httpx.Response:
        line = {"custom_id": "a", "response": {"status_code": 200, "body": {
            "model": "gpt-5.6-sol",
            "choices": [{"message": {"content": "{\"cut\":"},
                         "finish_reason": "length"}], "usage": {}}}}
        return httpx.Response(200, text=json.dumps(line))

    out = batch_providers.fetch(
        {"batch_id": "x", "output_file_id": "file-out"}, _client(handler)
    )
    # strict schema does not protect against truncation (ADR-0002 §6); the
    # shim's max_tokens mapping is what keeps it out of the cache (F1)
    assert out["a"].stop_reason == "max_tokens"


def test_missing_key_defers_the_drain_instead_of_tombstoning(monkeypatch):
    """A missing credential must never be recorded as "batch gone forever":
    the batch stays journaled and drainable (ADR-0002 §5 invariant 6)."""
    from . import batchcache

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(batch_providers.RouteKeyMissing):
        batch_providers.drain_fetch({"batch_id": "b1"})

    run_dir = None  # drain must skip the row without writing a drained marker

    def fake_drain(row, progress=None):
        raise batch_providers.RouteKeyMissing("no key")

    monkeypatch.setattr(batch_providers, "drain_fetch", fake_drain)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path

        run_dir = Path(tmp)
        batchcache._CACHES.clear()
        batchcache._journal(run_dir, {
            "kind": "handle", "route": "openai_batch", "batch_id": "b1",
            "custom_ids": ["a"], "keys": {"a": "k"}, "refresh_ids": ["a"], "ts": "",
        })
        assert batchcache.drain_orphans(run_dir) == 0
        rows = [
            l for l in (run_dir / "_batches.jsonl").read_text().splitlines() if l
        ]
        assert all('"drained"' not in r for r in rows), "no tombstone on a key gap"
        with pytest.raises(batch_providers.RouteKeyMissing):
            batchcache.drain_orphans(run_dir, strict=True)


def test_lost_create_response_is_recovered_from_the_input_file():
    """The batch id lives only in the create response; the file id is journaled
    first, so a dropped create is still findable (F6)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/batches" and request.method == "GET":
            return httpx.Response(200, json={"data": [
                {"id": "batch-other", "input_file_id": "file-zzz"},
                {"id": "batch-found", "input_file_id": "file-lost"},
            ]})
        raise AssertionError(request.url.path)

    assert batch_providers.find_batch_by_input_file(
        "file-lost", _client(handler)) == "batch-found"
    assert batch_providers.find_batch_by_input_file(
        "file-never", _client(handler)) is None


def test_fetch_keeps_the_requested_slug_not_the_dated_snapshot():
    def handler(request: httpx.Request) -> httpx.Response:
        line = {"custom_id": "a", "response": {"status_code": 200, "body": {
            "model": "gpt-5.6-sol-2026-07-01",  # dated snapshot, unpinnable
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {}}}}
        return httpx.Response(200, text=json.dumps(line))

    out = batch_providers.fetch(
        {"batch_id": "x", "output_file_id": "f"}, _client(handler),
        slug="openai/gpt-5.6-sol",
    )
    assert out["a"].model == "openai/gpt-5.6-sol"
    assert ("openai/gpt-5.6-sol", "openai_batch") in config.PRICES


def _batch_handler(status_of, content_of):
    """A submit/poll/fetch wire for run_openai_batch. `status_of(batch_id)`
    answers one poll; `content_of(output_file_id)` answers one output file."""
    created = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/files" and request.method == "POST":
            return httpx.Response(200, json={"id": f"file-{len(created)}"})
        if path == "/v1/batches" and request.method == "POST":
            created.append(1)
            return httpx.Response(200, json={"id": f"batch-{len(created)}"})
        if path.startswith("/v1/batches/"):
            return httpx.Response(200, json=status_of(path.rsplit("/", 1)[-1]))
        if path.startswith("/v1/files/") and path.endswith("/content"):
            return httpx.Response(200, text=content_of(path.split("/")[3]))
        raise AssertionError(f"unexpected {request.method} {path}")

    return handler


def _out_line(custom_id, text="hello"):
    return json.dumps({"custom_id": custom_id, "response": {
        "status_code": 200, "body": {
            "model": "gpt-5.6-sol",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {}}}})


def test_batch_polls_interleave_across_models(monkeypatch):
    """Stage B submits one batch per model. Polled in sequence, the second
    batch is not even looked at until the first has run its whole window, and
    the 13-model roster is what turns that tail into the dominant term."""
    monkeypatch.setattr(batch_providers, "POLL_SECONDS", 0)
    slow = {"left": 2}  # batch-1 needs three cycles; batch-2 lands on the first

    def status_of(batch_id):
        if batch_id == "batch-1" and slow["left"]:
            slow["left"] -= 1
            return {"id": batch_id, "status": "in_progress"}
        return {"id": batch_id, "status": "completed",
                "output_file_id": f"out-{batch_id}"}

    polled = []
    fetched_after = {}

    def watched(batch_id):
        polled.append(batch_id)
        return status_of(batch_id)

    def content_of(file_id):
        # how many polls had happened when this batch was harvested
        fetched_after[file_id] = len(polled)
        cid = "a" if file_id == "out-batch-1" else "b"
        return _out_line(cid, cid)

    monkeypatch.setattr(
        batch_providers, "_http", lambda: _client(_batch_handler(watched, content_of))
    )
    out = batch_providers.run_openai_batch(
        [_req("a", model="openai/gpt-5.6-sol"),
         _req("b", model="openai/gpt-5.6-sol-pro")],
        "t", None, on_submit=lambda h, cids: None, on_result=None,
    )
    assert polled[:2] == ["batch-1", "batch-2"], "both read on the first cycle"
    assert polled.count("batch-2") == 1, "a finished batch is not re-polled"
    assert fetched_after["out-batch-2"] < fetched_after["out-batch-1"], (
        "the fast batch is harvested without waiting out the slow one"
    )
    assert set(out) == {"a", "b"}
    assert out["a"].content[-1].text == "a" and out["b"].content[-1].text == "b"


def test_a_stuck_batch_neither_blocks_its_neighbour_nor_loses_a_partial(monkeypatch):
    """The durability properties survive the interleaving: every handle is
    journaled before any poll, a batch past the ceiling stays journaled and
    drainable instead of raising, and an expired batch's billed partials are
    harvested rather than discarded (ADR-0002 §5 invariant 5)."""
    monkeypatch.setattr(batch_providers, "POLL_SECONDS", 0)
    monkeypatch.setattr(batch_providers, "POLL_CEILING_SECONDS", -1)
    journaled = []

    def status_of(batch_id):
        if batch_id == "batch-1":
            return {"id": batch_id, "status": "finalizing"}  # §10 hazard 4
        return {"id": batch_id, "status": "expired", "output_file_id": "out-2"}

    monkeypatch.setattr(
        batch_providers,
        "_http",
        lambda: _client(_batch_handler(status_of, lambda f: _out_line("b", "partial"))),
    )
    out = batch_providers.run_openai_batch(
        [_req("a", model="openai/gpt-5.6-sol"),
         _req("b", model="openai/gpt-5.6-sol-pro")],
        "t", None,
        on_submit=lambda h, cids: journaled.append(h["batch_id"]),
        on_result=None,
    )
    assert journaled == ["batch-1", "batch-2"], "journaled before the first poll"
    assert out["b"].content[-1].text == "partial"
    assert out["a"] is None, "the stuck batch yields no result and no exception"


def test_poll_ceiling_gives_up_instead_of_blocking_the_run(monkeypatch):
    monkeypatch.setattr(batch_providers, "POLL_CEILING_SECONDS", -1)
    monkeypatch.setattr(batch_providers, "POLL_SECONDS", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "b", "status": "finalizing"})

    with pytest.raises(batch_providers.PollCeilingExceeded):
        batch_providers.poll_until_done({"batch_id": "b"}, _client(handler))


def test_input_file_partitions_are_single_model_via_run(monkeypatch):
    """run_openai_batch must submit one batch per model (ADR-0002 §9/F10)."""
    created = []

    def fake_submit_chunked(requests, client, on_submit, on_upload=None):
        models = {r["params"]["model"] for r in requests}
        assert len(models) == 1, "a batch input file must be single-model"
        created.append(sorted(models))
        handle = {"batch_id": f"b{len(created)}", "input_file_id": "f"}
        on_submit(handle, [r["custom_id"] for r in requests])
        return [handle]

    monkeypatch.setattr(batch_providers, "submit_chunked", fake_submit_chunked)
    monkeypatch.setattr(batch_providers, "_http", lambda: None)
    monkeypatch.setattr(
        batch_providers, "poll_all_until_done",
        lambda hs, c, p=None: ((h, {"status": "completed"}) for h in hs),
    )
    monkeypatch.setattr(batch_providers, "fetch", lambda h, c, slug=None: {})
    batch_providers.run_openai_batch(
        [_req("a", model="openai/gpt-5.6-sol"),
         _req("b", model="openai/gpt-5.6-sol-pro")],
        "t", None, on_submit=lambda h, cids: None, on_result=None,
    )
    assert created == [["openai/gpt-5.6-sol"], ["openai/gpt-5.6-sol-pro"]]
