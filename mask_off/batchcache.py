"""Request-level batch cache with a pre-poll journal (ADR-0001, ADR-0002).

One layer of durability for everything that funnels through `run_batch_retry`:

- Every completed result is stored in `<run_dir>/_results.jsonl`, keyed by
  request content. Replaying a cohort turns paid work into cache hits.
- Batch ids are journaled to `<run_dir>/_batches.jsonl` BEFORE polling begins.
  If the process dies, `drain_orphans` re-polls the journaled handle in any
  later process and folds the results into the cache.
- The `Policy` contextvar is the seam: `scale.py` sets it via `policy(...)`;
  `llm.run_batch_retry` reads it ONCE at entry on the calling thread. The
  default `Policy()` reproduces the uncached legacy behavior exactly.

Cache contract (ADR-0002 §9/F1):
1. The cache never stores `None` and never stores a final whose
   `stop_reason == "max_tokens"`.
2. `cached_batch` accepts a per-call `refresh` set of custom_ids that bypass
   the cache and supersede the stored row.
3. Duplicate keys are latest-wins, both at load and in the in-process dict.
"""

import contextvars
import datetime
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from . import config


# --- Policy seam ----------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    run_dir: Path | None = None
    tolerance: float | None = None
    strict: bool = False


_POLICY = contextvars.ContextVar("mask_off_batch_policy", default=Policy())


def current_policy() -> Policy:
    return _POLICY.get()


@contextmanager
def policy(run_dir=None, tolerance=None, strict=False):
    """Set the ambient Policy. Only `scale.py` calls this (ADR-0002 §4)."""
    token = _POLICY.set(
        Policy(Path(run_dir) if run_dir else None, tolerance, strict)
    )
    try:
        yield
    finally:
        _POLICY.reset(token)


# --- Keying and the stored value ------------------------------------------


def request_key(request: dict) -> str:
    """sha256(custom_id + canonical params). Determinism of the params dict is
    the caller's contract (ADR-0001): no timestamps, no unsorted collections."""
    canonical = json.dumps(
        request["params"], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256((request["custom_id"] + canonical).encode()).hexdigest()


def normalize(msg) -> dict:
    """The four-field stored view. Not an SDK Message; both the Anthropic and
    OpenRouter-shim paths already produce exactly these fields."""
    from .llm import usage_summary_of

    content = []
    for block in getattr(msg, "content", None) or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            content.append({"type": "text", "text": block.text})
        elif kind == "thinking":
            content.append(
                {"type": "thinking", "thinking": getattr(block, "thinking", "") or ""}
            )
    usage = usage_summary_of(msg)  # carries model and route (F4)
    return {
        "content": content,
        "stop_reason": getattr(msg, "stop_reason", None),
        "usage": usage,
        "resolved_provider": getattr(msg, "resolved_provider", None),
    }


def rehydrate(stored: dict) -> SimpleNamespace:
    """Only text_of / reasoning_summary_of / usage_summary_of / .stop_reason /
    .model are valid on the result (ADR-0001)."""
    usage = dict(stored["usage"])
    model = usage.pop("model", None)
    route = usage.pop("route", None)
    return SimpleNamespace(
        content=[SimpleNamespace(**block) for block in stored["content"]],
        stop_reason=stored["stop_reason"],
        model=model,
        route=route,
        usage=SimpleNamespace(**usage),
        resolved_provider=stored.get("resolved_provider"),
    )


def _bad(msg) -> bool:
    """A final (the post-retry result a request settles on) that must not be
    cached: no message at all, or output truncated at max_tokens."""
    from .llm import bad_final

    return bad_final(msg)


# --- Files ----------------------------------------------------------------

_CACHES: dict[Path, dict] = {}  # run_dir -> {key: payload}, loaded once per process
_WRITE_LOCK = threading.Lock()  # sync-route workers append from pool threads


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _results_path(run_dir: Path) -> Path:
    return run_dir / "_results.jsonl"


def _journal_path(run_dir: Path) -> Path:
    return run_dir / "_batches.jsonl"


def _cache(run_dir: Path) -> dict:
    run_dir = Path(run_dir).resolve()
    if run_dir not in _CACHES:
        loaded = {}
        path = _results_path(run_dir)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                loaded[row["key"]] = row["payload"]  # latest-wins
        _CACHES[run_dir] = loaded
    return _CACHES[run_dir]


def append_result(run_dir: Path, key: str, custom_id: str, payload: dict) -> None:
    """Durability precedes visibility (ADR-0002 §5): the file line is written
    before the in-process dict is updated."""
    row = json.dumps(
        {"key": key, "custom_id": custom_id, "kind": "message", "payload": payload},
        ensure_ascii=False,
    )
    with _WRITE_LOCK:
        with open(_results_path(run_dir), "a", encoding="utf-8") as f:
            f.write(row + "\n")
            f.flush()
        _cache(run_dir)[key] = payload


def _journal(run_dir: Path, row: dict) -> None:
    with _WRITE_LOCK:
        with open(_journal_path(run_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()


# --- The cached batch path ------------------------------------------------


def _log(progress, text: str) -> None:
    if progress is not None:
        progress.console.print(text, markup=False, highlight=False)
    else:
        print(text)


def cached_batch(
    requests: list[dict],
    label: str,
    progress,
    run_dir: Path,
    refresh: frozenset | set = frozenset(),
    strict: bool = False,
    latency: str = "wave",
) -> dict:
    """Drop-in for run_batch_retry: {custom_id: message | None}, cache-backed.

    Retry-once lives BELOW this cache: only post-retry finals are stored, and
    never None, never a max_tokens final.
    """
    if not requests:
        return {}
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    cache = _cache(run_dir)
    keys = {r["custom_id"]: request_key(r) for r in requests}

    out, misses = {}, []
    for r in requests:
        cid = r["custom_id"]
        stored = None if cid in refresh else cache.get(keys[cid])
        if stored is not None:
            out[cid] = rehydrate(stored)
        else:
            misses.append(r)
    # A refreshed request resubmits under an IDENTICAL key, so its stale cached
    # row would satisfy drain's all-keys-cached check and hide the paid
    # resubmission from recovery. These ids are marked on the handle row so
    # drain re-polls the batch regardless of the cache (see drain_orphans).
    stale_refresh = {cid for cid in refresh if cache.get(keys.get(cid)) is not None}
    _log(progress, f"[batchcache] {label}: {len(out)} hits, {len(misses)} misses")

    if misses:
        try:
            out.update(
                _run_misses(
                    misses, label, progress, run_dir, keys, stale_refresh, latency
                )
            )
        except KeyboardInterrupt:
            _log(
                progress,
                f"[batchcache] interrupted; journaled batches keep running "
                f"server-side. Re-invoke to drain: {_journal_path(run_dir)}",
            )
            raise
    if strict:
        dead = [cid for cid in keys if out.get(cid) is None]
        if dead:
            raise RuntimeError(f"{label}: no result for {dead} under strict policy")
    return out


def _run_misses(
    misses,
    label,
    progress,
    run_dir: Path,
    keys: dict,
    stale_refresh: set = frozenset(),
    latency: str = "wave",
) -> dict:
    from . import routes

    # The route decision is made once, by the registry (ADR-0002). The cache
    # used to re-derive it here and llm.run_batch re-derived it again; both
    # had to agree and could silently drift.
    for route_name, group in routes.partition(misses, latency).items():
        if route_name not in routes.JOURNALED:
            continue  # a synchronous route has no handle to orphan
        _journal(
            run_dir,
            {
                "kind": "intent",
                "label": label,
                "route": route_name,
                "custom_ids": [r["custom_id"] for r in group],
                "keys": {r["custom_id"]: keys[r["custom_id"]] for r in group},
                "ts": _now(),
            },
        )
    refresh_batches = []

    def on_handle(route_name: str, handle: dict, custom_ids: list[str]) -> None:
        row = {
            "kind": "handle",
            "label": label,
            "route": route_name,
            **handle,
            "custom_ids": custom_ids,
            "keys": {cid: keys[cid] for cid in custom_ids},
            "ts": _now(),
        }
        marked = sorted(stale_refresh & set(custom_ids))
        if marked:
            row["refresh_ids"] = marked
            if handle.get("batch_id"):
                refresh_batches.append(handle["batch_id"])
        _journal(run_dir, row)

    def on_result(cid: str, msg) -> None:
        if _bad(msg):
            return  # F1 rule 1: never cache None or a max_tokens final
        append_result(run_dir, keys[cid], cid, normalize(msg))

    hooks = routes.Hooks(
        on_result=on_result, on_handle=on_handle, cancel_on_interrupt=False
    )

    def _one_pass(requests, pass_label):
        return routes.dispatch(requests, pass_label, progress, latency, hooks)

    out = _one_pass(misses, label)
    retry = [r for r in misses if _bad(out.get(r["custom_id"]))]
    if retry:
        out.update(_one_pass(retry, f"{label} (retry)"))
    # the refresh batches completed in-process; mark them drained so restarts
    # do not re-poll them (their keys can never prove completion — see above)
    for batch_id in refresh_batches:
        _journal(run_dir, {"kind": "drained", "batch_id": batch_id, "ts": _now()})
    return {r["custom_id"]: out.get(r["custom_id"]) for r in misses}


# --- Orphan drain ---------------------------------------------------------


def _fetch_anthropic(batch_id: str):
    """Poll a journaled batch to completion and return {custom_id: msg | None};
    None if the batch no longer exists server-side (expired, >29d)."""
    import anthropic

    from .llm import client

    batches = client().messages.batches
    try:
        while True:
            status = batches.retrieve(batch_id)
            if status.processing_status == "ended":
                break
            time.sleep(config.BATCH_POLL_SECONDS)
        return {
            item.custom_id: (item.result.message if item.result.type == "succeeded" else None)
            for item in batches.results(batch_id)
        }
    except anthropic.NotFoundError:
        return None


def drain_orphans(run_dir: Path, progress=None, strict: bool = False) -> int:
    """Fold journaled-but-unfetched batch results into the cache.

    Runs at every process start, BEFORE the fingerprint gate (harvest is always
    safe; the fingerprint gates new submissions only). Uses the journaled
    `route` field, never re-computes routing. Returns the count folded.
    """
    run_dir = Path(run_dir)
    path = _journal_path(run_dir)
    if not path.exists():
        return 0
    handles, intents, drained = {}, [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") == "handle":
            # dedupe latest-wins; a pre-create row keys on its input file so
            # the real handle row supersedes it once the batch id lands
            handles[row.get("batch_id") or f"file:{row.get('input_file_id')}"] = row
            if row.get("batch_id") and row.get("input_file_id"):
                handles.pop(f"file:{row['input_file_id']}", None)
        elif row.get("kind") == "intent":
            intents.append(row)
        elif row.get("kind") == "drained":
            drained.add(row["batch_id"])
    cache = _cache(run_dir)
    folded = 0
    for row in handles.values():
        keys = row["keys"]
        if row.get("batch_id") and row["batch_id"] in drained:
            continue
        # a refresh batch resubmits under keys the STALE rows already occupy,
        # so the cache can never prove it completed; poll it unconditionally
        # until a drained marker lands (ADR-0002 §5 invariant 6)
        if not row.get("refresh_ids") and all(k in cache for k in keys.values()):
            continue
        if row["route"] == "openai_batch":
            from . import batch_providers

            try:
                results = batch_providers.drain_fetch(row, progress)
            except batch_providers.RouteKeyMissing as exc:
                # loud and run-blocking under strict; never a tombstone —
                # the batch stays drainable once the key is present (F6)
                _log(progress, f"[drain] WARNING: {exc}; results NOT harvested "
                               f"and left drainable. Export the key and re-invoke.")
                if strict:
                    raise
                continue
        # "anthropic" is the pre-registry journal name for this route. Journals
        # written before ticket 05 still carry it, and a harvest must never
        # fail to recognise a route it wrote itself.
        elif row["route"] in ("anthropic_batch", "anthropic"):
            results = _fetch_anthropic(row["batch_id"])
        else:
            _log(progress, f"[drain] unsupported route {row['route']!r}, skipped")
            continue
        if results is None:
            _log(progress, f"[drain] batch {row['batch_id']} no longer exists, skipped")
            if row.get("refresh_ids") and row.get("batch_id"):
                _journal(run_dir, {"kind": "drained", "batch_id": row["batch_id"],
                                   "ts": _now()})
            continue
        for cid, msg in results.items():
            if cid in keys and not _bad(msg):
                append_result(run_dir, keys[cid], cid, normalize(msg))
                folded += 1
        if row.get("refresh_ids"):
            _journal(run_dir, {"kind": "drained", "batch_id": row["batch_id"],
                               "ts": _now()})
    handled = {cid for row in handles.values() for cid in row["custom_ids"]}
    for intent in intents:
        lost = [
            cid
            for cid in intent["custom_ids"]
            if cid not in handled and intent["keys"][cid] not in cache
        ]
        if lost:
            _log(
                progress,
                f"[drain] WARNING: intent {intent['label']!r} has {len(lost)} "
                f"custom_ids with no journaled handle and no cached result — "
                f"a submit may have been billed but lost pre-journal",
            )
    if folded:
        _log(progress, f"[drain] folded {folded} orphaned results into the cache")
    return folded


# --- Run-directory lock ---------------------------------------------------


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def run_lock(run_dir: Path):
    """Pid lockfile: two invocations on one run directory is a refusal."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = run_dir / "_scale.pid"
    if lock.exists():
        pid = int(lock.read_text().strip() or 0)
        if pid and pid != os.getpid() and _alive(pid):
            raise RuntimeError(f"{run_dir} is locked by running pid {pid}")
    lock.write_text(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
