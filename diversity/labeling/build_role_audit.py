"""Build the role-audit frame: which items the human authors role-label.

Amendment 2026-08-22 (LABELING_DESIGN.md §13): the authors no longer role-label
all 150 items. The frame is a stratified audit of the two frozen judge runs:

- ``disagree``      — census: every item where the two judges disagree on any axis.
- ``agree_cell``    — census: judges fully agree AND the item is an audited cell,
                      so the author opens it anyway for response grading; the
                      three role clicks are nearly free.
- ``agree_noncell`` — seeded SRS of NONCELL_DRAW from the remaining items. All
                      sampling variance in the frame projection lives here;
                      weight_stratum = frame size / draw size.

The frame is frozen against the two named judge files (menu 75616a058466). A
judge re-run or menu change does NOT move the frame — it is a sampling frame,
not a living quantity. Rebuilding with the same inputs reproduces the file byte
for byte; readers stamp rows with file_sha12() of this file (``frame_sha``).

Usage (from the repo root):
    .venv/bin/python diversity/labeling/build_role_audit.py

Output: diversity/labeling/out/frame150/role_audit.json
"""

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from roles import AXIS_KEYS, file_sha12, menu_version  # noqa: E402

OUT_DIR = HERE / "out" / "frame150"
SAMPLE = OUT_DIR / "sample_150.jsonl"
JUDGES = [
    OUT_DIR / "judge_axes_claude-opus-4-8.jsonl",
    OUT_DIR / "judge_axes_openai_gpt-5.6-terra-pro.jsonl",
]
OUT = OUT_DIR / "role_audit.json"
SEED = 20260822
NONCELL_DRAW = 10

ROLE_AXES = [k for k in AXIS_KEYS]  # beneficiary, institution, standing


def _rows(path: Path) -> dict[str, dict]:
    return {r["result_id"]: r for r in map(json.loads, path.read_text().splitlines())}


def build() -> dict:
    sample = _rows(SAMPLE)
    ja, jb = (_rows(p) for p in JUDGES)
    assert set(sample) == set(ja) == set(jb), "sample and judge files must cover the same items"

    strata: dict[str, list[str]] = {"disagree": [], "agree_cell": [], "agree_noncell": []}
    for rid in sorted(sample):
        if any(ja[rid][k] != jb[rid][k] for k in ROLE_AXES):
            strata["disagree"].append(rid)
        elif "responses" in sample[rid]:
            strata["agree_cell"].append(rid)
        else:
            strata["agree_noncell"].append(rid)

    noncell_frame = strata["agree_noncell"]
    draw = sorted(random.Random(SEED).sample(noncell_frame, NONCELL_DRAW))

    items = []
    for stratum, ids, frame_n, draw_ids in [
        ("disagree", strata["disagree"], len(strata["disagree"]), strata["disagree"]),
        ("agree_cell", strata["agree_cell"], len(strata["agree_cell"]), strata["agree_cell"]),
        ("agree_noncell", noncell_frame, len(noncell_frame), draw),
    ]:
        w = frame_n / len(draw_ids)
        for rid in draw_ids:
            items.append(
                {
                    "result_id": rid,
                    "stratum": stratum,
                    "weight_stratum": w,
                    "weight_domain": sample[rid]["weight_domain"],
                    # product weight, for corpus-level rates only — never for kappa
                    "weight": w * sample[rid]["weight_domain"],
                }
            )

    return {
        "built": "2026-08-22",
        "seed": SEED,
        "menu_version": menu_version(),
        "sample_sha": file_sha12(SAMPLE),
        "judge_shas": {p.name: file_sha12(p) for p in JUDGES},
        "stratum_frames": {k: len(v) for k, v in strata.items()},
        "items": items,
    }


def _selfcheck(frame: dict) -> None:
    sizes = frame["stratum_frames"]
    drawn = {s: sum(1 for i in frame["items"] if i["stratum"] == s) for s in sizes}
    assert sizes["disagree"] == drawn["disagree"], "disagree stratum must be a census"
    assert sizes["agree_cell"] == drawn["agree_cell"], "agree_cell stratum must be a census"
    assert drawn["agree_noncell"] == NONCELL_DRAW
    assert sum(sizes.values()) == 150 and len({i["result_id"] for i in frame["items"]}) == len(frame["items"])
    # weight_stratum must project each stratum back to its frame size
    for s, n in sizes.items():
        tot = sum(i["weight_stratum"] for i in frame["items"] if i["stratum"] == s)
        assert abs(tot - n) < 1e-9, (s, tot, n)
    # every audited cell is in the frame by construction (disagree or agree_cell)
    sample = _rows(SAMPLE)
    in_frame = {i["result_id"] for i in frame["items"]}
    cells = {rid for rid, r in sample.items() if "responses" in r}
    assert cells <= in_frame, f"{len(cells - in_frame)} audited cells missing from the frame"
    print(f"all {len(cells)} audited cells are inside the role frame")


if __name__ == "__main__":
    frame = build()
    _selfcheck(frame)
    OUT.write_text(json.dumps(frame, indent=1) + "\n")
    print(f"wrote {OUT} frame_sha={file_sha12(OUT)}")
    print(f"strata frames: {frame['stratum_frames']}  drawn: {len(frame['items'])} items")
