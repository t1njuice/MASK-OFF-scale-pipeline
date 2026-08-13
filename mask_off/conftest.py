"""One fake adapter, registered in the route registry.

Every caller reaches a provider through `routes.dispatch`, so every caller can
be exercised by replacing what the registry runs. Tests used to monkeypatch
`llm.run_batch`, which only worked because the transport had no seam: the
route split was re-derived in four places and a test could not stand in for
all of them at once.

The fake honours the real contract — it fires `on_handle` for journaled routes
and `on_result` for every message, through the same `routes._stamped` wrapper
the real adapters use — so the durability paths under test still run.
"""

import dataclasses
import itertools
from types import SimpleNamespace

import pytest

from . import routes


def message(text="hello", stop_reason="end_turn", model="claude-opus-4-8"):
    """The four fields the cache stores, and nothing else."""
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


class FakeTransport:
    """Stands in for all four adapters at once.

    `calls` records one entry per adapter invocation: the custom ids it was
    given. `routed` records the route each custom id was dispatched on.
    Set `respond` to control what comes back per request.
    """

    def __init__(self):
        self.calls: list[list[str]] = []
        self.routed: dict[str, str] = {}
        self.respond = lambda request: message(
            text=f"answer:{request['custom_id']}"
        )
        self._batch_ids = itertools.count(1)

    def _runner(self, route_name: str):
        def run(requests, label, progress, hooks):
            custom_ids = [r["custom_id"] for r in requests]
            self.calls.append(custom_ids)
            for custom_id in custom_ids:
                self.routed[custom_id] = route_name
            if route_name in routes.JOURNALED and hooks.on_handle is not None:
                hooks.on_handle(
                    route_name,
                    {"batch_id": f"b{next(self._batch_ids)}"},
                    custom_ids,
                )
            on_result = routes._stamped(hooks, route_name)
            out = {}
            for request in requests:
                msg = self.respond(request)
                on_result(request["custom_id"], msg)
                out[request["custom_id"]] = msg
            return out

        return run

    def install(self, monkeypatch) -> None:
        for name, adapter in routes.ADAPTERS.items():
            monkeypatch.setitem(
                routes.ADAPTERS, name,
                dataclasses.replace(adapter, run=self._runner(name)),
            )


@pytest.fixture
def transport(monkeypatch):
    fake = FakeTransport()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def fake_run(transport):
    """The call log, for tests that only count submissions."""
    return transport.calls
