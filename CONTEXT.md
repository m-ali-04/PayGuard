# PayGuard — Project Context

Running log of context provided about the project. Items that belong in CLAUDE.md (instructions for Claude: conventions, commands, rules) are confirmed with the user before being added there.

## Project Overview

- **Client:** a finance company with two problems:
  1. **Fraud detection.** Flag fraudulent transactions.
  2. **Complaint triage.**
- **What we deliver:** prototypes that show the solutions we can offer the client.
- **Data:** we treat the data we're given as if it belongs to the company.
- **Order of work:** overview first, then Problem 1 and Problem 2 in turn. The owner provides whatever information is available for each.

### Scope Principles
- The top priority is what the client asked for directly.
- Anything out of scope is still mentioned to the client, not dropped silently.
- We treat these as prototypes of enterprise solutions, so we balance effort against results.

### Reproducibility & Documentation
- The project must boot from a **clean environment**: a dependency file (requirements.txt or pyproject.toml) and seed data or download instructions. Add setup steps as we go.
- Keep a **README** that summarises our strategies over time, precisely:
  - setup instructions
  - approach
  - results
  - what was cut and why, or why something extra was added

- Tooling: **uv + pyproject.toml + uv.lock, Python 3.12** (owner approved).
- The data file downloaded from Kaggle has the same SHA-256 as the public mirror copy: `76274b69…a89`.

*(Added to CLAUDE.md. README created with the approved outline.)*

## Problem 1: Fraud Detection

### Goal
- A model that flags fraudulent transactions, built for **real-time inference**.

### Decisions to Make
- How much research the scope needs.
- What the end goal is.
- Which evaluation strategies and metrics are relevant.

### Approach
- Try several strategies.
- Domain research plus a study of the provided data produces a **shortlist** of models.
- Compare the shortlisted models in a **controlled environment**.
- **Complexity must match the results.** Adding complexity without a proven gain is not allowed.

### Data
- The dataset is the credit-card fraud transactions data (source ID `mlg-ulb/creditcardfraud`). **Treat it as client data, not as a public or competition dataset.** Talk about it in terms of the client.

### Real-Time Setting
- The client works on **real-time data**. Our data is a static file, so the prototype needs a way to replay it as a live stream.
- **Decision (2026-11-24): Option A, replay to a scoring API.** A script reads the file in time order and sends each transaction to a local scoring service. **Possible additions if time allows:** B (local Kafka pipeline) and C (A with Kafka beside it for logging and monitoring).
- **Training-serving skew (from a blog the owner read):** models lose accuracy in production when features are computed one way in training and another way at inference. The fix is structural: define features in one place and compute each kind (just-in-time, near-real-time, batch) on the right path. What this means for us: training and the API share one preprocessing code path, and a parity test checks that the API's scores on replayed transactions match the offline scores. Any training-data cleaning must be something that could also happen live, or be a fix for a genuine data error. The client's upstream PCA step is a skew risk at integration. A feature store is an enterprise addition and out of scope for the prototype. *(Rule added to CLAUDE.md under Code Quality.)*

### Latency
- Set the budget from industry standards, on the lenient side if needed.
- Latency doesn't override or block any approach when we discuss models or other decisions.
- Latency has to be good enough. Reduce it with the right tools (serving, runtime, infrastructure), not by compromising elsewhere.
- **Decision (2026-11-24): p99 ≤ 50 ms per transaction is the baseline.** It's the lenient end of the published 10–50 ms range. If we have capacity, improving on it is a goal.
- **Decision (2026-11-24, to be reviewed later): score one transaction at a time, synchronously.** The owner read that batch processing isn't enough because of ingestion delays: a batch can't decide on a transaction inside its authorisation window. Point for the review: server-side micro-batching (grouping requests that arrive within a few ms) is a serving-tool option that raises throughput without changing the per-transaction contract.

### Metrics
- **Deferred (2026-11-24).** Still open: (1) which metric picks the model (PR-AUC, or recall at a fixed alert budget), (2) how to set the alert budget (one assumed value or a range; needs research on typical issuer review capacity), (3) when a gain counts as real (for example, bootstrap confidence intervals). Latency is a pass/fail gate, not a scored metric. Cost-weighting and calibration come later.

### Cost of Errors
- Weigh missed fraud against blocking genuine customers using standard industry practice, on the lenient side.

### Domain Research
- Done at the start of planning. Claude does a first pass with sources, and the owner checks it against industry experience.
- **First pass, 2026-11-24, not yet checked by the owner:**
  - **Latency:** the full authorisation window is about 100–300 ms. Fraud scoring usually gets 10–50 ms of that, and feature lookup is often the bottleneck. Sources are vendor and practitioner write-ups, not a formal standard.
  - **Metrics:** don't use accuracy or ROC-AUC as the headline metric for very imbalanced data. Use PR-AUC (average precision). For operations, use precision/recall at a fixed alert budget (precision@k), since investigators can only review so many alerts.
  - **Validation:** split by time, not randomly. Leave a gap between train and test to model **feedback delay**, the time before fraud labels arrive (a week is a reasonable first approximation).
  - **Cost of errors:** estimates vary widely. False declines often cost issuers more than the fraud itself, through churn and lower spend. There's no standard ratio, and it should come from the client's own portfolio.
  - **Models:** gradient-boosted trees usually come out ahead on this kind of tabular data. Logistic regression stays common as an interpretable baseline. None of the published comparisons report latency, calibration or drift.
- **Data limitations found:** the data covers only about 2 days, has no card or customer ID, and its features are anonymised with PCA. That means we can't simulate a week of feedback delay, can't compute card-level metrics, and can't build history (velocity) features. These go to the client as out-of-scope items.

### Out of Scope
- Extensive hyperparameter tuning.
- Ensembling for leaderboard-style gains.
- The solution has to be practical and work in real life, not just score well on training data.

## Problem 2: Complaint Triage

*(Context to come)*

## Team & Roles

- The user is the **solutions architect** and owns every part of the project. Claude is part of the development team.
- The user must have direct input on every decision.
- All code must be reviewed with the user before it's finalised, especially code that introduces a new format or a new kind of code for the project. *(Added to CLAUDE.md)*

## Planning Approach

We plan using a structured problem-solving approach:

1. **Flag knowledge gaps.** Say where we need more context or research, for example on industry practices.
2. **Break the problem into components** where it makes sense. Each component has:
   - a clear scope
   - a workflow the team generally understands
   - a **project-impact subsection** that explains how decisions inside the component affect the project as a whole
3. **Evaluate options by fit, not by ranking.** Instead of asking whether one option is better or worse, look at how the overall strategy would work under each choice.
4. **Match depth to the decision.** How far we take this depends on how complex or important the decision is.

These are guidelines that add to normal planning practice (including plan mode). They don't replace it.

*(Added to CLAUDE.md)*

## AI Usage Guidelines

- AI (Claude) must be used under specific guidelines.
- The repo must contain an **`AI_USAGE.md`** that records:
  - which AI tools were used (for example, Claude Code)
  - what each tool was used for
  - roughly what share of the code each tool produced

- Code share is estimated **per component**.

*(Added to CLAUDE.md. AI_USAGE.md created.)*

## Code Quality

- Code must be concise, not bloated. We want efficient code that follows good practices.
- Claude drafts the CLAUDE.md wording and the owner reviews it.
- Clever solutions are welcome, but the owner must review them first.

*(Added to CLAUDE.md. Stack-specific rules and payment-industry security practices such as PCI-DSS still need research once the stack is chosen.)*


## Repository & Workflow

- Private GitHub repo: `m-ali-04/PayGuard`. CLAUDE.md and CONTEXT.md are committed, following standard practice. CLAUDE.local.md stays local, with no backup (owner's decision).
- Workflow: one branch and one PR per step, with conventional commits. Claude runs a code review on each PR and posts the findings, then the owner reviews and merges. Merging means the code is final. At milestones, the owner can run `/code-review ultra`.

*(Added to CLAUDE.md via PR)*
