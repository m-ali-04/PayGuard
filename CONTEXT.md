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

### Information Available
- **(2026-11-24) The information we have now is final until the prototype is built.** There are no open questions for the client.
- **Assumptions about volume, traffic type and similar operating conditions must be discussed with the owner before they're made.** *(Added to CLAUDE.md.)*

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

### Tooling & Audience
- **MLflow** will be used later to evaluate (track and compare) the models.
- The project will be **presented to technical people** as well, so the code and analysis need to read well when walked through.
- **Decision (2026-11-24): data understanding is a script that writes a Markdown report with figures, not a notebook.** The presentation will show the data findings only, not walk through the analysis code. MLflow's UI covers model comparison, so no notebooks are planned. Presentation flow: data findings report → model comparison in MLflow → live replay demo against the API.

### Data Understanding Findings (2026-11-24)
- Full report: `reports/data_understanding.md`, generated by `scripts/data_understanding.py`.
- Day 1 has 281 frauds and day 2 has 211, so a day-2 test set has about 211 positives (each one ≈ 0.5% of recall). Fraud is 4.3x more frequent in quiet hours.
- 1,081 exact duplicates (19 fraud, no label conflicts), all within the same second, so they can't straddle a time split. A further 8,063 rows repeat values at a different second (possibly recurring payments or retries).
- 7 features drift between day 1 and day 2 among genuine transactions (KS > 0.2, largest V3 at 0.52), which supports a time split.
- 7 features separate fraud strongly on their own (KS > 0.7: V14, V10, V12, V4, V11, V17, V3), so a simple baseline is credible.
- 37% of frauds are ≤ 1.00 against 11% of genuine. Amount alone separates weakly and needs a scale transform for scale-sensitive models.
- The 0.2 and 0.7 KS cut-offs are reporting thresholds Claude chose, not industry standards.
- **Decision (2026-11-24): pytest is on hold.** `ks()` was checked once against SciPy's `ks_2samp` (exact match). Tests will be added with the prototype code (preprocessing, parity test).

### Metrics
- **Decision (2026-11-24): alert budget sample figure = 0.1% of transactions** (~140 alerts a day on the client's volume). Source: the Fraud Detection Handbook says real systems are closer to 0.1%. It's a sample figure chosen by the owner, not client-provided. At 0.1%, recall is capped at ~58% because the fraud rate is 0.17%.
- **Agreed principles:** commit to the selection rule before comparing models. Report every metric. Compute PR-AUC (average precision) step-wise, never by linear interpolation. At a fixed budget, precision and recall rank models identically, so both are reported. ROC-AUC is reported for reference only and never used to choose. Card precision top-k can't be computed (no card ID). The live threshold is a fixed score set on validation data, not a daily top-k. Latency is a pass/fail gate. Cost-weighting and calibration come later.
- **Decision (2026-11-24): selection rule.** The model is chosen by average precision (PR-AUC) on the test set, provided it is not worse than the alternatives at the 0.1% budget (precision/recall there). All metrics are reported. If the curves cross (a model wins overall but loses at the budget), we report it to the client as a finding and the owner decides; we don't switch rules.
- **Decision (2026-11-24): what counts as a real gain is the owner's judgement, not an automatic floor.** A fixed floor can't weigh a gain against its running costs (latency, complexity, explainability), which only show up once models exist. The evaluation produces a **decision report** comparing each candidate with the simpler model: average precision and frauds caught a day at the 0.1% budget, each with a paired-bootstrap 95% range for the difference, plus p99 latency and complexity/explainability. The bootstrap is information, not a gate. Safeguards against favouring a hoped-for model: the report's contents are fixed before any comparison, and the reason for each choice is written down (PR/README). The selection rule is the report's default recommendation; the owner makes the final call. Latency stays a pass/fail gate (p99 ≤ 50 ms), and below it latency is a trade-off. Exact test-set sizes come with the split design (likely ~100 test frauds with a validation set).

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
- **Fraud Detection Handbook, Ch. 4 "Performance metrics" (ULB Machine Learning Group; read 2026-11-24 at the owner's request):**
  - It recommends reporting **ROC-AUC, average precision (AP) and card precision top-k together**, as complementary measures. It doesn't name one metric for model selection.
  - Operations metric: **precision top-k per day**, with k = the number of alerts investigators can process in a day. A card-level version counts each card once, which we can't compute (no card ID).
  - Its example uses k = 100 a day (~1% of its test set) and says real systems are **closer to 0.1%** of transactions, with "any FPR higher than 0.001 already too high".
  - In its example, ROC-AUC and AP **rank two models in opposite order**, which is evidence that ROC-AUC can mislead model selection.
  - Use threshold-based metrics only when the constraints are clear (its example: "precision above 60 percent"); otherwise compare models threshold-free.
  - Its protocol is 7 days train, 7 days delay, 7 days test, with detected cards removed from later days. We can't replicate that (2 days, no card ID).
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
