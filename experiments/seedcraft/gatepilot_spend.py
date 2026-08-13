"""One-line cumulative spend for the gate pilot (spend guard).

Sums usage records across all gatepilot_p* run logs. Opus runs via the
OpenRouter slug at sync prices; sunk cost from the canceled batch attempts
is a constant. Prints: `spend=$X.XX (sunk=$Y.YY, live=$Z.ZZ)`.
"""

import glob
import json

# $/MTok
SYNC = {
    "anthropic/": {"in": 5.0, "out": 25.0},   # opus sync via OpenRouter
    "kimi": {"in": 3.0, "out": 15.0},
    "grok": {"in": 2.0, "out": 6.0},
    "sol": {"in": 5.0, "out": 30.0},
    "claude": {"in": 2.5, "out": 12.5},        # native batch (not used post-switch)
}
# 2026-08-12: 59 completed generator calls in canceled batch attempts @ ~$0.154
SUNK = 9.10


def cost(u: dict) -> float:
    m = str(u.get("model") or "anthropic/")
    p = next((v for k, v in SYNC.items() if k in m or m.startswith(k)), None)
    if p is None:
        p = SYNC["claude"] if m.startswith("claude") else {"in": 0, "out": 0}
    return (u.get("input_tokens", 0) * p["in"] + u.get("output_tokens", 0) * p["out"]) / 1e6


def main():
    live = 0.0
    for path in glob.glob("output/gatepilot_p*_run_log.jsonl"):
        for line in open(path):
            r = json.loads(line)
            if "usage" not in r:
                continue
            u = r["usage"]
            if "generator" in u:  # decision round
                g = dict(u["generator"])
                g.setdefault("model", "anthropic/")
                live += cost(g)
                live += sum(cost(v) for v in u["votes"])
            else:  # error round: generator usage, flat
                live += cost({**u, "model": "anthropic/"})
    print(f"spend=${SUNK + live:.2f} (sunk=${SUNK:.2f}, live=${live:.2f})")


if __name__ == "__main__":
    main()
