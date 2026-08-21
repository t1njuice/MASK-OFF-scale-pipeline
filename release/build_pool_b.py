"""Assemble the Pool B (100 items) release artifacts.

Pool B ran the 15-seat panel from the start (post-fable5-removal), so no
seat stripping is needed; this is a verified copy plus provenance. The
eval file is ~50 MB, under GitHub's 100 MB cap, so it ships unsharded.

Run from the repo root:  uv run python release/build_pool_b.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "release" / "pool_b"

CORPUS = ROOT / "output/dataset_v1b.jsonl"
EVAL = ROOT / "output/scale_v1b_eval/eval/cohort_01_eval.jsonl"
SUMMARY = ROOT / "output/scale_v1b_eval/eval/cohort_01_eval_summary.json"
POOL_A_CORPUS = ROOT / "release/pool_a/dataset_pool_a_400.jsonl"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    from mask_off import config
    panel = [seat.label for seat in config.TARGET_PANEL]

    ids, seeds = set(), set()
    rows = [json.loads(line) for line in CORPUS.open()]
    for row in rows:
        assert row["result_id"] not in ids, row["result_id"]
        assert row["seed_name"] not in seeds, row["seed_name"]
        ids.add(row["result_id"])
        seeds.add(row["seed_name"])
    assert len(rows) == 100, len(rows)

    pool_a_ids = {json.loads(l)["result_id"] for l in POOL_A_CORPUS.open()}
    assert not ids & pool_a_ids, "pool B ids overlap pool A"

    ev = {}
    for line in EVAL.open():
        row = json.loads(line)
        assert row["result_id"] in ids and row["result_id"] not in ev
        seats = {k.split("#")[0] for k in row["responses"]}
        assert seats == set(panel), seats ^ set(panel)
        ev[row["result_id"]] = row
    assert set(ev) == ids

    corpus_out = OUT / "dataset_pool_b_100.jsonl"
    corpus_out.write_bytes(CORPUS.read_bytes())
    eval_out = OUT / "pool_b_100_eval.jsonl"
    with eval_out.open("w") as f:
        for row in rows:  # corpus order
            f.write(json.dumps(ev[row["result_id"]], ensure_ascii=False) + "\n")
    summary_out = OUT / "pool_b_100_eval_summary.json"
    summary_out.write_bytes(SUMMARY.read_bytes())

    prov = {
        "built_from": {str(p.relative_to(ROOT)): sha256(p)
                       for p in (CORPUS, EVAL, SUMMARY)},
        "outputs": {p.name: sha256(p)
                    for p in (corpus_out, eval_out, summary_out)},
        "n_items": len(rows),
        "panel": panel,
        "notes": ("Pool B evaluated the 15-seat panel from the start; "
                  "eval rows copied verbatim (reordered to corpus order), "
                  "no seat stripping. Includes the 2026-08-21 --fill pass "
                  "that recovered the terra judge and probe-2 cells lost "
                  "to the pre-fix flex 429 bug."),
    }
    (OUT / "provenance.json").write_text(json.dumps(prov, indent=2))
    print(f"corpus: {corpus_out} ({len(rows)} items)")
    print(f"eval:   {eval_out} ({len(ev)} rows)")


if __name__ == "__main__":
    main()
