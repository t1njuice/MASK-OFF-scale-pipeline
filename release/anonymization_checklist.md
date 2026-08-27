# Anonymization sweep spec (2026-08-27)

The word list, whitelist, and delivery rules for every artifact that
leaves this machine for review: the anonymous repo (`../MASK-OFF`) and the
Harvard Dataverse deposit. Run the sweep over file CONTENTS of everything
shipped, including output artifacts, not just source files.

## Word list (case-insensitive substring unless noted)

| Pattern | Why |
|---|---|
| `antyabha` | author name |
| `ntyabha` | catches the diacritic form of the first name, which `antyabha` misses |
| `rahman` | author name |
| `rahmanantyabha@gmail.com` | personal email |
| `antyabha.rahman@student.unsw.edu.au` | university email |
| `z5465036` | university id |
| `unsw` | university (see whitelist) |
| `t1njuice` | github handle of the private repo |
| `/home/antyabha` | local path |
| `/Users/antyabharahman` | local path (other machine) |
| `MASK-OFF-scale-pipeline` | private repo name; links anon repo to it |
| `Downloads/Personal` / `neurips` in paths | path fragments from the other machine |
| `\bAR\b` / `\bJM\b` as rater identifiers | rater initials; must be R1/R2 (see whitelist) |
| `sk-`, `sk-ant-`, `AIza`, `ghp_`, `Bearer ` | credential shapes |

## Whitelist (confirmed benign, user-approved 2026-08-27; do not edit)

| Match | Where | Resolution |
|---|---|---|
| "unswept" (`unsw`) | `data/pool_a_items.jsonl`, item `maskoff-e46bdc272d69` ("his unswept mailbox archive") | ordinary English in a frozen item; editing would move the sha256, canary, croissant, and deposit records |
| "AR scope" (`\bAR\b`) | `data/pool_a_items.jsonl`, two occurrences | accounts-receivable, not a rater identifier; frozen item text |
| `\bAR\b` in frozen item or model-response text | corpora and run records (all instances re-adjudicated 2026-08-27, Wave 3: 101 across the full deposit, three senses, zero rater identifiers) | accounts receivable, authorized representative, USCIS form AR-11; never a rater identifier (rater fields are `labeler`, scrubbed to R1/R2) |
| "Rahman" as a model-invented character name | `evalaware_pilot20` response records | coincidental name in pilot chain-of-thought, not author metadata; staged copies carry `[REDACTED-SURNAME]` (redaction kept 2026-08-27 — pilot records are not sha-frozen release artifacts) |

## Delivery rules

1. The anon repo ships ONLY as a clone or `git archive` export (via the
   anonymous mirror of the fresh remote). Never a directory zip: the
   working directory's `.git/config`, reflog, `__pycache__/*.pyc`, and
   `.venv/` all carry identity or local paths.
2. New commits in `../MASK-OFF` require the local identity
   (`user.name Anonymous`, pinned 2026-08-27) — verify with
   `git config --local user.name` before committing.
3. No commit in `../MASK-OFF` carries a Co-Authored-By trailer: the
   private repo's public commits carry one, so reusing it is a
   cross-repo fingerprint.
4. Labeling files in the Dataverse deposit use the scrubbed R1/R2
   variants (file names, `labeler` fields, and the κ report's path
   lines); the unscrubbed originals stay in the private repo only.
5. Dataverse deposit during review: draft with real author metadata,
   shared ONLY through the anonymized private URL (verified supported,
   probe 2026-08-27); free-text metadata fields (description, related
   publication) are not auto-scrubbed by that URL and are written
   identity-free until acceptance.
6. Croissant `contentUrl` strategy (user decision 2026-08-27): after the
   deposit files upload, regenerate `croissant.json` with the Dataverse
   file URLs in place of `ANON_BASE`, revalidate with mlcroissant, and
   upload the croissant file last. The staged copy's placeholder base is
   expected until then; the deposit README says so.
