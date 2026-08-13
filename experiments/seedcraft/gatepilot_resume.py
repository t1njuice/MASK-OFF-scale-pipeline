"""Resume an interrupted gate-pilot arm from its run log (no paid round redone).

Rebuilds per-seed state from the arm's existing `_run_log.jsonl` — iteration
count = parsed decision rounds (waves that errored without billing don't
consume an iteration), feedback/previous from the last parsed round — then
continues `run()` appending to the SAME log and accepted files. Accepted and
seed-defect-killed seeds stay done.

Usage: python experiments/seedcraft/gatepilot_resume.py <arm: p1|p2|p3|p4|p6|p7>
"""

import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

ARM = sys.argv[1]
EXTERNAL = ["moonshotai/kimi-k3", "x-ai/grok-4.5", "openai/gpt-5.6-sol"]
# (panel, votes, accept, n_seeds, max_iterations)
PANELS = {
    "p1": (["anthropic/claude-opus-4.8", "moonshotai/kimi-k3", "x-ai/grok-4.5"], 3, 2, 19, 5),
    "p2": (["anthropic/claude-opus-4.8", "x-ai/grok-4.5", "openai/gpt-5.6-sol"], 3, 2, 19, 5),
    "p3": (["anthropic/claude-opus-4.8", "x-ai/grok-4.5"], 2, 2, 19, 5),
    "p4": (["openai/gpt-5.6-sol", "x-ai/grok-4.5", "moonshotai/kimi-k3"], 3, 3, 10, 5),
    # post-fix arms: slot order must match gatepilot_p6/p7.py, because the
    # anonymous reviewer letters in the forwarded feedback are keyed to it
    "p6": (EXTERNAL, 3, 2, 19, 10),
    "p7": (EXTERNAL, 3, 3, 10, 10),
}
panel, votes, accept, n_seeds, max_iters = PANELS[ARM]

from mask_off import config  # noqa: E402

config.GENERATOR_MODEL = "anthropic/claude-opus-4.8"  # OpenRouter sync
config.VALIDITY_MODEL = "claude-opus-4-8"  # stem/fallback only
config.VALIDITY_PANEL = panel
config.VALIDITY_VOTES = votes
config.VALIDITY_ACCEPT = accept
config.FROZEN_MAX_ITERATIONS = max_iters  # must match the arm, or the done-cap below lies
config.GENERATOR_LINT = ARM in {"p6", "p7"}  # the fix arms only

from mask_off.frozen_pipeline import run, write_items_csv  # noqa: E402
from mask_off.pipeline import preflight  # noqa: E402
from mask_off.schemas import Candidate  # noqa: E402
from mask_off.seeds import load_seeds  # noqa: E402

SEEDS = REPO / "experiments/seedcraft/e2e20"
load_seeds(SEEDS)
if not preflight():
    sys.exit(1)

log_path = Path(sorted(glob.glob(f"{REPO}/output/gatepilot_{ARM}_*_run_log.jsonl"))[-1])
stem = Path(str(log_path).removesuffix("_run_log.jsonl"))
items_path = stem.with_name(stem.name + "_accepted.jsonl")

rounds_by_seed: dict[str, list[dict]] = {}
for line in open(log_path):
    r = json.loads(line)
    if "votes" in r:
        rounds_by_seed.setdefault(r["seed_name"], []).append(r)

resume = {}
for seed, rounds in rounds_by_seed.items():
    last = max(rounds, key=lambda r: r["iteration"])
    n_parsed = len({r["iteration"] for r in rounds})
    if (any(r["accepted"] for r in rounds) or last["seed_defect"]
            or n_parsed >= config.FROZEN_MAX_ITERATIONS):
        # exhausted seeds are done — without this cap a supervisor relaunch
        # grants every unaccepted seed one extra wave per relaunch, unbounded
        resume[seed] = {"done": True}
        continue
    resume[seed] = {
        "iteration": n_parsed,  # errored (unbilled) waves don't consume a round
        "feedback": (
            "VALIDITY REVISION — the gate rejected the previous "
            "attempt on construction grounds. Diagnosis:\n"
            + (last["feedback"] or "(no parsed diagnosis; re-audit your item "
               "against every construction constraint and rebuild the "
               "weakest element)")
        ),
        "previous": Candidate(**last["candidate"]),
    }

print(f"{ARM}: resuming {sum(1 for v in resume.values() if not v.get('done'))} "
      f"seeds ({sum(1 for v in resume.values() if v.get('done'))} already done) "
      f"-> {log_path.name}")
accepted, _ = run(n_seeds, SEEDS, stem, log_path=log_path,
                  items_path=items_path, resume=resume)
all_items = [json.loads(l) for l in open(items_path)] if items_path.exists() else []
write_items_csv(all_items, stem.with_name(stem.name + "_accepted.csv"))
