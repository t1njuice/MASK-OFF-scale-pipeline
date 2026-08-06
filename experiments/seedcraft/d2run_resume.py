"""Resume the crashed d2run frozen run from server-side batch results.

Crash: 502 during run_batch_retry's resubmission of 2 errored iter-2 votes
(now fixed in llm._connection_retry). Salvage: iter-2 candidates from batch
...SCj7tHUb, 14 opus votes from ...upGSsyek; re-run the grok votes (results
were in memory) and the 2 errored opus votes; tally iter-2, then run iter-3
for survivors. Appends to the original 095805Z run log / items files.
"""

import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from mask_off import config  # noqa: E402
from mask_off.frozen_pipeline import now_iso, usage_cost, write_items_csv  # noqa: E402
from mask_off.generator import build_gen_request, parse_gen  # noqa: E402
from mask_off.llm import batch_progress, client, run_batch_retry, usage_summary_of  # noqa: E402
from mask_off.seeds import load_seeds  # noqa: E402
from mask_off.validity import build_vote_requests, parse_vote, tally  # noqa: E402

STEM = REPO / "output/frozen_8_gen-opus-4-8_gate-opus-4-8_seeds-d2run_2026-08-05_095805Z"
LOG = Path(f"{STEM}_run_log.jsonl")
ITEMS = Path(f"{STEM}_accepted.jsonl")
GEN_BATCH_SUFFIX = "SCj7tHUb"
VOTE_BATCH_SUFFIX = "upGSsyek"

log_f = open(LOG, "a", encoding="utf-8")


def log(rec):
    log_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log_f.flush()


def batch_msgs(suffix):
    c = client()
    full_id = None
    for b in c.messages.batches.list(limit=20):
        if b.id.endswith(suffix):
            full_id = b.id
            break
    assert full_id, f"batch *{suffix} not found"
    out = {}
    for entry in c.messages.batches.results(full_id):
        if entry.result.type == "succeeded":
            out[entry.custom_id] = entry.result.message
    return out


seeds = {s.name: s for s in load_seeds(HERE / "d2run")}
iter1 = {}
for line in open(LOG):
    r = json.loads(line)
    if r.get("iteration") == 1 and "accepted" in r:
        iter1[r["seed_name"]] = r
assert len(iter1) == 8, f"expected 8 iter-1 records, got {len(iter1)}"

gen_msgs = batch_msgs(GEN_BATCH_SUFFIX)
vote_msgs = batch_msgs(VOTE_BATCH_SUFFIX)
print(f"salvaged {len(gen_msgs)} iter-2 candidates, {len(vote_msgs)} opus votes")

states = []
for name, seed in seeds.items():
    cid = f"cand-{name}"
    msg = gen_msgs.get(cid)
    assert msg is not None, f"no iter-2 candidate for {name}"
    cand = parse_gen(msg)
    states.append({"seed": seed, "cid": cid, "iteration": 2, "candidate": cand,
                   "feedback": None, "previous": None, "done": False,
                   "accepted_item": None})

total_cost = sum(
    usage_cost(getattr(s["candidate"], "_llm_usage", {}) or {}) for s in states
)

# refill missing votes: all grok slots (lost in-memory) + any absent opus slots
refill = []
for s in states:
    reqs = build_vote_requests(s["cid"], s["candidate"])
    for i, req in enumerate(reqs):
        if req["custom_id"] not in vote_msgs:
            refill.append(req)
print(f"re-running {len(refill)} missing votes")
progress = batch_progress()
with progress:
    vote_msgs.update(run_batch_retry(refill, "Vote refill", progress))

    def gate(s):
        global total_cost
        votes, dumps, errors = [], [], []
        for i in range(config.VALIDITY_VOTES):
            msg = vote_msgs.get(f"{s['cid']}__vote{i}")
            if msg is None:
                errors.append("no message")
                continue
            try:
                v = parse_vote(msg)
                votes.append(v)
                dumps.append(v.model_dump())
                total_cost += usage_cost(getattr(v, "_llm_usage", {}) or {})
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))
        if not votes:
            log({"seed_name": s["seed"].name, "iteration": s["iteration"],
                 "stage": "validity", "error": "; ".join(errors), "ts": now_iso()})
            if s["iteration"] >= config.FROZEN_MAX_ITERATIONS:
                s["done"] = True
            return
        decision = tally(votes)
        log({"seed_name": s["seed"].name, "seed_source": s["seed"].source,
             "iteration": s["iteration"], "candidate": s["candidate"].model_dump(),
             "votes": dumps, "vote_errors": errors, **decision,
             "generator_model": config.GENERATOR_MODEL,
             "validity_model": config.VALIDITY_PANEL or config.VALIDITY_MODEL,
             "usage": {"generator": getattr(s["candidate"], "_llm_usage", {}) or {},
                       "votes": [getattr(v, "_llm_usage", {}) or {} for v in votes]},
             "ts": now_iso(), "resumed": True})
        if decision["accepted"]:
            item = {"result_id": f"maskoff-{uuid.uuid4().hex[:12]}",
                    "seed_name": s["seed"].name, "seed_source": s["seed"].source,
                    "iterations": s["iteration"], **s["candidate"].model_dump()}
            s["accepted_item"] = item
            s["done"] = True
            with open(ITEMS, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            progress.console.print(
                f"accepted {s['seed'].name} (iter {s['iteration']})", markup=False)
        elif decision["seed_defect"] or s["iteration"] >= config.FROZEN_MAX_ITERATIONS:
            s["done"] = True
            progress.console.print(f"exhausted {s['seed'].name}", markup=False)
        else:
            s["feedback"] = (
                "VALIDITY REVISION — the gate rejected the previous "
                "attempt on construction grounds. Diagnosis:\n"
                + (decision["feedback"]
                   or "(no parsed diagnosis; re-audit your item against every "
                      "construction constraint and rebuild the weakest element)"))
            s["previous"] = s["candidate"]

    for s in states:
        gate(s)

    # iteration 3 for survivors
    active = [s for s in states if not s["done"]]
    if active:
        for s in active:
            s["iteration"] = 3
        gen_msgs3 = run_batch_retry(
            [build_gen_request(s["cid"], s["seed"].text, [], s["feedback"],
                               s["previous"], lessons="", revision_round=2,
                               frozen=True)
             for s in active],
            "Generator iter3", progress)
        ready = []
        for s in active:
            msg = gen_msgs3.get(s["cid"])
            try:
                if msg is None:
                    raise RuntimeError("generator batch returned no message")
                s["candidate"] = parse_gen(msg)
                total_cost += usage_cost(getattr(s["candidate"], "_llm_usage", {}) or {})
                ready.append(s)
            except Exception as e:  # noqa: BLE001
                log({"seed_name": s["seed"].name, "iteration": 3,
                     "stage": "generator", "error": repr(e),
                     "stop_reason": getattr(msg, "stop_reason", None),
                     "usage": usage_summary_of(msg) if msg else {}, "ts": now_iso()})
                s["done"] = True
        vote_reqs = []
        for s in ready:
            vote_reqs += build_vote_requests(s["cid"], s["candidate"])
        vote_msgs = run_batch_retry(vote_reqs, "Validity gate iter3", progress)
        for s in ready:
            gate(s)

log_f.close()
accepted = [s["accepted_item"] for s in states if s["accepted_item"]]
print(f"\nresume done: {len(accepted)}/8 accepted this resume "
      f"(anthropic cost this script: ${total_cost:.2f})")
all_items = [json.loads(l) for l in open(ITEMS)] if ITEMS.exists() else []
write_items_csv(all_items, Path(f"{STEM}_accepted.csv"))
print(f"items: {ITEMS}")
