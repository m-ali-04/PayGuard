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

### Evaluation Framework
- **Discussion (2026-11-24): k-fold vs time-based split.** The owner asked why not k-fold, the usual choice, and whether it was because chunks would hold too few frauds. That isn't the reason: stratified 5-fold would hold about 98 frauds per fold and test every fraud once. The problem is the shuffle. (1) It trains on future transactions and tests on past ones. (2) It hides the day-1 → day-2 drift (7 features, V3 largest), so it would overstate live performance. (3) It splits the 1,081 same-second exact duplicates across folds, so the model gets tested on rows it trained on.
- **Discussion: forward-chaining** (walk-forward / expanding-window, the time-aware k-fold). Each fold trains on everything before a cut-off and tests on the next block. Over day 2 it would base the comparison on all 211 day-2 frauds instead of about 115, and it would show whether drift lowers later folds and whether fresher training data recovers the loss. The costs: a threshold-setting step per fold, training sizes that differ between folds, and a rule for pooling or averaging folds that has to be fixed before any comparison. The owner raised the key limitation: with only 48 hours (one daily cycle), fold-to-fold changes mix drift with time of day, since fraud runs 4.3x higher in quiet hours. A single split still prices in the drift once (train day 1, test day 2); what it can't show is the trend.
- **Decision (2026-11-24): a single time-ordered train / validation / test split, not forward-chaining.** Reason: with one daily cycle, forward-chaining's main benefit (seeing how performance changes over time) can't be separated from time-of-day effects, so it adds machinery without a reliable reading. The bootstrap ranges in the decision report already cover "is this gain real?". **The owner would choose forward-chaining with a longer window of history**, so it's the recommended method once the client provides several weeks of data.
- **Decision (2026-11-24): clock-aligned windows. Train 0–24h (144,786 txns, 281 frauds), validation 24–36h (47,445, 96 frauds, 0.20%), test 36–48h (92,576, 115 frauds, 0.12%).** Reason: the largest test set of the options compared (50/25/25 gave 94 test frauds, 60/20/20 gave 75), and an easy story to tell: "train on yesterday, set the threshold overnight, test on today". Validation covers the quiet night hours, where fraud runs higher, so the validation threshold will flag a different share than 0.1% on test. That drift is shown as a finding, not hidden.
- **Decision (2026-11-24): no gap between windows.** A gap of a few hours can't model a week of label delay and costs about 10 frauds per hour. Recorded as a limitation.
- **Decision (2026-11-24): train only, no refit on train + validation.** Owner's reason: refitting would mean validating on something that was used for training. The threshold set on validation has to come from a model that never saw the validation data.
- **Decision (2026-11-24): decision-report contents approved** as proposed: (1) AP with a paired-bootstrap 95% range for the difference (2,000 resamples, fixed seed); (2) precision, recall and frauds caught a day at the 0.1% budget, with a bootstrap range for the difference in frauds caught; (3) the operational view, meaning the validation threshold applied to test (actual alert rate, precision, recall); (4) ROC-AUC for reference; (5) p99 single-transaction latency, pass/fail at 50 ms (end-to-end API latency added later); (6) complexity and explainability, in words; (7) duplicate sensitivity; (8) the default recommendation from the selection rule, plus the owner's decision and reason. **Owner's condition:** any item that turns out to be irrelevant is removed (for example, item 7 depends on the duplicate policy).
- **Duplicate check (2026-11-24, at the owner's request).** The owner's concern: training on duplicates whose fraud share differs from the overall share could teach the model to treat duplicates differently. Findings:
  - **Exact duplicates** (same second): no label conflicts. 773 groups, 1,854 rows, 1,081 extra copies. The fraud rate inside these groups is **1.73%, 10x the overall 0.173%**: 13 distinct fraud transactions appear 32 times, and two groups have 18 copies each. Extra fraud copies per window: train 9 (281 frauds → 272 distinct), validation 9 (96 → 87), test 1 (115 → 114).
  - **Repeats at a different second:** 12,456 rows, all genuine (0 fraud), no label conflicts. 805 of the 4,383 groups span more than one window, so identical genuine feature vectors appear across windows (the check didn't separate train–test from other pairs). That fits recurring payments, which would also recur live.
  - Mechanism: the model has no "is a duplicate" input, so it can't single out duplicates as such. The effect is extra weight on those 13 frauds and about 760 genuine transactions, which pulls the model toward their region of feature space. In validation, 9 of the 96 frauds are copies, which tilts the threshold.
- **Options discussed:** (a) keep all; (b) drop exact copies in train and validation, keep them in test and the replay (count each transaction once when fitting and setting the threshold); (c) drop everywhere, which needs request deduplication in the API so the replay matches. The owner asked whether (b)'s complexity is worth what it gives, and whether handling this nuance is recommended practice at prototype level. Claude's answer: (b) is about one line of code, but the gain is unproven (9 copies among 281 training frauds), and deduplication is normally done upstream, at ingestion, by transaction ID, not in the model. We have no transaction ID.
- **Decision (2026-11-24): keep all duplicates.** Owner's reason: whatever they are, the duplicates are part of the real-life data, and handling them belongs to an earlier process (upstream ingestion), not to the model. Option (b) goes under possible additions.
- **Findings are stored here only.** The duplicate check was a one-off and isn't added to `scripts/data_understanding.py` (owner's decision).
- **Decision (2026-11-24): the decision report also lists the main metrics on validation beside test**, as a two-point view over time. Its caveat is stated in the report: the windows differ in fraud mix (night vs daytime), so it's a reading, not a measurement of drift.
- **Decision (2026-11-24): report item 7 (duplicate sensitivity) removed.** With all duplicates kept, test holds only 1 extra fraud copy, so a with/without comparison would show almost no difference. This applies the owner's remove-if-irrelevant condition. The report uses the data exactly as recorded throughout.
- **Final decision-report contents:** AP with bootstrap range; precision, recall and frauds caught a day at the 0.1% budget, with bootstrap range; the operational view (validation threshold on test); ROC-AUC (reference); p99 latency (pass/fail at 50 ms); complexity and explainability; main metrics on validation beside test; the default recommendation plus the owner's decision and reason.

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
