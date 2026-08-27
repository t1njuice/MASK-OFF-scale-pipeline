"""The appendix text-metric battery: Self-BLEU, POS compression ratio,
Vendi Score, Hill numbers (q=0/1/2) over taxonomy and extracted entities.

    uv run --env-file .env \
        --with 'spacy>=3.8,<3.9' \
        --with https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl \
        python diversity/text_battery.py A=<a.jsonl> B=<b.jsonl> [--out prefix]

Reports every metric per pool and pooled, on `system_prompt` and
`user_email` separately (ANALYSIS_PLAN.md §9). Pooled text-metric gains
are a stimulus-construction artifact (159.5- vs 61.2-word prompts), and
the caption must say so — this script only prints the numbers.

Size sensitivity: Self-BLEU and Vendi depend on N, so the A column is
also reported rarefied to |B| (mean over draws), the same move
compare_sets.py makes for coverage. The external matched-N baseline row
(Enron; ticket 008) was closed out of scope 2026-08-27: Vendi and
Self-BLEU are out of the paper, so no baseline is computed.

Method notes, so the appendix can state them:
- Self-BLEU: for each item, BLEU-4 of the item against all other items
  in the set as references (clipped n-gram precision, uniform 1-4-gram
  weights). Brevity penalty omitted: with hundreds of references the
  closest reference length approximates the candidate's, so BP ~= 1.
  Higher = more mutual overlap = less diverse.
- POS compression ratio: zlib level 9 over the space-joined coarse POS
  tag sequence of the whole set, raw/compressed bytes. Higher = more
  repeated syntactic frames. (Shaib et al. 2024's CR, on POS tags.)
- Vendi Score: exp of the von Neumann entropy of the cosine-similarity
  kernel of L2-normalized OpenAI text-embedding-3-small embeddings.
  Units: effective number of distinct items.
- Entities: spaCy en_core_web_sm PERSON/ORG spans over system_prompt +
  user_email, lowercased; Hill q=0 (distinct), q=1 (exp Shannon),
  q=2 (inverse Simpson).
"""
import hashlib
import json
import math
import os
import re
import sys
import zlib
from collections import Counter
from pathlib import Path

import numpy as np

FIELDS = ("system_prompt", "user_email")
EMBED_MODEL = "text-embedding-3-small"
CACHE = Path("output/.text_battery_embed_cache.jsonl")
RAREFY_DRAWS = 20
RNG_SEED = 7


# --- Hill numbers -----------------------------------------------------------

def hill(counts: Counter, q: float) -> float:
    n = sum(counts.values())
    if not n:
        return 0.0
    p = [c / n for c in counts.values() if c]
    if q == 0:
        return float(len(p))
    if q == 1:
        return math.exp(-sum(x * math.log(x) for x in p))
    return sum(x ** q for x in p) ** (1.0 / (1.0 - q))


# --- Self-BLEU --------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def self_bleu(texts: list[str], max_n: int = 4) -> float:
    """Mean over items of BLEU(item | all other items). Top-2 trick: the
    reference max count for an n-gram, excluding the candidate itself, is
    the global max unless the candidate holds it alone, then the second
    max."""
    docs = [_tokens(t) for t in texts]
    per_doc_logs = [[] for _ in docs]
    for n in range(1, max_n + 1):
        grams = [Counter(tuple(d[i:i + n]) for i in range(len(d) - n + 1))
                 for d in docs]
        best: dict[tuple, tuple[int, int, int]] = {}  # g -> (max, argmax, second)
        for di, g in enumerate(grams):
            for gram, c in g.items():
                m, am, s = best.get(gram, (0, -1, 0))
                if c > m:
                    best[gram] = (c, di, m)
                elif c > s:
                    best[gram] = (m, am, c)
        for di, g in enumerate(grams):
            total = sum(g.values())
            if not total:
                per_doc_logs[di].append(None)
                continue
            clipped = 0
            for gram, c in g.items():
                m, am, s = best[gram]
                ref_max = s if am == di else m
                clipped += min(c, ref_max)
            p = clipped / total
            per_doc_logs[di].append(math.log(p) if p > 0 else None)
    scores = []
    for logs in per_doc_logs:
        if any(l is None for l in logs):
            scores.append(0.0)
        else:
            scores.append(math.exp(sum(logs) / len(logs)))
    return float(np.mean(scores))


# --- POS compression ratio ---------------------------------------------------

def pos_compression_ratio(pos_seqs: list[list[str]]) -> float:
    blob = "\n".join(" ".join(seq) for seq in pos_seqs).encode()
    return len(blob) / len(zlib.compress(blob, 9))


# --- Embeddings + Vendi -------------------------------------------------------

def _load_cache() -> dict:
    cache = {}
    if CACHE.exists():
        for line in CACHE.open():
            row = json.loads(line)
            cache[row["k"]] = row["v"]
    return cache


def embed(texts: list[str]) -> np.ndarray:
    from urllib.request import Request, urlopen
    key = os.environ["OPENAI_API_KEY"]
    cache = _load_cache()
    keys = [hashlib.sha256((EMBED_MODEL + "\x00" + t).encode()).hexdigest()
            for t in texts]
    missing = sorted({k for k, t in zip(keys, texts) if k not in cache})
    by_key = {k: t for k, t in zip(keys, texts)}
    with CACHE.open("a") as out:
        for i in range(0, len(missing), 100):
            chunk = missing[i:i + 100]
            req = Request(
                "https://api.openai.com/v1/embeddings",
                data=json.dumps({"model": EMBED_MODEL,
                                 "input": [by_key[k] for k in chunk]}).encode(),
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            data = json.load(urlopen(req))
            for k, row in zip(chunk, data["data"]):
                cache[k] = row["embedding"]
                out.write(json.dumps({"k": k, "v": row["embedding"]}) + "\n")
    mat = np.array([cache[k] for k in keys])
    return mat / np.linalg.norm(mat, axis=1, keepdims=True)


def vendi(x: np.ndarray) -> float:
    k = (x @ x.T) / len(x)
    lam = np.linalg.eigvalsh(k)
    lam = lam[lam > 1e-12]
    return float(np.exp(-np.sum(lam * np.log(lam))))


# --- main ---------------------------------------------------------------------

def load(spec: str) -> list[dict]:
    return [json.loads(line)
            for p in spec.split(",") for line in open(p)]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sets = {}
    for a in args:
        name, _, paths = a.partition("=")
        sets[name] = load(paths)
    if sorted(sets) != ["A", "B"]:
        sys.exit("usage: text_battery.py A=<a.jsonl,...> B=<b.jsonl,...>")
    pooled = sets["A"] + sets["B"]
    rng = np.random.default_rng(RNG_SEED)
    nb = len(sets["B"])

    import spacy
    nlp = spacy.load("en_core_web_sm")

    report = {"n": {"A": len(sets["A"]), "B": nb, "pooled": len(pooled)},
              "method": {"embed_model": EMBED_MODEL,
                         "self_bleu": "BLEU-4, no BP, item vs rest",
                         "pos_cr": "zlib -9 over coarse POS tags",
                         "rarefy_draws": RAREFY_DRAWS}}

    # POS + entities in one spaCy pass per item
    pos, ents = {}, {}
    for name, rows in [("A", sets["A"]), ("B", sets["B"])]:
        pos[name], ents[name] = [], Counter()
        for r in rows:
            fields = {}
            for f in FIELDS:
                doc = nlp(r.get(f) or "")
                fields[f] = [t.pos_ for t in doc if not t.is_space]
                for e in doc.ents:
                    if e.label_ in ("PERSON", "ORG"):
                        ents[name][(e.label_, e.text.lower().strip())] += 1
            pos[name].append(fields)

    # text metrics per field per set
    for f in FIELDS:
        texts = {n: [r.get(f) or "" for r in sets[n]] for n in ("A", "B")}
        texts["pooled"] = texts["A"] + texts["B"]
        emb = {n: embed(texts[n]) for n in texts}
        block = {}
        for n in ("A", "B", "pooled"):
            block[n] = {
                "self_bleu": round(self_bleu(texts[n]), 4),
                "pos_cr": round(pos_compression_ratio(
                    [d[f] for d in (pos["A"] + pos["B"]
                                    if n == "pooled" else pos[n])]), 4),
                "vendi": round(vendi(emb[n]), 2),
                "vendi_ratio": round(vendi(emb[n]) / len(texts[n]), 4),
            }
        # A rarefied to |B|
        sb, vd = [], []
        for _ in range(RAREFY_DRAWS):
            idx = rng.choice(len(texts["A"]), size=nb, replace=False)
            sb.append(self_bleu([texts["A"][i] for i in idx]))
            vd.append(vendi(emb["A"][idx]))
        block["A_rarefied_to_B"] = {"self_bleu": round(float(np.mean(sb)), 4),
                                    "vendi": round(float(np.mean(vd)), 2)}
        report[f] = block

    # Hill numbers: taxonomy and entities
    def hills(counts):
        return {f"q{q}": round(hill(counts, q), 2) for q in (0, 1, 2)}

    tax = {n: Counter(r.get("taxonomy", "?") for r in rows)
           for n, rows in [("A", sets["A"]), ("B", sets["B"]),
                           ("pooled", pooled)]}
    report["taxonomy_hill"] = {n: hills(c) for n, c in tax.items()}
    ents["pooled"] = ents["A"] + ents["B"]
    report["entity_hill"] = {
        n: {"person": hills(Counter({k: v for k, v in c.items()
                                     if k[0] == "PERSON"})),
            "org": hills(Counter({k: v for k, v in c.items()
                                  if k[0] == "ORG"}))}
        for n, c in ents.items()}

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
