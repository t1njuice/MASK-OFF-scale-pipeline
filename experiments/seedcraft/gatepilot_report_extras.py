"""Report extras for the gate pilot: per-arm cost split (generator vs each
voter), forwarded-feedback share, persuadability, and representative
diagnoses per panel voter.

Pricing: actual transport — control opus = Anthropic batch (incl. cache
fields at batch rates); pilot opus = OpenRouter sync $5/$25 with cache reads
at 10% of input (Anthropic's discount, passed through); kimi 3/15, grok 2/6,
sol 5/30 with cache reads priced at FULL input rate (no documented discount —
conservative upper bound). Log-derived numbers are lower bounds: calls that
errored or were killed in flight billed without leaving usage records.

Usage: python gatepilot_report_extras.py LABEL=RUN_STEM ...
"""

import json
import sys
from collections import Counter, defaultdict


def price_of(model):
    m = str(model or "")
    if m.startswith("anthropic/"):
        return {"in": 5.0, "out": 25.0, "cw": 6.25, "cr": 0.5}
    if m.startswith("claude"):
        return {"in": 2.5, "out": 12.5, "cw": 5.0, "cr": 0.25}
    if "kimi" in m:
        return {"in": 3.0, "out": 15.0, "cw": 3.0, "cr": 3.0}
    if "grok" in m:
        return {"in": 2.0, "out": 6.0, "cw": 2.0, "cr": 2.0}
    if "sol" in m:
        return {"in": 5.0, "out": 30.0, "cw": 5.0, "cr": 5.0}
    return {"in": 0, "out": 0, "cw": 0, "cr": 0}


def cost(u, model=None):
    p = price_of(model or u.get("model"))
    return (
        u.get("input_tokens", 0) * p["in"]
        + u.get("output_tokens", 0) * p["out"]
        + u.get("cache_creation_input_tokens", 0) * p["cw"]
        + u.get("cache_read_input_tokens", 0) * p["cr"]
    ) / 1e6


def who(model):
    m = str(model or "?")
    for k in ("kimi", "grok", "sol"):
        if k in m:
            return k
    return "opus" if "claude" in m else m


def main():
    quotes = defaultdict(dict)
    for spec in sys.argv[1:]:
        label, stem = spec.split("=", 1)
        recs = [json.loads(l) for l in open(f"{stem}_run_log.jsonl")]
        rounds = [r for r in recs if "votes" in r]
        acc_items = []
        try:
            acc_items = [json.loads(l) for l in open(f"{stem}_accepted.jsonl")]
        except FileNotFoundError:
            pass
        n_acc = len(acc_items)

        split = Counter()
        fwd = Counter()          # whose diagnosis was forwarded per revise round
        verdicts = defaultdict(dict)  # (voter, seed) -> {iter: verdict}
        for r in rounds:
            g = r["usage"]["generator"]
            split["generator"] += cost(g, g.get("model") or r.get("generator_model") or "claude")
            for v, u in zip(r["votes"], r["usage"]["votes"]):
                w = who(u.get("model"))
                split[f"vote:{w}"] += cost(u)
                verdicts[(w, r["seed_name"])][r["iteration"]] = v["verdict"]
                if (not r["accepted"] and r["feedback"]
                        and v["verdict"] != "accept"
                        and v["feedback"] == r["feedback"]):
                    fwd[w] += 1
                    quotes[w].setdefault(label, v["feedback"])
        for r in recs:
            if "votes" not in r and r.get("usage"):
                split["generator"] += cost(r["usage"], "claude")

        total = sum(split.values())
        n_fwd = sum(fwd.values())
        # persuadability: voter revised seed at some iter, accepted it later
        pers = {}
        for w in {k[0] for k in verdicts}:
            flipped = revised = 0
            for (w2, seed), by_iter in verdicts.items():
                if w2 != w:
                    continue
                its = sorted(by_iter)
                first_rev = next((i for i in its if by_iter[i] == "revise"), None)
                if first_rev is None:
                    continue
                revised += 1
                if any(by_iter[i] == "accept" for i in its if i > first_rev):
                    flipped += 1
            pers[w] = (flipped, revised)

        parts = ", ".join(f"{k.split(':')[-1]}=${v:.2f}" for k, v in split.most_common())
        per_item = f"${total/n_acc:.2f}/item" if n_acc else "n/a"
        print(f"[{label}] total=${total:.2f} ({per_item}, {n_acc} items)  {parts}")
        if n_fwd:
            fwd_s = ", ".join(f"{k}={v} ({v/n_fwd:.0%})" for k, v in fwd.most_common())
            print(f"    forwarded diagnoses ({n_fwd}): {fwd_s}")
        pers_s = ", ".join(
            f"{w}={f}/{r} ({f/r:.0%})" for w, (f, r) in sorted(pers.items()) if r
        )
        print(f"    persuadability (revised->later accepted): {pers_s}")

    print("\n-- representative forwarded diagnoses --")
    for w in sorted(quotes):
        label, text = next(iter(quotes[w].items()))
        first = " ".join(text.split("\n")[:3])[:400]
        print(f"[{w}] (from {label}): {first}")


if __name__ == "__main__":
    main()
