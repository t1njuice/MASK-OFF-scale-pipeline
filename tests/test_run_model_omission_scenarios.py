"""Tests for the model omission scenario wrapper script."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

from scripts import run_model_omission_scenarios


def test_script_passes_reasoning_effort(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    behavior = tmp_path / "behavior"
    behavior.mkdir()
    (behavior / "BEHAVIOR.md").write_text("Test behavior.")

    called: dict[str, Any] = {}

    def fake_run_scenarios(path: Path, **kwargs: Any) -> None:
        called["path"] = path
        called["kwargs"] = kwargs

    monkeypatch.setitem(
        sys.modules,
        "petri_bloom",
        types.SimpleNamespace(run_scenarios=fake_run_scenarios),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_model_omission_scenarios.py",
            "--behavior",
            str(behavior),
            "--model",
            "mockllm/model",
            "--reasoning-effort",
            "xhigh",
        ],
    )

    assert run_model_omission_scenarios.main() == 0
    assert called["path"] == behavior.resolve()
    assert called["kwargs"] == {
        "scenarios_model": "mockllm/model",
        "overwrite": False,
        "reasoning_effort": "xhigh",
    }
