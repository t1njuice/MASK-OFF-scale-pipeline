"""Sum estimated API cost from run-log usage records.

    python -m mask_off.cost_report output/frozen_*_run_log.jsonl
"""
import json
import sys

# batch-discounted $/MTok, opus-tier (4.8 and 5 share pricing)
P = {"input_tokens": 2.5, "output_tokens": 12.5,
     "cache_creation_input_tokens": 5.0, "cache_read_input_tokens": 0.25}


def cost(u: dict) -> float:
    return sum(u.get(k, 0) * p for k, p in P.items()) / 1e6


def walk(node):
    """Yield every dict that looks like a usage block."""
    if isinstance(node, dict):
        if "output_tokens" in node and "input_tokens" in node:
            yield node
        else:
            for v in node.values():
                yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def main():
    total = 0.0
    n = 0
    for path in sys.argv[1:]:
        sub = 0.0
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            rec = json.loads(line)
            for u in walk(rec.get("usage", {})):
                sub += cost(u)
                n += 1
        print(f"{path}: ${sub:.2f}")
        total += sub
    print(f"TOTAL (logged usage blocks: {n}): ${total:.2f}")


if __name__ == "__main__":
    main()
