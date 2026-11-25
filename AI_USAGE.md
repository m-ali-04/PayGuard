# AI Usage

This file records the AI tools used on PayGuard, what each was used for, and roughly how much of the code each produced.

## Summary

| Tool        | Purpose                                         | Approx. share of code |
|-------------|-------------------------------------------------|-----------------------|
| Claude Code | Project docs; setup, analysis, model-training, evaluation, serving and replay code | ~100% of code so far  |

## Per-Component Estimates

| Component | Tool | Approx. AI share | Last reviewed |
|-----------|------|------------------|---------------|
| Setup (scripts/fraud/get_data.py) | Claude Code | ~100% | 2026-11-24 (approved by owner) |
| Data understanding (scripts/fraud/data_understanding.py, report) | Claude Code | ~100% | 2026-11-24 (reviewed by owner) |
| Fraud models: data windows, shared preprocessing, training (src/payguard/fraud/, scripts/fraud/train.py, tests/fraud/) | Claude Code | ~100% | 2026-11-24 (approved by owner, PR #4 merged) |
| Decision report: scoring rules, evaluation script, report (src/payguard/fraud/evaluation.py, scripts/fraud/evaluate.py, tests/fraud/test_evaluation.py) | Claude Code | ~100% | 2026-11-25 (approved by owner, PR #5 merged) |
| Scoring API: store helpers, API, tests (src/payguard/fraud/tracking.py, src/payguard/fraud/api.py, tests/fraud/test_api.py, tests/fraud/conftest.py) | Claude Code | ~100% | 2026-11-25 (approved by owner, PR #6 merged) |
| Replay: engine, live panel, parity report, tests (scripts/fraud/replay.py, scripts/fraud/replay_panel.py, scripts/fraud/replay_report.py, tests/fraud/test_replay.py) | Claude Code | ~100% | 2026-11-25 (walked through with owner per session, PR #7 merged) |

## Usage Log

| Date       | Tool        | Component / Area | What it did                                         | Human review      |
|------------|-------------|------------------|-----------------------------------------------------|-------------------|
| 2026-11-24 | Claude Code | Docs             | Drafted CONTEXT.md, CLAUDE.md and AI_USAGE.md        | Approved by owner |
| 2026-11-24 | Claude Code | Problem 1 / Research | Downloaded and checked the dataset; first pass of domain research | Pending owner review |
| 2026-11-24 | Claude Code | Setup | Set up uv/Python 3.12; wrote scripts/get_data.py (Kaggle/manual, hash-checked) and the README setup steps | Approved by owner |
| 2026-11-24 | Claude Code | Problem 1 / Data understanding | Wrote scripts/data_understanding.py and drafted the report text; added pandas/matplotlib in the `analysis` group | Reviewed by owner |
| 2026-11-24 | Claude Code | Repo | Initialised git, wrote the README workflow section, created the private GitHub repo, made the initial commits | Approved by owner |
| 2026-11-24 | Claude Code | Problem 1 / Evaluation design | Proposed split options and the decision-report contents; ran a one-off duplicate check; logged the owner's decisions in CONTEXT.md and the README (no code) | Decisions made by owner |
| 2026-11-24 | Claude Code | Problem 1 / Models | Compared 12 model families; wrote the package (data windows, shared preprocessing, two candidate pipelines), the MLflow training script and the first pytest suite; added scikit-learn, pandas, MLflow and pytest | Walked through with owner per session; PR #4 merged |
| 2026-11-24/25 | Claude Code | Problem 1 / Decision report | Planned the report and previewed its format; wrote the scoring rules, their tests (checked against deliberate bugs) and scripts/evaluate.py; diagnosed HGB's training divergence and proposed the l2 fix; computed threshold, budget and day/night findings for the owner's questions; logged decisions in CONTEXT.md and README | Owner made every decision (budget, fix, model); walked through per session; PR #5 merged |
| 2026-11-25 | Claude Code | Problem 1 / Scoring API | Planned the API (framework, model selection, threshold storage); moved MLflow helpers into the package; logged the threshold from evaluate.py; wrote the FastAPI service and its tests (checked against 9 deliberate bugs); found and fixed the NaN-500 error; ran a manual check against the real server; added fastapi, uvicorn and httpx | Owner made every decision; walked through per session; PR #6 merged |
| 2026-11-25 | Claude Code | Problem 1 / Replay | Laid out the visual-view options; measured the test window, API throughput, fraud-dense windows and real gaps between transactions for the owner's slice and speed-up choices; probed the API under overlapping requests (found the OpenMP oversubscription and the uvicorn multi-worker no-delay quirk); wrote the replay engine, rich live panel, parity report and tests (parity test checked against a deliberate rounding bug); added rich and moved httpx to the main dependencies | Owner made every decision (panel, slice, pacing, scope); walked through per session; PR review pending |
| 2026-11-25 | Claude Code | Problem 2 / Repo layout | Moved fraud scripts, reports and tests into `fraud/` subfolders (option A) and updated every path, docstring hint and README command | Layout decided by owner; plan approved |

## Estimation Method

- We estimate share **per component**: for each component, roughly what percentage of its code came from AI and was kept with little or no change.
- Code the owner substantially rewrote counts as human-written.
- We re-check the estimates at milestones and when a component is finished. They're estimates, not line counts.
- The share in the Summary table is a rough weighted average across components.
