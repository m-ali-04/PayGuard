# AI Usage

This file records the AI tools used on PayGuard, what each was used for, and roughly how much of the code each produced.

## Summary

| Tool        | Purpose                                         | Approx. share of code |
|-------------|-------------------------------------------------|-----------------------|
| Claude Code | Project docs; setup and analysis scripts          | ~100% of code so far  |

## Per-Component Estimates

| Component | Tool | Approx. AI share | Last reviewed |
|-----------|------|------------------|---------------|
| Setup (scripts/get_data.py) | Claude Code | ~100% | 2026-11-24 (approved by owner) |
| Data understanding (scripts/data_understanding.py, report) | Claude Code | ~100% | 2026-11-24 (reviewed by owner) |

## Usage Log

| Date       | Tool        | Component / Area | What it did                                         | Human review      |
|------------|-------------|------------------|-----------------------------------------------------|-------------------|
| 2026-11-24 | Claude Code | Docs             | Drafted CONTEXT.md, CLAUDE.md and AI_USAGE.md        | Approved by owner |
| 2026-11-24 | Claude Code | Problem 1 / Research | Downloaded and checked the dataset; first pass of domain research | Pending owner review |
| 2026-11-24 | Claude Code | Setup | Set up uv/Python 3.12; wrote scripts/get_data.py (Kaggle/manual, hash-checked) and the README setup steps | Approved by owner |
| 2026-11-24 | Claude Code | Problem 1 / Data understanding | Wrote scripts/data_understanding.py and drafted the report text; added pandas/matplotlib in the `analysis` group | Reviewed by owner |
| 2026-11-24 | Claude Code | Repo | Initialised git, wrote the README workflow section, created the private GitHub repo, made the initial commits | Approved by owner |
| 2026-11-24 | Claude Code | Problem 1 / Evaluation design | Proposed split options and the decision-report contents; ran a one-off duplicate check; logged the owner's decisions in CONTEXT.md and the README (no code) | Decisions made by owner |

## Estimation Method

- We estimate share **per component**: for each component, roughly what percentage of its code came from AI and was kept with little or no change.
- Code the owner substantially rewrote counts as human-written.
- We re-check the estimates at milestones and when a component is finished. They're estimates, not line counts.
- The share in the Summary table is a rough weighted average across components.
