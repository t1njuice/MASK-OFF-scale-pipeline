"""Reproduce every figure in docs/evidence/README.md from the two run logs.

Run it as a check, not as a report:

    uv run python docs/evidence/summarize.py

It asserts each published figure and exits non-zero if a log ever stops
matching its README row.
"""

import datetime
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def records(name: str) -> list[dict]:
    lines = (HERE / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def hours(rows: list[dict], start: str, end: str) -> float:
    fmt = datetime.datetime.fromisoformat
    return (fmt(end) - fmt(start)).total_seconds() / 3600


def p6() -> dict:
    rows = records("p6_gate_pilot_run_log.jsonl")
    decisions = [r for r in rows if "accepted" in r]
    # A lint record shares its wave with a decision record, so count waves by
    # (seed, iteration) over every record except the lint ones.
    waves = {(r["seed_name"], r["iteration"]) for r in rows if r.get("stage") != "lint"}
    seeds = {r["seed_name"] for r in rows}
    accepted = {r["seed_name"] for r in decisions if r["accepted"]}
    never = seeds - accepted
    last_accept = max(r["ts"] for r in decisions if r["accepted"])
    return {
        "records": len(rows),
        "waves": len(waves),
        "seeds": len(seeds),
        "accepted": len(accepted),
        "never_accepted": len(never),
        "waves_on_never_accepted": sum(1 for seed, _ in waves if seed in never),
        "latest_accepting_wave": max(r["iteration"] for r in decisions if r["accepted"]),
        "hours_total": hours(rows, rows[0]["ts"], rows[-1]["ts"]),
        "hours_after_last_accept": hours(rows, last_accept, rows[-1]["ts"]),
    }


def frozen_19() -> dict:
    blocks = []
    for row in records("frozen_19_run_log.jsonl"):
        usage = row.get("usage") or {}
        if "generator" in usage:  # decision record: generator plus panel votes
            blocks += [u for u in [usage["generator"], *usage.get("votes", [])] if u]
        elif usage:  # error record: one flat usage dict
            blocks.append(usage)
    total = lambda field: sum(b.get(field, 0) for b in blocks)  # noqa: E731
    return {
        "usage_blocks": len(blocks),
        "output_tokens": total("output_tokens"),
        "input_tokens": total("input_tokens"),
        "cache_write_tokens": total("cache_creation_input_tokens"),
        "cache_read_tokens": total("cache_read_input_tokens"),
    }


PUBLISHED_P6 = {
    "records": 103,
    "waves": 102,
    "seeds": 19,
    "accepted": 14,
    "never_accepted": 5,
    "waves_on_never_accepted": 50,
    "latest_accepting_wave": 6,
}
PUBLISHED_FROZEN_19 = {
    "usage_blocks": 186,
    "output_tokens": 2_517_397,
    "input_tokens": 736_419,
    "cache_write_tokens": 437_066,
    "cache_read_tokens": 2_879_996,
}
# claude-opus-4-8 on anthropic_batch, $/MTok, as pinned in config.PRICES.
OPUS_48_BATCH = {
    "output_tokens": 12.5,
    "input_tokens": 2.5,
    "cache_write_tokens": 5.0,
    "cache_read_tokens": 0.25,
}


def main() -> None:
    measured_p6, measured_frozen = p6(), frozen_19()
    for name, value in {**measured_p6, **measured_frozen}.items():
        print(f"{name:26} {value:,.2f}" if isinstance(value, float) else f"{name:26} {value:,}")
    for measured, published in ((measured_p6, PUBLISHED_P6),
                                (measured_frozen, PUBLISHED_FROZEN_19)):
        for name, expected in published.items():
            assert measured[name] == expected, (
                f"{name}: log says {measured[name]}, README says {expected}"
            )
    # Output tokens are 87% of the bill at the pinned opus-4-8 batch rates.
    dollars = {
        field: measured_frozen[field] * rate / 1e6
        for field, rate in OPUS_48_BATCH.items()
    }
    bill = sum(dollars.values())
    for field, amount in dollars.items():
        print(f"{'$ ' + field:26} {amount:,.2f}")
    print(f"{'$ total':26} {bill:,.2f}")
    assert round(dollars["output_tokens"], 2) == 31.47
    assert round(dollars["input_tokens"], 2) == 1.84
    assert round(bill, 2) == 36.21
    assert round(dollars["output_tokens"] / bill, 2) == 0.87
    print("\nevery published figure reproduced")


if __name__ == "__main__":
    main()
