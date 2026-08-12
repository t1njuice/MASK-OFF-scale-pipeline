# Start here — author labeling

Two authors label the same items independently. The agreement score between the
two of you is the number the paper reports, so the protocol matters as much as
the labels.

Design and rationale: [LABELING_DESIGN.md](LABELING_DESIGN.md).

## The five rules

1. **Label independently.** Do not discuss items, compare picks, or open the other
   author's file until both files are complete and `kappa.py` has run. The score
   is computed before any adjudication.
2. **Read each list from the top. Take the first line that is true.** The lists run
   most specific first. The last line before *Other* is the residual.
3. **Never edit a saved row.** To redo one item, delete that one line from your own
   file. Nothing else rewrites rows.
4. **Stop on a red STOPPED line.** It means your file, the code, or the sample
   disagree. Fix that before you label. Do not work around it.
5. **Commit your own file after every session.** Never run `git checkout` over it.

**One sample per directory.** Your rater file is named from your initials, so two
sample files in one directory would both map to `author_<initials>.jsonl` and the
stamp guard would stop you. Each sample gets its own directory.

## The sweep — roles, then responses, in one pass

```bash
.venv/bin/marimo edit diversity/labeling/author_notebook.py
```

Set the sample file, type your initials, label. Two phases per item:

1. **Roles.** Read the system prompt and the email, pick the three axes, save.
2. **Responses** — audited items only. The hidden fact and all three responses
   appear together. Label each one, save. You may compare the three; the design
   expects it and the statistics account for it.

The hidden fact never appears during phase 1. If it did, it would contaminate the
role labels.

Two output files, `<sample dir>/author_<initials>.jsonl` and
`author_responses_<initials>.jsonl`. Both resume, and an item interrupted between
the two phases is served phase 2 first on the next launch. A break banner appears
every 40 screens; it never blocks a save.

Pilot samples, built and ready. Pilot labels calibrate the surface; they do not
bind the paper.

| File | Contents |
|---|---|
| `out/pilot/sample_26.jsonl` (`180e77dc156e`) | 26 items, roles only, 30 to 45 min |
| `out/pilot_combined/sample_26.jsonl` (`b547995d3b52`) | the same 26 items, 9 of them carrying 3 responses each |

## Building the sample

Roles only:

```bash
.venv/bin/python diversity/labeling/sample.py items -n 300 <accepted.jsonl...> --out diversity/labeling/out/sample_300.jsonl
```

Roles plus the audited responses, one file (needs the Stage B eval output):

```bash
.venv/bin/python diversity/labeling/sample.py items -n 300 <accepted.jsonl...> --with-responses <eval.jsonl...> --cells 100 --out diversity/labeling/out/sample_300.jsonl
```

The audited rows carry `weight_domain`, `weight_stratum`, and their product
`weight`. Use `weight` for any corpus rate. Never use it for kappa.

`response_notebook.py` grades responses alone, one per screen, for the case where
the roles are already done. The sweep above replaces it in normal use.

## Score the agreement

```bash
.venv/bin/python diversity/labeling/kappa.py diversity/labeling/out/pilot/*.jsonl
```

Read the output in this order:

1. **Cohen's κ per axis** — the gate. 0.80 passes, 0.67 to 0.80 passes with a
   "tentative" caveat, below 0.67 fails.
2. **The confusion pairs under each axis.** A pair marked `<-- OVERLAP` holds 30%
   or more of that axis's disagreements. That is a menu problem, not rater noise.
   On the response file the interval is computed by resampling **items**, not
   responses, because the three responses of an item are graded together.
3. **PABAK, α, and the sentence-level κ** — reported, never the gate. The sentence
   spans 168 cells, so its κ reads low by construction.

`kappa.py` refuses to compare two files whose `menu_version` or `sample_sha`
disagree, and refuses any file with a duplicate `result_id`.

## Files

| Path | What it is |
|---|---|
| `roles.py` | The label menu. Single source of truth for both notebooks, the judge, and κ. |
| `sample.py` | Builds a frozen sample file. `items` for the sweep, `cells` for a responses-only pass. |
| `author_notebook.py` | The sweep: role axes, then responses. |
| `response_notebook.py` | Standalone response grading, for a responses-only pass. |
| `hill.py` | Role-facet diversity numbers: per-axis coverage, effective options, joint grid. |
| `judge_labels.py` | Runs a model over the same sample, for judge-vs-author κ. |
| `kappa.py` | Agreement statistics and the overlap diagnostic. |
| `out/pilot/` | Roles-only pilot sample and its labels. Never pooled with the binding run. |
| `out/pilot_combined/` | Combined-sweep pilot. One sample per directory: the rater file is named from the initials, so two samples in one directory would collide. |
| `out/flat13_archive/` | Dead flat-13 scheme. Historical only. |
| `out/prev_menu_archive/` | Judge labels from before the 2026-08-12 ordered-list refinement. |

## If something looks wrong

The stamps on each row (`labeler`, `menu_version`, `sample_sha`) say which rater,
which menu, and which sample produced it. Read them first — they usually name the
problem. Do not delete a file to make an error go away; move it to an archive
directory with a note.
