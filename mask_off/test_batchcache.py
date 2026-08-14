"""Cache contract, journal, drain, and lock checks. No API calls.

Run: pytest mask_off/test_batchcache.py
"""
import json
import os
from types import SimpleNamespace

import pytest

import dataclasses

from . import batchcache, llm, routes


def _msg(text="hello", stop_reason="end_turn", model="claude-opus-4-8"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        model=model,
        usage=SimpleNamespace(
            input_tokens=1,
            output_tokens=2,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )


def _req(cid, model="claude-opus-4-8", user="hi"):
    return {"custom_id": cid, "params": {"model": model, "messages": [user]}}


@pytest.fixture(autouse=True)
def fresh_cache_state():
    batchcache._CACHES.clear()
    yield
    batchcache._CACHES.clear()


def test_second_identical_call_submits_zero(tmp_path, fake_run):
    reqs = [_req("a"), _req("b")]
    first = batchcache.cached_batch(reqs, "t", None, tmp_path)
    assert llm.text_of(first["a"]) == "answer:a"
    assert fake_run == [["a", "b"]]
    second = batchcache.cached_batch(reqs, "t", None, tmp_path)
    assert fake_run == [["a", "b"]], "second identical call must submit nothing"
    assert llm.text_of(second["b"]) == "answer:b"


def test_changed_param_is_a_miss_not_a_stale_hit(tmp_path, fake_run):
    batchcache.cached_batch([_req("a", user="v1")], "t", None, tmp_path)
    batchcache.cached_batch([_req("a", user="v2")], "t", None, tmp_path)
    assert fake_run == [["a"], ["a"]]


def test_cache_survives_a_new_process(tmp_path, fake_run):
    reqs = [_req("a")]
    batchcache.cached_batch(reqs, "t", None, tmp_path)
    batchcache._CACHES.clear()  # simulate process death
    out = batchcache.cached_batch(reqs, "t", None, tmp_path)
    assert fake_run == [["a"]]
    assert llm.text_of(out["a"]) == "answer:a"
    assert out["a"].model == "claude-opus-4-8"
    assert out["a"].usage.output_tokens == 2


def test_none_and_max_tokens_finals_are_never_stored(tmp_path, transport):
    transport.respond = lambda r: (
        None if r["custom_id"] == "gone" else _msg(stop_reason="max_tokens")
    )
    calls = transport.calls
    reqs = [_req("gone"), _req("cut")]
    out = batchcache.cached_batch(reqs, "t", None, tmp_path)
    assert out["gone"] is None
    assert out["cut"].stop_reason == "max_tokens"
    assert not (tmp_path / "_results.jsonl").exists() or all(
        False for _ in open(tmp_path / "_results.jsonl")
    ), "bad finals must never reach _results.jsonl"
    # both requests re-submit on replay: they were never cached
    calls.clear()
    batchcache.cached_batch(reqs, "t", None, tmp_path)
    assert calls[0] == ["gone", "cut"]


def test_errored_and_textless_finals_are_retried_and_never_stored(tmp_path, transport):
    """A kimi-k3 stream that dies mid-generation still returns a MESSAGE:
    OpenRouter finish_reason "error", partial thinking, empty text. The
    seedcorpus2 refill (2026-08-14) cached 14 of these as good finals and
    every rerun replayed them. Both shapes seen in that cache must retry:
    stop_reason "error", and a "stop" whose text is empty."""

    def flaky(request):
        if len(transport.calls) > 1:  # retry pass
            return _msg(text="recovered")
        if request["custom_id"] == "died":
            return _msg(text="", stop_reason="error")
        return _msg(text="", stop_reason="stop")

    transport.respond = flaky
    out = batchcache.cached_batch([_req("died"), _req("empty")], "t", None, tmp_path)
    assert len(transport.calls) == 2, "both bad finals must reach the retry pass"
    assert llm.text_of(out["died"]) == "recovered"
    assert llm.text_of(out["empty"]) == "recovered"
    batchcache._CACHES.clear()
    stored = batchcache._cache(tmp_path)
    assert all(s["content"][0]["text"] == "recovered" for s in stored.values())


def test_a_poisoned_cache_row_is_a_miss_not_a_hit(tmp_path, transport):
    """A cache written before the errored-final rule holds errored rows. A
    rerun must resubmit them, not replay them forever."""
    req = _req("a")
    key = batchcache.request_key(req)
    with open(tmp_path / "_results.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "key": key, "custom_id": "a", "kind": "message",
            "payload": batchcache.normalize(_msg(text="", stop_reason="error")),
        }) + "\n")
    out = batchcache.cached_batch([req], "t", None, tmp_path)
    assert transport.calls == [["a"]], "the poisoned row must resubmit"
    assert llm.text_of(out["a"]) == "answer:a"
    # and the good final supersedes it for the next process
    batchcache._CACHES.clear()
    out = batchcache.cached_batch([req], "t", None, tmp_path)
    assert transport.calls == [["a"]]
    assert llm.text_of(out["a"]) == "answer:a"


def test_refresh_set_bypasses_and_supersedes(tmp_path, transport):
    serial = iter(range(100))
    transport.respond = lambda r: _msg(text=f"v{next(serial)}")
    reqs = [_req("a")]
    assert llm.text_of(batchcache.cached_batch(reqs, "t", None, tmp_path)["a"]) == "v0"
    out = batchcache.cached_batch(reqs, "t", None, tmp_path, refresh={"a"})
    assert llm.text_of(out["a"]) == "v1", "refresh must bypass the cache"
    out = batchcache.cached_batch(reqs, "t", None, tmp_path)
    assert llm.text_of(out["a"]) == "v1", "the refreshed row must supersede"


def test_duplicate_keys_are_latest_wins_at_load(tmp_path):
    req = _req("a")
    key = batchcache.request_key(req)
    with open(tmp_path / "_results.jsonl", "w", encoding="utf-8") as f:
        for text in ("old", "new"):
            f.write(json.dumps({
                "key": key, "custom_id": "a", "kind": "message",
                "payload": batchcache.normalize(_msg(text=text)),
            }) + "\n")
    stored = batchcache._cache(tmp_path)[key]
    assert stored["content"][0]["text"] == "new"


def test_retry_once_lives_below_the_cache(tmp_path, transport):
    """A truncated first pass is retried within one cached_batch call, and only
    the post-retry final is stored."""
    passes = []

    def flaky(request):
        first = not passes
        passes.append(first)
        return _msg(stop_reason="max_tokens") if first else _msg(text="final")

    transport.respond = flaky
    out = batchcache.cached_batch([_req("a")], "t", None, tmp_path)
    assert len(transport.calls) == 2, "one first pass, one retry pass"
    assert llm.text_of(out["a"]) == "final"
    batchcache._CACHES.clear()
    stored = batchcache._cache(tmp_path)
    assert len(stored) == 1
    assert next(iter(stored.values()))["content"][0]["text"] == "final"


def test_drain_folds_a_journaled_batch_into_the_cache(tmp_path, monkeypatch, transport):
    req = _req("a")
    key = batchcache.request_key(req)
    batchcache._journal(tmp_path, {
        "kind": "handle", "label": "t", "route": "anthropic",
        "batch_id": "b1", "custom_ids": ["a"], "keys": {"a": key}, "ts": "",
    })
    monkeypatch.setattr(
        batchcache, "_fetch_anthropic", lambda batch_id: {"a": _msg(text="drained")}
    )
    assert batchcache.drain_orphans(tmp_path) == 1

    def must_not_run(request):
        raise AssertionError("drained result must be a cache hit")

    transport.respond = must_not_run
    out = batchcache.cached_batch([req], "t", None, tmp_path)
    assert llm.text_of(out["a"]) == "drained"


def test_drain_skips_a_batch_that_no_longer_exists(tmp_path, monkeypatch):
    batchcache._journal(tmp_path, {
        "kind": "handle", "label": "t", "route": "anthropic",
        "batch_id": "gone", "custom_ids": ["a"], "keys": {"a": "k"}, "ts": "",
    })
    monkeypatch.setattr(batchcache, "_fetch_anthropic", lambda batch_id: None)
    assert batchcache.drain_orphans(tmp_path) == 0  # skipped, not fatal


def test_drain_does_not_repoll_a_fully_cached_batch(tmp_path, monkeypatch):
    req = _req("a")
    key = batchcache.request_key(req)
    batchcache.append_result(tmp_path, key, "a", batchcache.normalize(_msg()))
    batchcache._journal(tmp_path, {
        "kind": "handle", "label": "t", "route": "anthropic",
        "batch_id": "b1", "custom_ids": ["a"], "keys": {"a": key}, "ts": "",
    })

    def must_not_fetch(batch_id):
        raise AssertionError("fully cached batch must not be re-polled")

    monkeypatch.setattr(batchcache, "_fetch_anthropic", must_not_fetch)
    assert batchcache.drain_orphans(tmp_path) == 0


def test_crashed_refresh_batch_is_drained_despite_the_stale_cached_row(
    tmp_path, monkeypatch
):
    """Regression: a refresh resubmits under an identical key, so the stale
    cached row satisfies drain's all-keys-cached check. The refresh-marked
    handle row must be polled anyway, and only until a drained marker lands."""
    req = _req("a")
    key = batchcache.request_key(req)
    batchcache.append_result(tmp_path, key, "a", batchcache.normalize(_msg(text="stale")))

    def crash_after_submit(requests, label, progress, hooks):
        hooks.on_handle("anthropic_batch", {"batch_id": "b-refresh"},
                        [r["custom_id"] for r in requests])
        raise KeyboardInterrupt

    monkeypatch.setitem(
        routes.ADAPTERS, "anthropic_batch",
        dataclasses.replace(routes.ADAPTERS["anthropic_batch"], run=crash_after_submit),
    )
    with pytest.raises(KeyboardInterrupt):
        batchcache.cached_batch([req], "t", None, tmp_path, refresh={"a"})

    fetches = []

    def fetch(batch_id):
        fetches.append(batch_id)
        return {"a": _msg(text="superseding")}

    monkeypatch.setattr(batchcache, "_fetch_anthropic", fetch)
    batchcache._CACHES.clear()  # new process
    assert batchcache.drain_orphans(tmp_path) == 1
    assert fetches == ["b-refresh"], "stale cached row must not mask the batch"
    stored = batchcache._cache(tmp_path)[key]
    assert stored["content"][0]["text"] == "superseding"
    assert batchcache.drain_orphans(tmp_path) == 0
    assert fetches == ["b-refresh"], "a drained refresh batch must not re-poll"


def test_completed_refresh_batch_is_marked_drained_in_process(
    tmp_path, fake_run, monkeypatch
):
    req = _req("a")
    batchcache.cached_batch([req], "t", None, tmp_path)
    batchcache.cached_batch([req], "t", None, tmp_path, refresh={"a"})

    def must_not_fetch(batch_id):
        raise AssertionError("completed refresh batch must not be re-polled")

    monkeypatch.setattr(batchcache, "_fetch_anthropic", must_not_fetch)
    assert batchcache.drain_orphans(tmp_path) == 0


def test_run_lock_refuses_a_live_second_invocation(tmp_path):
    (tmp_path / "_scale.pid").write_text(str(os.getpid()))
    with batchcache.run_lock(tmp_path):  # own pid: re-entry allowed
        pass
    (tmp_path / "_scale.pid").write_text("1")  # pid 1 is always alive
    with pytest.raises(RuntimeError, match="locked"):
        with batchcache.run_lock(tmp_path):
            pass


def test_default_policy_is_the_legacy_path(monkeypatch):
    seen = []

    def fake(requests, label, progress, hooks):
        seen.append(hooks)
        return {r["custom_id"]: _msg() for r in requests}

    monkeypatch.setitem(
        routes.ADAPTERS, "anthropic_batch",
        dataclasses.replace(routes.ADAPTERS["anthropic_batch"], run=fake),
    )
    llm.run_batch_retry([_req("a")], "t", None)
    assert len(seen) == 1
    assert seen[0].on_result is None and seen[0].on_handle is None, (
        "default Policy must not touch cache hooks"
    )


def test_policy_routes_run_batch_retry_through_the_cache(tmp_path, fake_run):
    with batchcache.policy(run_dir=tmp_path):
        llm.run_batch_retry([_req("a")], "t", None)
        llm.run_batch_retry([_req("a")], "t", None)
    assert fake_run == [["a"]]
