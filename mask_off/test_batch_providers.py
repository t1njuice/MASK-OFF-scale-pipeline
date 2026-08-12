"""openai_batch adapter wire tests over httpx.MockTransport. No API calls.

Run: pytest mask_off/test_batch_providers.py
"""
import json

import httpx
import pytest

from . import batch_providers, config


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
    assert batch_providers.route("claude-opus-4-8", "day") == "anthropic_batch"
    assert batch_providers.route("openai/gpt-5.6-sol", "day") == "openai_batch"
    # a 24h window is never eligible inside a wave loop (ADR-0002 §3)
    assert batch_providers.route("openai/gpt-5.6-sol", "wave") == "openrouter_sync"
    # no pinned batch discount (terra-pro) -> sync even at day latency
    assert batch_providers.route("openai/gpt-5.6-terra-pro", "day") == "openrouter_sync"
    assert batch_providers.route("moonshotai/kimi-k3", "day") == "openrouter_sync"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert batch_providers.route("openai/gpt-5.6-sol", "day") == "openrouter_sync"


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
        batch_providers, "poll_until_done",
        lambda h, c, p=None: {"status": "completed"},
    )
    monkeypatch.setattr(batch_providers, "fetch", lambda h, c, slug=None: {})
    batch_providers.run_openai_batch(
        [_req("a", model="openai/gpt-5.6-sol"),
         _req("b", model="openai/gpt-5.6-sol-pro")],
        "t", None, on_submit=lambda h, cids: None, on_result=None,
    )
    assert created == [["openai/gpt-5.6-sol"], ["openai/gpt-5.6-sol-pro"]]
