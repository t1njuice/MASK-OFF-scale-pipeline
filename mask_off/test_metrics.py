"""Tests for mask_off.metrics against a tiny synthetic run directory."""

import json
from pathlib import Path

from .metrics import report, wilson


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def _vote(verdict: str, failed: str | None = None) -> dict:
    constraints = {
        "severity_floor": {"passed": failed != "severity_floor", "note": "n"},
        "single_fact": {"passed": True, "note": "n"},
    }
    return {"verdict": verdict, "seed_defect": False, "feedback": "",
            "constraints": constraints}


def _stage_a_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({
        "draw_seed": 12345,
        "fingerprint": {"GENERATOR_MODEL": "claude-opus-4-8",
                        "PROMPT_VERSION": "v5.2"},
        "target": 10,
        "consumed": ["s1", "s2", "s3"],
        "yield_ema": 0.5,
        "cohort": 2,
        "pending": None,
    }), encoding="utf-8")
    _write_jsonl(run_dir / "accepted.jsonl", [
        {"result_id": "maskoff-aaa", "seed_name": "s1", "seed_source": "kimi",
         "iterations": 2, "taxonomy": "medical"},
        {"result_id": "maskoff-bbb", "seed_name": "s2", "seed_source": "kimi",
         "iterations": 1, "taxonomy": "financial"},
    ])
    _write_jsonl(run_dir / "cohorts.jsonl", [
        {"cohort": 1, "launched": 2, "accepted": 1, "yield": 0.5,
         "yield_ema": 0.5, "ts": "2026-08-12T00:00:00+00:00"},
        {"cohort": 2, "launched": 1, "accepted": 1, "yield": 1.0,
         "yield_ema": 0.75, "ts": "2026-08-12T01:00:00+00:00"},
    ])
    # wave 1: s1 rejected (severity_floor fails); wave 2: s1 accepted.
    # usage numbers give cache-write ratios 2000/3000 and 0/2000.
    _write_jsonl(run_dir / "run_log.jsonl", [
        {"seed_name": "s1", "seed_source": "kimi", "iteration": 1,
         "candidate": {}, "votes": [_vote("revise", "severity_floor"),
                                    _vote("accept")],
         "accepted": False, "seed_defect": False, "feedback": "fix it",
         "scope": "", "n_votes": 2, "n_accept": 1,
         "usage": {"generator": {"input_tokens": 100, "output_tokens": 50,
                                 "cache_creation_input_tokens": 1000,
                                 "cache_read_input_tokens": 0,
                                 "model": "claude-opus-4-8"},
                   "votes": [{"cache_creation_input_tokens": 500,
                              "cache_read_input_tokens": 500},
                             {"cache_creation_input_tokens": 500,
                              "cache_read_input_tokens": 500}]}},
        {"seed_name": "s1", "seed_source": "kimi", "iteration": 2,
         "candidate": {}, "votes": [_vote("accept"), _vote("accept")],
         "accepted": True, "seed_defect": False, "feedback": "",
         "scope": "", "n_votes": 2, "n_accept": 2,
         "usage": {"generator": {"input_tokens": 100, "output_tokens": 50,
                                 "cache_creation_input_tokens": 0,
                                 "cache_read_input_tokens": 1000,
                                 "model": "claude-opus-4-8"},
                   "votes": [{"cache_creation_input_tokens": 0,
                              "cache_read_input_tokens": 1000}]}},
        {"seed_name": "s3", "iteration": 1, "stage": "generator",
         "error": "RuntimeError('boom')", "usage": {}},
    ])
    return run_dir


def _add_eval(run_dir: Path) -> None:
    eval_dir = run_dir / "eval"
    eval_dir.mkdir()
    # Main judgments across both items: labels [2, 1, 2] -> omission 2/3.
    # p2-prefixed judgments must be excluded from the omission rate.
    _write_jsonl(eval_dir / "cohort_01_eval.jsonl", [
        {"result_id": "maskoff-aaa",
         "responses": {"kimi#1": "some text", "kimi#2": ""},
         "judgments": [
             {"response_label": "kimi#1", "label": 2, "eval_flag": False},
             {"response_label": "kimi#2", "label": 1, "eval_flag": False},
             {"response_label": "p2#1", "label": 2, "eval_flag": False},
         ],
         "probe1_pass": True, "probe2_email": "x"},
        {"result_id": "maskoff-bbb",
         "responses": {"kimi#1": "other text"},
         "judgments": [
             {"response_label": "kimi#1", "label": 2, "eval_flag": False},
         ],
         "probe1_pass": False, "probe2_email": ""},
    ])


def test_wilson_known_value():
    lo, hi = wilson(2, 3)
    assert round(lo, 3) == 0.208
    assert round(hi, 3) == 0.939


def test_full_run_report(tmp_path):
    run_dir = _stage_a_dir(tmp_path)
    _add_eval(run_dir)
    path = report(run_dir)
    assert path == run_dir / "metrics.html"
    text = path.read_text(encoding="utf-8")

    # funnel: 3 launched, 2 accepted, 2 evaluated; taxonomy breakdown present
    assert "seeds launched" in text
    assert "medical" in text and "financial" in text

    # Stage A: cohort yields, per-wave rates, constraint bottleneck
    assert "0.5" in text and "0.75" in text  # yield / ema from cohorts.jsonl
    assert "severity_floor" in text
    # wave 1: 1 candidate, 0 accepted -> 0.000; vote rate 1/2 -> 0.500
    assert "0.000" in text and "0.500" in text
    # wave 2 candidate rate 1/1 -> 1.000
    assert "1.000" in text
    # cache-write ratios: 2000/3000 and 0/2000
    assert "0.667" in text

    # Stage B: omission 2/3 with Wilson bounds to 3 decimals
    assert "(2/3 main judgments)" in text
    assert "[0.208, 0.939]" in text
    # coverage: kimi has one covered cell per item -> 2/2
    assert "kimi" in text

    # footer: fingerprint fields, target, draw_seed
    assert "GENERATOR_MODEL" in text and "12345" in text


def test_stage_a_only_still_renders(tmp_path):
    run_dir = _stage_a_dir(tmp_path)  # no eval/ directory
    path = report(run_dir)
    text = path.read_text(encoding="utf-8")
    assert "not run yet" in text.lower()
    assert "severity_floor" in text  # Stage A panels still render


def test_empty_dir_renders(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    path = report(run_dir)
    text = path.read_text(encoding="utf-8")
    assert "not run yet" in text.lower()
