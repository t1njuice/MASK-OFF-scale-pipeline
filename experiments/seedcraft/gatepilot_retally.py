"""Gate pilot P5 re-tally (no API calls): scalar rule over existing run logs.

Rule: the run's own acceptance (2-of-3, or 2-of-2 for P3) EXCEPT any item whose
Grok vote scores inference-distance S+C = 0 is rejected outright. Grok's
inference_distance notes state the count ("S+C = 0" and variants); notes that
don't parse are reported, not guessed.

Usage: python experiments/seedcraft/gatepilot_retally.py <run_log.jsonl> ...
"""

import json
import re
import sys

# "S+C = 0", "S+C: 1", and the bound form "S+C ≤ 1" / "<= 1" all occur.
SC_RE = re.compile(r"S\s*\+\s*C\s*(=|:|≤|<=|<)\s*(\d+)", re.IGNORECASE)


def grok_sc(rec):
    """(s_plus_c | None, had_grok_vote) for one decision round.

    A bound "≤ N" asserts S+C = 0 only when N is 0 ("< N" only when N is 1);
    a looser bound did not score 0, so the rule can't fire — return the bound
    value (nonzero) so callers treat it as parsed-but-not-zero.
    """
    for vote, usage in zip(rec["votes"], rec["usage"]["votes"]):
        if "grok" not in str(usage.get("model", "")):
            continue
        note = vote["constraints"]["inference_distance"]["note"]
        m = SC_RE.search(note)
        if not m:
            return None, True
        op, val = m.group(1), int(m.group(2))
        if op in ("≤", "<="):
            return val, True  # val==0 -> exact 0; else a nonzero bound
        if op == "<":
            return (0 if val == 1 else val), True
        return val, True
    return None, False


def retally(path):
    recs = [json.loads(l) for l in open(path)]
    rounds = [r for r in recs if "votes" in r]
    seeds = {r["seed_name"] for r in rounds}
    plain, p5, removed, unparseable, no_grok = [], [], [], [], []
    for r in rounds:
        if not r["accepted"]:
            continue
        plain.append(r["seed_name"])
        sc, had = grok_sc(r)
        if not had:
            no_grok.append(r["seed_name"])
            p5.append(r["seed_name"])  # no grok vote -> rule can't fire
        elif sc is None:
            unparseable.append(r["seed_name"])
            p5.append(r["seed_name"])  # unparseable -> not rejected, reported
        elif sc == 0:
            removed.append(r["seed_name"])
        else:
            p5.append(r["seed_name"])
    # unparseable count across ALL grok votes in the log, not just accepts
    all_notes = sum(1 for r in rounds if grok_sc(r)[1])
    all_unparsed = sum(1 for r in rounds if grok_sc(r) == (None, True))
    return {
        "log": path,
        "n_seeds": len(seeds),
        "plain_accepted": sorted(plain),
        "p5_accepted": sorted(p5),
        "removed": sorted(removed),
        "accept_round_unparseable": sorted(unparseable),
        "accept_round_no_grok_vote": sorted(no_grok),
        "grok_notes_total": all_notes,
        "grok_notes_unparseable": all_unparsed,
    }


def main():
    for path in sys.argv[1:]:
        r = retally(path)
        print(f"\n=== {r['log']}")
        print(
            f"plain yield {len(r['plain_accepted'])}/{r['n_seeds']}"
            f"  ->  P5 yield {len(r['p5_accepted'])}/{r['n_seeds']}"
        )
        print(f"removed by S+C=0 rule ({len(r['removed'])}): {r['removed']}")
        print(
            f"grok notes unparseable: {r['grok_notes_unparseable']}"
            f"/{r['grok_notes_total']}"
            + (
                f" (on accepting rounds: {r['accept_round_unparseable']})"
                if r["accept_round_unparseable"]
                else ""
            )
        )
        if r["accept_round_no_grok_vote"]:
            print(f"accepting rounds with no grok vote: {r['accept_round_no_grok_vote']}")


if __name__ == "__main__":
    main()
