# Teaching notes

- User is a co-author of the frozen design — expert on content, needs *fluency and triage drill*, not introduction. Pitch lessons as decision drills against the frozen doc.
- Ponytail mode active in this workspace: keep prose terse, reference-first.
- 2026-08-01: workspace scaffolded; Lesson 0001 = experiment map + ablation triage.
- Strong preference: define every term before first use; no unexplained jargon (Probe 2, label 2, etc.). Readability beats compression — applied to the shared-understanding doc itself (readability rewrite, decisions unchanged).
- 2026-08-14: the workspace files (lessons, assets, reference, NOTES, RESOURCES, learning-records) were dropped by the `clean-trunk` cut. Restored from the `.claude/worktrees/diversity-20-construction-e33e67` worktree and from commit `228c7ed`. If they vanish again, restore from there before writing a lesson.
- 2026-08-14: the user asks implementation questions ("what is implemented, what does it measure, what is the procedure"), not concept questions. Lessons should map code paths to claims and end in a command ladder. Cite `file:line`.
- 2026-08-14: state the unimplemented parts explicitly in every lesson. The user is executing to a deadline, so a build-status table is more useful than a clean summary.
- 2026-08-14: the user is **new to confidence intervals and inferential statistics**, while being expert on the design. Do not assume statistical background; do assume domain background. Teach a statistic by what it *rules out*, not by its formula.
- 2026-08-14: interactive widgets earn their place here. `assets/statlab.js` holds three reusable ones — `.lab-bootstrap` (resampling machine), `.lab-chance` (prevalence paradox sliders), `.lab-hill` (coverage vs effective number). Reuse them before writing new ones. Verify with a headless DOM shim in node; the in-app preview pane loads local files as `data:` URLs, so relative `<script>` and `<link>` never resolve there.
- Preference honoured in lesson 0003: answer the question that was asked, then give the frame that makes the answer generalise. The user asks several questions at once and wants the connective tissue between them.
