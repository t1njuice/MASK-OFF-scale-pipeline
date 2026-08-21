"""openai_flex adapter wire tests over httpx.MockTransport. No API calls.

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


def test_route_is_price_driven(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert routes.route("claude-opus-4-8") == "anthropic_batch"
    # flex carries Batch API rates on a synchronous call, so it wins the
    # price comparison for every pinned openai/* model
    assert routes.route("openai/gpt-5.6-sol") == "openai_flex"
    assert routes.route("openai/gpt-5.6-terra") == "openai_flex"
    # an openai/* slug with no pinned native discount falls back to OpenRouter
    assert routes.route("openai/gpt-5.6-luna") == "openrouter_sync"
    assert routes.route("moonshotai/kimi-k3") == "openrouter_sync"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert routes.route("openai/gpt-5.6-sol") == "openrouter_sync"


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
    other = routes.ADAPTERS["openrouter_sync"].concurrency
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
    # Read before the patch, not written as a literal: the invariant is that
    # narrowing one route leaves the other alone, and pinning the number here
    # made a routine retune of `openrouter_sync` look like a regression.
    assert routes.ADAPTERS["openrouter_sync"].concurrency == other != 2, (
        "the other synchronous route keeps its own limit"
    )
    # A batch route hands the whole group to the provider, which fans it out
    # server-side. There is no request pool here, so there is no honest number.
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


def test_a_stale_openai_batch_journal_row_is_skipped_never_tombstoned(tmp_path):
    """The openai_batch adapter is gone, but a journal written before the
    removal could still carry one of its rows. Drain must skip it loudly and
    leave it in the journal — never discard batch work."""
    from . import batchcache

    batchcache._CACHES.clear()
    batchcache._journal(tmp_path, {
        "kind": "handle", "route": "openai_batch", "batch_id": "b1",
        "custom_ids": ["a"], "keys": {"a": "k"}, "ts": "",
    })
    assert batchcache.drain_orphans(tmp_path) == 0
    rows = (tmp_path / "_batches.jsonl").read_text().splitlines()
    assert all('"drained"' not in r for r in rows), "no tombstone on a skip"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_a_rate_limit_429_retries_and_falls_back_to_auto(monkeypatch):
    """A plain rate-limit 429 (no `resource_unavailable` in the body) must
    back off and retry like a capacity 429, ending on the auto-tier
    fallback — found 2026-08-21: a throttled key failed every terra judge
    request on first touch instead of retrying."""
    monkeypatch.setattr(batch_providers, "FLEX_BACKOFF_SECONDS", (0, 0))
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        tier = json.loads(request.read())["service_tier"]
        calls.append(tier)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": {
                "message": "Rate limit reached for gpt-5.6-terra"}})
        return httpx.Response(200, json={
            "model": "gpt-5.6-sol-2026-07-01", "service_tier": "default",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    msg = batch_providers.flex_call(_req("a")["params"], _client(handler))
    assert calls == ["flex", "flex", "auto"]
    assert msg.route == "openai_sync", "the fallback tier bills as sync"
