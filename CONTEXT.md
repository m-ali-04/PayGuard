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

### Windows Support (2026-11-25)
- **Question (owner):** does the reproducibility have Windows or Linux limitations? An audit found the Python code portable (lockfile covers Windows, pathlib paths) but the setup docs bash-only, and nothing tested on Windows.
- **Native attempt:** a PowerShell script (kept every install inside the repo) was tried on the owner's Windows 11 machine, which has Smart App Control on. SAC blocked, in turn: uv's unsigned Python builds (worked around with python.org's signed build), uv's unsigned `.exe` launchers such as `kaggle.exe` (worked around with `python -m`), and then scikit-learn's own compiled files from PyPI, which can't be worked around inside the project. So native Windows only runs with SAC off.
- **Real bug found on the way:** the three report writers used the locale's encoding (cp1252 on Windows) and failed on `≤`. Fixed with explicit UTF-8.
- **Decision (owner): WSL2 is the Windows route.** The README Linux steps run unchanged inside WSL2, which is also where all results so far were produced (same machine). The native-only workarounds were removed (script, signed Python, `python -m kaggle`); the UTF-8 fix stays, and `.gitattributes` keeps the committed complaint slice's bytes on Windows-side checkouts.

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
- **Decision (2026-11-24): alert budget sample figure = 0.1% of transactions** (~140 alerts a day on the client's volume). Source: the Fraud Detection Handbook says real systems are closer to 0.1%. It's a sample figure chosen by the owner, not client-provided. At 0.1%, recall is capped at ~58% because the fraud rate is 0.17%. *(Superseded 2026-11-24: raised to 0.2% before any model was scored; see "Decision Report & Model Selection".)*
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

### Model Shortlist & Preprocessing
- **Discussion (2026-11-24): plan mode.** The owner asked when to use Claude Code's plan mode. Until now, "propose before building" was a convention only, and the session ran in auto mode. Plan mode enforces it: no edits until the owner approves the plan via ExitPlanMode. **Decision: code steps start in plan mode.** *(Added to CLAUDE.md under Collaboration Rules.)*
- **Decision (2026-11-24): gradient-boosted trees start with sklearn's `HistGradientBoostingClassifier`, with early stopping turned off.** On data this size, its default early stopping holds out a *random* 10% of training rows, which would shuffle time inside the training window. LightGBM/XGBoost stay an option if a gain is proven.
- **Decision (2026-11-24): no resampling** (no SMOTE or undersampling).
- **Decision (2026-11-24): dependencies added now:** scikit-learn, pandas (runtime), MLflow (runtime, also used now to save model artifacts so the format doesn't change between PRs), pytest (dev group).
- **Discussion: wider model list.** Claude compared 12 model families against this data (PCA features, no categoricals, no IDs, 281 training frauds, single-transaction scoring, explainability). Logistic regression and boosted trees cover both ends: interpretable, and strongest expected. Random forest was the one reasonable third option (usually trails boosted trees, slower single-row scoring). k-NN (latency grows with the data), RBF SVM (training cost) and MLP (sensitive to tuning) fit poorly. Anomaly detection is a possible later companion signal. Sequence and graph models need card history (out of scope).
- **Decision (2026-11-24): shortlist = logistic regression + `HistGradientBoostingClassifier`**, default settings, no tuning.
- **Decision (2026-11-24): preprocessing lives inside each model's sklearn Pipeline (option a)**, so the saved artifact carries its own preprocessing and serving can't skew from training. Drawbacks discussed, none major for the prototype: tied to sklearn's pickle format (MLflow records the environment); serving needs sklearn + pandas (~1 ms overhead, to be measured); stateless (velocity features would come from a feature store upstream); harder ONNX conversion if latency ever needs it.
- **Decision (2026-11-24): `Time` is dropped; no hour-of-day feature for now.** The clock start is an unverifiable assumption, the model would learn "night is risky" from a single night, and the threshold is set on the night window. The code would be small. Possible addition: test it as one variant through the decision report.
- **Finding (2026-11-24, during build): MLflow 3.18 saves sklearn models with skops, not pickle.** skops refuses types it hasn't vetted, so loading can't run arbitrary code. HGB's internal tree type isn't on its safe list (a tampered file could crash `predict()`). **Resolution, walked through with the owner:** keep skops and trust that one type explicitly (`TRUSTED_TYPES` in `models.py`), since we only load models we trained. Checked: both models save as identical file sets, reload as the same sklearn Pipeline and give bit-identical scores, so the setting doesn't affect storage or evaluation. This removes the "tied to pickle" drawback of option (a). MLflow also records the 92 pinned dependency versions from `uv.lock` with each model, which covers version matching.
- **Code review on PR #4 (2026-11-24): 6 findings, all fixed with the owner's go-ahead.** The important one: the saved input contract required `Time` because the input example kept it, so MLflow's generic loader (used by serving tools) rejected live transactions without it. **Resolution: the model contract is the 29 model fields** (V1–V28, Amount), consistent with dropping `Time`. While fixing it, Claude found that MLflow inferred the **output** contract from `predict` (0/1 labels as integers) rather than `predict_proba`; the signature is now inferred from `predict_proba` (float64 probabilities). Both save paths (training and tests) go through one `save_options()` so they can't drift. The others: a clear exit when the experiment was deleted in the UI (not restored automatically, so a deletion isn't quietly undone), tests for live-shaped rows and the generic loader, numpy declared at runtime, a cheaper skip check in the data tests, and "from the repo root" for the MLflow UI command.
- **Decision (2026-11-24): code is built in short sessions**, each explained and followed by a "continue?" check (owner's request).
- **Decision (2026-11-24): class imbalance.** No resampling. Logistic regression uses `class_weight="balanced"` (reweights the rare class without changing the data); the trees use defaults.

### Decision Report & Model Selection (2026-11-24 to 25)
The process ran in this order: report design (plan mode) → budget review → build → a bug found in the first results → fix → results → the owner's questions → model decision. Each step is recorded below, including the owner's own reasoning.

**Report design (before any model was scored)**
- **Discussion: what "frauds caught a day" means on a 12-hour test window.** The owner asked for a detailed explanation of budgets, alerts and the 0.1% figure. Summary given: an *alert* is a transaction flagged for review or blocking, and each one costs investigator time or customer friction. The *alert budget* is the client's review capacity, expressed as a share of transactions so it scales with volume. 0.1% was a sample figure (the Handbook's "real systems run near 0.1%"), ~142 alerts a day. Offline, a model is scored by flagging the top k = budget × transactions in a window. Live, a fixed score threshold set on validation is used instead, since transactions arrive one at a time, so the live alert count drifts. The test window holds 92,576 transactions (the busy daytime half), 115 frauds.
- **Owner's reasoning on the budget:** the 0.1% budget was a limit we had assumed on our own, and it was cutting results hard. At 0.1%, the budget sat below the 0.173% fraud rate, so it capped daily recall at 58% whatever the model. The owner asked for a budget that stays relevant but isn't "so devastating". Options compared: 0.2% (~285/day), 0.5% (~712/day), 1% (~1,424/day, the Handbook's worked example). Higher budgets mean most alerts land on genuine customers and the two models separate less.
- **Decision: alert budget raised to 0.2%** (`BUDGET` in `src/payguard/fraud/evaluation.py`). Still an owner-chosen sample figure, not client-provided. Reason: it sits just above the fraud rate, so the model, not the budget, is the limit, and it stays close to the Handbook's real-world figure. Chosen before any model was scored, so it isn't tuned to results. On the windows: test 185 alerts for 115 frauds, validation 95 for 96.
- **Decision: counts are reported per test window, not scaled to a day,** with one line relating the window's 185 alerts to the daily budget. Reason: doubling a 12-hour daytime window would assume the night half behaves the same, and fraud runs higher at night.
- **Decision: output = Markdown report (`reports/decision_report.md`, written by `scripts/evaluate.py`) + headline metrics logged to each model's existing MLflow run.**
- **Decision: the owner's model decision and reason are recorded in README "Results" and here,** not in the generated report, which is overwritten on every run.
- **Design choices in the build (proposed by Claude, approved in the plan):** the report reads the latest *finished* run per candidate from MLflow. The scoring rules (`at_budget`, `threshold_for_budget`, `at_threshold`, `paired_bootstrap`) live in `src/payguard/fraud/evaluation.py`, so the API can reuse the live threshold. Latency is measured on the model only: 2,000 single-row `predict_proba` calls after 50 warm-up calls; end-to-end API latency comes in the API step. Tied scores at the cut: top-k flags exactly k; the live threshold flags all ties.

**Bug found in the first results: HGB training diverged**
- **Finding:** the first report showed HGB at AP 0.160 against logistic regression's 0.677, and both thresholds printed as "1". Claude checked before treating it as a result. HGB's probabilities saturated at exactly 1.0 (247 test transactions tied at 1.0 against a 185 budget, so its top ranking was arbitrary). It also misfit its own training data (≥69 genuine training transactions at 1.0). Tracing the training loss tree by tree showed it rising after the first tree, with raw log-odds reaching 323,617.
- **Cause:** each tree's leaf value is the sum of gradients over the sum of hessians plus `l2_regularization`, which defaults to 0 in sklearn. Leaves holding a few rare-class rows whose predictions are already near 0 or 1 divide by a near-zero hessian sum, so their values explode and feed back into the next tree.
- **Evidence for the fix (training window only, no validation or test scores):** with `l2_regularization=1.0`, training loss falls with every tree, raw scores stay below 16, nothing saturates.
- **Options discussed:** (A) add `l2_regularization=1.0`, a stability guard, the same default XGBoost uses for this term; (B) report HGB as is, which would compare against a model broken in a known way; (C) lower the learning rate or restrict leaf size, which works but has no principled values and slides into tuning; (D) switch to XGBoost/LightGBM, a new dependency for a one-argument fix.
- **Decision: (A).** It's the one exception to "default settings" on the shortlist, made because of a diagnosed failure, not a score search. Both models were retrained.
- **Regression test on the client's training window (owner's request).** The divergence doesn't reproduce on synthetic imbalanced data (the old setting gives larger raw scores but no saturation), so a synthetic test would pass with the bug present. `test_hgb_training_does_not_saturate_on_client_data` trains HGB on the real training window and checks no score hits exactly 0 or 1; it's skipped when the data isn't downloaded. Checked: it fails with the old setting.
- **The PR #4 runs were deleted** (owner's request), including the broken HGB, so MLflow holds one run per model again. While purging, `mlflow gc` needed `--tracking-uri` as well as `--backend-store-uri` once logged models are involved, so the hint in `scripts/train.py` was fixed (checked in a throwaway store: the old hint fails, the new one works).

- **Code review on PR #5 (2026-11-25): 6 findings; 5 fixed with the owner's go-ahead, 1 declined with a reason.** The important one: the report picked each model's latest run separately, so a `train.py` call that stopped partway could pair a fresh model with a stale one (for example, the broken HGB). **Resolution:** every run from one `train.py` call shares a `session` parameter, and `evaluate.py` stops if the latest runs don't share one. The two current runs predate the parameter; they came from one `train.py` call 3 seconds apart, so that session was added to them rather than retraining. The others fixed: the AI_USAGE table row, README's Evaluation heading, bootstrap settings defined once, complexity notes read from the fitted models. Partly declined: guarding against a third candidate missing a note (adding a candidate means writing its note anyway). Declined: a guard for recall on a window with zero frauds. Recall is undefined there, so an error is more honest than reporting 0, and no current window or resample can hit it.

**Results (test window 36–48h, budget 0.2% = 185 alerts)**

| | Logistic regression | HGB |
|---|---|---|
| AP | 0.677 | 0.732 |
| Frauds caught at budget (of 115) | 88 | 90 |
| ROC-AUC (ref.) | 0.937 | 0.973 |
| Operational view (validation cut on test): alerts / caught | 82 / 68 | 96 / 82 |
| Live alert rate (budget 0.2%) | 0.089% | 0.104% |
| p99 latency (model only) | 7.0 ms | 18.1 ms |
| Saved model size | 146 KB | 1,057 KB |

- HGB − logistic regression, paired bootstrap 95%: AP +0.055 [−0.016, +0.121], frauds caught +2 [−3, +7]. Both ranges include zero, so with 115 test frauds the gain on these measures isn't certain.
- Default recommendation from the selection rule: HGB (higher AP, not worse at the budget).

**Owner's questions after the report, and findings computed to answer them** (on test, as information only; the rule and report contents were not changed)
- **Effect of the threshold.** The model ranks; the threshold decides where on the ranking to stop, trading missed frauds against genuine checks, and doesn't change AP. Logistic regression's scores are squeezed toward 1 by `class_weight="balanced"`: moving its cut from 0.999 to 0.9999 shifts 26 alerts and 8 frauds. HGB's scores are spread out, so its cut is stable and readable. **Owner's reading: HGB is more reliable and predictable with respect to the threshold.**
- **Why 0.999981 and not 0.999 for logistic regression.** The owner asked why the cut wasn't the one with the better caught-to-missed ratio. Answer: the cut is set on validation to flag exactly the budget there, then fixed, as it would be live. 0.999 catches more only because it spends more alerts (138 vs 82) at lower precision (59% vs 83%), and choosing it after seeing test would set the threshold on test.
- **Without the budget constraint** (frauds caught / missed on test by share checked): 0.1%: logistic regression 70/45, HGB 80/35; 0.2%: 88/27 vs 90/25; 0.3%: 93/22 vs 91/24; 1%: 95/20 vs 94/21; 5%: 101/14 vs 98/17. Returns fall off sharply after ~0.3% (0.3%→5% buys 5–8 frauds for ~4,300 more genuine checks). The last ~20% of frauds look genuine to both models: catching 90% needs 11% of transactions checked with HGB or 28% with logistic regression. The models swap places above 0.2%, within noise.
- **Is the selection metric "frauds let through"?** At a fixed budget, yes in effect: missed = 115 − caught. The weighting of a missed fraud against a genuine check is set by the budget choice, not the metric. The owner holds that missed fraud is worse than a checked genuine transaction. Ways to express that: a larger budget, or a cost-weighted metric, which needs a client cost ratio (none is standard). Neither was applied.
- **A 0.3% budget was considered by the owner** ("a good logreg model while missed and genuine checked stay within reach"). At 0.3% the selection rule would give "No default" (HGB higher AP, logistic regression +2 frauds at the budget, within noise). **Decision: keep 0.2%.**
- **Day/night effect.** With the cut fixed on the night validation window: genuine flagged 0.040% of genuine at night vs 0.015% by day; frauds caught 79% at night (both models) vs 59% (logistic regression) / 71% (HGB) by day. Both genuine and fraud scores are lower by day, a shift in scores and not only in fraud mix, larger than predicted. It doesn't affect the model comparison (same test window for both), but a single fixed threshold leaves half the budget unused by day. **Owner's reading: HGB is more consistent across day and night.**
- **SHAP** (per-decision attribution of a score to each field; exact and fast for trees). **Owner's decision: not needed now.** The client didn't ask for explainability, and the explanations would map to anonymised PCA fields that carry no business meaning. Revisit if the client or a regulator requires explanations.
- **Real-life catch rates:** the owner asked whether real-life rates are similar. Claude had no figure it could stand behind (published numbers are mostly vendor claims with inconsistent definitions). **The owner declined a sourced research pass.**

**Decision (2026-11-25): HGB is the selected model.** Owner's reasons: it ranks better (AP, ROC-AUC) and catches more with the threshold fixed in advance (+14 frauds in the operational view); its threshold is more reliable and predictable; it's more consistent across day and night. Its costs were judged acceptable: the larger model file isn't a limitation for this project, and its p99 latency (18 ms) is worse than logistic regression's but far below the 50 ms limit.

**Possible addition (owner's idea): time-of-day handling, once more history shows the pattern regularly.** The owner proposed splitting the day into peak and quiet hours with a separate model for each, if the relationship holds up over a longer period. Options from cheapest to most involved: (1) per-segment thresholds (one model, a different cut for busy and quiet hours; directly addresses the measured drift); (2) a time-of-day feature in one model (needs a reliable clock); (3) separate models (each trains on fewer frauds; two models to maintain). Usual path: try 1, then 2, then 3 only if the decision report shows a gain.

### Scoring API (2026-11-25)
Planned in plan mode, built in three short sessions (S1 store helpers and threshold, S2 API and tests, S3 manual run and docs).
- **Decision: FastAPI + uvicorn.** Our own small endpoint, so the response can carry the alert decision. Already installed through MLflow (its own scoring server uses the same stack), so declaring them added no download. `mlflow models serve` was the alternative: no API code, but it returns probabilities only, so the threshold would have to be hidden inside a custom model wrapper.
- **Decision: the selected model is a constant in code** (`SELECTED = "hgb"` in `models.py`). The MLflow registry with an alias (e.g. `fraud@champion`) is MLflow's standard promotion flow, but it adds a registry step and a promote command; changing the model is a reviewed code change for now.
- **Decision: evaluate.py logs the live threshold on each model's run** (metric `live_threshold`, from `threshold_for_budget`). The API reads it from the same run it loads, and refuses to start if that run has no threshold (a model retrained after the last evaluation). Computing it at API start-up was the alternative; it would make serving depend on the dataset and the window split. A metric, not a param, so re-running evaluate.py works. The re-run changed only the report's latency rows (timing noise).
- **Owner's requirement: a clean, professional interface.** Clarified as the API contract, not a web page: versioned paths (`/v1/score`, `/v1/health`), typed request and response models, descriptions and an example on the `/docs` page.
- **Dependencies:** fastapi and uvicorn at runtime; httpx in the dev group (FastAPI's test client needs it).
- **Finding: NaN requests returned 500.** FastAPI's standard 422 echoes each rejected value back, and NaN can't be written as JSON, so the error handler crashed. Found by a test and confirmed against the app. **Fix:** a custom 422 handler that leaves out the echoed value (`loc` and `msg` still name the field); a small departure from FastAPI's standard error body. Side effect: transaction values aren't repeated back in errors.
- **The docs example is synthetic** (components 0, Amount 25), so no client transaction is committed to the source. The plan had said a real transaction.
- **Store helpers moved to `src/payguard/fraud/tracking.py`** so the API doesn't import from `scripts/`; they raise `StoreError` instead of exiting, and each caller decides how to report it.
- **Manual check against the real server:** three test-window transactions scored bit-for-bit equal to offline `predict_proba`; the stored threshold reads back exactly.
- **Discussion: send the data in time order and compare flags with the truth.** The owner asked whether we test this. Not yet: that's the replay script. It sends the test window in arrival order through the API (model fields only; the label stays in the script) and counts caught, false alerts and missed, with per-request latency. Because the model scores each transaction independently, its totals should match the decision report's operational view exactly, which makes it the parity check as well.
- **Decision: the replay comes next, before Problem 2.** Reason (Claude's recommendation, accepted by the owner): it's part of the base design (Option A), not an addition; it closes two open commitments (end-to-end p99 against the 50 ms limit, and the CLAUDE.md parity test); it's the last part of the presentation; and it's about one coding session. A smaller fallback (parity test only, via pytest) was offered in case time is short.
- **Code review on PR #6: 7 minor findings, no blocker.** Claude recommended and the owner approved:
  - **fixed:** strict request types (`true` and `"25"` were read as 1.0 and 25.0); a test for the start-up success path; a test fixture that restores MLflow's process-wide settings;
  - **comment added:** why the store sits at the repo root;
  - **skipped:** the empty `mlflow.db` created on a fresh clone;
  - **deferred to the replay:** concurrent-load latency (OpenMP threads per request). One request at a time matches the synchronous design, and concurrency depends on traffic volume we don't assume.
  - **The start-up traceback finding was approved as a fix but turned out not to be fixable cleanly:** uvicorn prints a traceback for any start-up failure, even `sys.exit`, and the fix message is already its last line. Left unchanged and reported to the owner.

### Replay (2026-11-25)
- **Discussion: a visual view of the replay.** The owner asked whether we're building a way to watch the process, and for the simplest, cleanest real-time options. None was planned: the README had cut a browser demo page, so the console was going to be the demo. Options: a live terminal panel (standard library, or the `rich` library), a Streamlit dashboard (heavy dependency, second process, reverses the browser-page cut), or Grafana + Prometheus (the industry monitoring stack, needs Docker).
- **Decision: a live terminal panel built with `rich`** (new dependency, approved by the owner). **Grafana + Prometheus go to the possible additions**, next to the Kafka/monitoring addition.
- **Discussion: demo length.** Measured this session: the test window holds 92,576 transactions, and the API handles about 85 a second one at a time in-process (p50 11.5 ms, p99 18.3 ms), so the full window takes ~18 min. The owner asked what a 2–5 minute demo would show. A 10× speed-up of the 12-hour clock still takes 72 min. Fitting all 12 hours into a few minutes needs 310–770 requests a second in parallel, which would turn the demo into a load test at a traffic volume we'd have to assume.
- **First decision, later replaced (see below): the demo replays the two busiest fraud hours, 41–43h** (16,716 transactions, 35 frauds; offline HGB at the live threshold: 29 caught, 1 false alert, 6 missed). **Owner's reason:** 38–40h, the busiest by volume (22 frauds, 8 missed), would misrepresent the results' averages through its high share of missed frauds. *Claude's flag:* 41–43h runs above average the other way (83% recall vs 71% on the whole window), so the report shows the full-window figures beside the slice.
- **Discussion: pacing.** The owner suggested a request about every 100 ms, a little above the 50 ms limit, without having done the maths. Claude's maths: 100 ms is 10 a second, about a 4× speed-up, so 2 hours would take ~30 min and a short demo would show 1–3 frauds. The 50 ms limit is about how long one request takes, while the sending gap is about load, which is a separate quantity.
- **First decision, later replaced: condense the 2 hours into a 5-minute demo (24×), open loop.** Each transaction is sent on its own schedule without waiting for earlier answers, as real traffic arrives, so latency includes any queueing. That's ~56 a second on average, under the ~85 a second the API handles one at a time.
- **Decision (owner): spread each second's transactions evenly within that second.** `Time` is in whole seconds, so k transactions in one second are sent at T + i/k. **Owner's reason:** the API is designed for one transaction at a time, and sending a second's transactions all at once is an artefact of the timestamp resolution. It would inflate the latency of the request served last in each burst. Some overlap remains: about 42% of the slice's transactions fall in seconds with 4 or more (up to 11), so they arrive ≤10.4 ms apart. That's real load from busy seconds.
- **Decision: console summary plus `reports/replay_report.md`**, with a live panel during the run. The real-data parity check (served scores vs offline `predict_proba` for the same run) is part of the replay, because it needs the dataset and the MLflow store. The synthetic-data parity test stays in pytest.
- **Decision: `httpx` moves from the dev group to the main dependencies** (the replay's HTTP client; already locked).
- **Finding (first runs at 24–30×): overlapping requests break the API on default settings.** Each request's HistGradientBoosting call uses OpenMP threads across all 22 cores, so overlapping calls compete for the same cores. At ~58 requests a second the API fell behind (463 in flight), p99 reached ~22 s and some connections dropped. With one inference thread (`OMP_NUM_THREADS=1`) there were no errors, and single-request latency improved (mean 9.5 → 8.3 ms), though busy seconds still queued in one process (p99 ~330 ms at 24×). Four worker processes kept up even at 60×, but uvicorn's multi-worker mode leaves `TCP_NODELAY` off (its sockets are created with protocol 0, which asyncio's no-delay check skips), adding ~40 ms to every kept-alive request. Not pursued further.
- **Decision (owner): load testing is out of scope.** The replay shows the model working on the client's traffic at a realistic pace; it doesn't test capacity.
- **Discussion: the true gap between transactions.** Asked by the owner before choosing a speed-up. In the most fraud-dense windows, real traffic averages one transaction every ~400–450 ms (2.2–2.5 a second), with ~60% sharing their second and up to 10–18 in one second. The busiest seconds, not the average, decide whether requests overlap.
- **Decision (owner): the demo is the 40 minutes with the most frauds, 42:40–43:20, at 4×** (5,351 transactions, 17 frauds; offline: 14 caught, 1 false alert, 3 missed; ~10 minutes). Picked from the most fraud-dense 20-, 40- and 60-minute windows. At 4× the mean gap is ~112 ms, and the busiest second (11 transactions) arrives ~23 ms apart, above the ~10 ms a request takes, so requests don't overlap. This replaces the 41–43h / 24× decision above.
- **Finding (first demo run): latency rose mid-run while Claude ran a second replay and the test suite on the same machine** (p50 up to ~58 ms, p99 ~170 ms, 0 in flight), then recovered once they stopped. Most likely CPU contention (the tests train HGB on all cores; two replay streams overlap). *Lesson: run nothing heavy alongside a live demo.*
- **Result (clean rerun, nothing else running, default threading):** 14 caught / 1 false alert / 3 missed, identical to offline; parity exact (largest difference 0, 0 decisions differ). Latency p50 12.2 ms, p95 21.6, p99 25.6 (limit 50: pass), 1 of 5,351 over 50 ms (max 76.7 ms). Requests ran at most 100 ms behind schedule once (a client-side pause; the replay keeps every send time, so it's visible in the report). This confirms the mid-run rise was interference.
- **Decision (owner): don't adopt `OMP_NUM_THREADS=1` for now.** Claude had recommended documenting it (robust under overlap, slightly faster per request in the probe). **Owner's reason:** it hasn't been tested under the same conditions as the demo. It goes into the README suggestions, to try if replay results on other hardware differ greatly from ours. **Owner's note:** the results depend on the hardware they're run on; recorded in the README Results.
- **Code review on PR #7: 1 important, 5 minor findings; the owner approved fixing all six.** The important one: the README's whole-window example at 60× would overload the API and abort, so it was removed (load testing is out of scope). The minor ones: a panel redraw could show an answered fraud as missed; an empty slice crashed; `--start` accepted invalid minutes; evaluate.py duplicated the latency summary; the H:MM formatting was repeated. **Found while checking the fixes:** a slice with no frauds crashed the shared recall calculation; recall is now undefined (`nan`, shown as n/a) there. Flagged to the owner.
- **Decision (owner): keep the panel as is.** Frames stacked in the terminal during the first run, but the owner found the panel fine.

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

### Client situation (owner, 2026-11-25)
- **What we know about the client's problem:** their support team is drowning. Thousands of free-text customer complaints arrive monthly, all handled **manually** today. They want to know whether LLMs can triage these automatically, routing each complaint to the right team with a summary, **without hallucinating or misrouting sensitive cases**. This is all the context we have.
- **What follows for the prototype:**
  - Every complaint arrives as free text, so the earlier question about the share with free text is settled.
  - The baseline is 100% manual handling. Any complaint triaged automatically cuts the load, and complaints that still go to a human arrive pre-routed and summarised.
  - The client's two worries become the evaluation's priorities: hallucination (invented categories, unfaithful summaries) and misrouted sensitive cases (recall on `requires_human`, sensitive cases routed correctly).

### Brief (from the client, 2026-11-25)
- **Goal:** an LLM pipeline that turns a raw complaint narrative into a structured triage record. Estimate ~3 hours.
- **Data:** CFPB Consumer Complaint Database, a filtered slice of ~300–500 complaints **with consumer narratives**, any product. The exact slice must be documented so the client can reproduce it.
- **Output record:** `category` (routing destination from our own taxonomy of 5–8 categories), `urgency` (low|medium|high), `summary` (1–2 sentences), `requires_human` (bool), `confidence_note` (when/why the triage might be wrong).
- **Provider:** any LLM, free-tier or local is fine; they evaluate the engineering, not the API budget.
- **What they want to see:**
  - The LLM handled robustly as a component: structured output enforcement, failure/retry handling, malformed responses.
  - **An evaluation approach (the heart of Part B):** hand-label a small sample, define what "correct" means, measure something, and say what we'd measure at scale.
  - Failure-mode awareness: hallucinated categories, prompt injection via complaint text, sensitive cases (fraud allegations, legal threats) that must never be auto-closed.
  - Cost/latency awareness: rough per-complaint cost and what it implies at **50,000 complaints/month** (an operating figure given by the client).
- **Not wanted:** fine-tuning; a chatbot UI. A script or notebook that processes a batch is exactly right.

### Data source: narratives removed from the live CFPB database (2026-11-25)
- **Finding (tested on the live service):** the API ignores `has_narrative` (19,397,176 records either way) and rejects `complaint_what_happened` as a field; the current bulk `complaints.csv.zip` (371 MB, 2026-11-24) has no narrative column. CFPB release notes: Release 24 (Sept 2026) removed narratives; Release 23 (July 2026) retired JSON export and capped filtered CSV exports at 100,000 rows. The brief's source can't supply the pipeline's input as written.
- **Options discussed:** (1) an archived pre-removal copy, documented; (2) ask the client for a narrative sample; (3) synthetic narratives on real metadata (rejected as circular for the evaluation).
- **Decision (owner):** the owner emails the client about it and proceeds on the documented assumption that we use an older copy of the dataset. Access had to be proven first.
- **Access proven:** Internet Archive snapshot of CFPB's own bulk file, `https://web.archive.org/web/20260815141332id_/https://files.consumerfinance.gov/ccdb/complaints.csv.zip` (captured 2026-08-15; original Last-Modified 2026-08-15; 1,415,011,387 bytes). Its header includes `Consumer complaint narrative` (16 columns), and the first rows hold real redacted narratives (`XXXX`, `XX/XX/2023`). The `id_` URL serves the raw archived bytes, so the snapshot is fixed; a SHA-256 is recorded on full download.
- **How the slice reaches a clean environment, discussion:** a full download would cost every clean setup 1.4 GB from the Internet Archive (slow, sometimes unreliable) to keep a few hundred rows. Options: (A) full download for everyone; (B) commit the small slice and add a rebuild script that streams a fixed first chunk of the immutable snapshot, hashes it and draws a fixed-seed sample; (C) rebuild script only, so every setup downloads the chunk.
- **Decision (owner): option B.** The slice is committed (the data is CC0 per the API metadata, and ~1 MB), so setup needs no download; the rebuild script lets anyone reproduce it exactly. Committing data is a new pattern for the project (Part 1 commits none). Caveat to check in the data discussion: a first-chunk sample reflects the file's order, so its product/date mix needs checking; if skewed, read a bigger chunk or fall back to the full file. Size: a few hundred, as the client asked (500 proposed, exact number open).
- **Done (B1):** `scripts/triage/get_complaints.py` builds the slice: first 10,000,000 bytes of the snapshot (SHA-256 `334b6c63…14d5`, identical across two downloads), 326,286 whole rows read, 500 narratives drawn with seed 42 (NumPy `RandomState`). Slice `data/triage/complaints_sample.csv`, 822 KB, SHA-256 `42b27d0b…4dcc`. A first look shows mostly 2026 complaints (338 of them from June) and a broad product mix led by debt collection (158); to be discussed in the data review before B2.
- **Data discussion (2026-11-25, ad-hoc analysis; owner decisions at the end):**
  - **Product skew explained:** CFPB's whole database for Feb–Jul 2026 is 90.7% credit reporting (3.64M complaints, live API counts), and so is our 10 MB chunk (90%). But only 0.1% of credit-reporting complaints carry a narrative, against 25.8% for other products. So the slice (5% credit reporting, 32% debt collection) represents complaints with narratives, which is the brief's population. It isn't a file-order artefact. In real intake, credit reporting would dominate the volume.
  - **Length:** median 177 words (~270 tokens), p90 456 words, p99 ~1,400 tokens, max ~2,500 tokens. About 173k narrative tokens across the 500.
  - **Redaction:** 84% contain `XXXX`-style redaction; 41% contain amounts as `{$…}`.
  - **Templates:** 7 groups of identical narratives (20 extra copies). One FDCPA template appears 12 times against 12 different companies and product labels, likely credit-repair or template filings. It shows CFPB's product label follows the company more than the text.
  - **Sensitive-case signals (keyword counts, rough):** fraud, scam or unauthorised 22%; legal words 12%; regulator mentions 13%; hardship or vulnerability words 8%. Tags: Servicemember 63, Older American 46 (19% tagged).
  - **Prompt injection:** no real injection attempts. All 5 keyword hits were ordinary uses of "disregard", so adversarial cases would have to be built.
  - **Correction to the product-skew reading:** CFPB publishes a narrative only when the consumer consents (and after scrubbing personal details). So the 0.1% means credit-reporting narratives were rarely *published*, not that those complaints had no text. The earlier idea that most real intake could be routed by a metadata rule without an LLM doesn't follow and is dropped.
  - **Redaction is CFPB's, not ours:** the archived file is CFPB's official bulk file byte for byte, `XXXX` already appears in the raw chunk, and the slice script copies text unchanged. CFPB's release notes say narratives were published "after we take steps to remove personal information". The live API can't be compared directly because it no longer serves narratives.
  - **Decisions (owner):** keep the slice as is; keep the template duplicates; no data-understanding script (key points go in the README). Client-email questions: explained further, owner to decide.
  - **Other:** all submitted via Web; dates mostly Feb–Jul 2026 (2 before 2025); 58 issues and 42 sub-products, with "I do not know" the second most common sub-product (75).
- Other leads, not checked: Hugging Face mirrors (e.g. `CFPB/consumer-finance-complaints`, 2024) and Wayback snapshots at other dates (e.g. 2025-05-31).

### B2 starting decisions (owner, 2026-11-25)
- **Taxonomy: our own routing teams plus a CFPB map.** 5–8 categories defined from the text's point of view (where the complaint should be handled), plus a small CFPB product/issue → category table used only as a weak reference for broad agreement on all 500. Reason: the data review showed CFPB's product label follows the company more than the text, so it can't be ground truth, but it's free and covers every complaint.
- **`requires_human`: flags plus a policy in code.** The LLM returns explicit flags; code derives `requires_human` from a fixed, testable policy that can also use CFPB tags. Prompt injection then can't switch the rule off.
- **Gold set: the owner labels ~80 complaints blind** against the B2 guide, without seeing model output, split into dev and held-out parts. Chosen over Claude-drafted labels to avoid anchoring the labels toward LLM answers.
- **Tags and the policy (owner):** CFPB tags (Older American, Servicemember) **always force human review, as a rule.** No earlier check (empty narrative, LLM failure, other category) may discard the tag check, so the policy collects every reason that applies instead of stopping at the first match; the reasons go into the output record. The tag doesn't raise urgency: urgency comes from the complaint's content, so a tagged complaint about a minor issue is reviewed at lower priority but never auto-closed. Cost: about 11% more reviews in the slice (53 tagged complaints with nothing sensitive in the text), accepted because the client handles everything manually today.
- **Empty or near-empty narratives** are caught in code before any LLM call and sent to review (threshold ~5 words, an assumption for the README).
- **Urgency and redacted dates (owner's question; measured on the 500, keyword-based, rough):** 46% contain a redacted date (22% `XX/XX/XXXX`, 139 complaints with CFPB's malformed `XX/XX/year>` token, 1% with the year kept); exactly 1 explicit date survives. Relative time survives in 29% ("3 weeks", "almost a month", "ago"). 69% have no usable time cue. Words signalling imminent or ongoing harm (scheduled, foreclosure sale, repossession, frozen, garnishment…) appear in 11%, and 32 of those 55 carry some time cue. Owner's position: time always matters, but how much it weighs on urgency must be decided given this.
- **Decision (owner): harm-led urgency; time never lowers it.** The kind of harm and its state (ongoing, imminent, past) set the level (high: ongoing or imminent loss of money, funds, home or car, or any safety risk; medium: real but not imminent harm; low: service or information problems, or resolved). Time cues raise urgency only when present in the text; missing or redacted time never lowers it, since 69% of complaints carry no time cue. When a redacted date could matter, the model says so in `confidence_note`. README note: on the client's unredacted complaints, time would weigh more.
- **Approved (owner): the rest of the B2 draft.** Seven categories (`fraud_scams`, `credit_reporting`, `debt_collection`, `banking_payments`, `credit_cards`, `lending`, `other`), with rule order fraud > credit-report content > product, which the CFPB map follows too. Five flags (`fraud_allegation`, `legal_threat`, `vulnerable_customer`, `safety_risk`, `discrimination`), with the boundaries discussed: citing a law isn't a legal threat, collector rudeness isn't a safety risk, discrimination needs a protected characteristic. No regulator or tone flag. Gold set: 80 complaints, 30 dev / 50 held-out, no identical narrative on both sides, labeller sees narrative and tags but not CFPB product or issue; gold `requires_human` derived by the same policy code. Rare flags (safety, discrimination) will be exercised by the synthetic set.
- **Labelling logistics (owner):** the labelling file is built before the policy, so the owner labels in parallel with the pipeline build. Format stays CSV; the owner labels in **Google Sheets**, adding dropdowns with Gemini inside Sheets (Claude supplies the prompt). Uploading the complaints to Google is the owner's call (public CFPB data, treated as client data). Flag cells stay blank (no pre-filled "n"), so blanks mean "not labelled yet" and don't nudge answers toward "no". The file is plain UTF-8 (no BOM, which only Excel needed).
- **Reviewer capacity: not a blocker (owner).** Against today's fully manual handling, the prototype already cuts the load substantially. If the review queue still outruns the team, priority tiers or narrower rules for tags are a **future modification** to note for the client, not a question for them now.
- **Done (B2):** taxonomy and CFPB map (`6a56227`), labelling file and generated guide (same commit), review policy (`2e17447`). Gold labels filled in (see the Gemini Neon entry below).
- **Provider (owner): Claude**, since the team has a Claude subscription. Open: a Claude chat subscription doesn't include API access (the API is billed separately), and this machine has no API key, `ant` CLI or standalone `claude` CLI. How the pipeline reaches Claude is to be decided before B3.
- **Decision (owner): route A, the Claude API with a key from the Claude Console** (billed separately from the subscription), chosen over driving the subscription through Claude Code's headless mode. Reason: the brief judges the LLM as an engineered component (schema enforcement, retries, malformed responses, measured cost per complaint), and only the API reports tokens per call. The owner creates the key and sets `ANTHROPIC_API_KEY`; Claude never handles it. Triage outputs get committed so the eval reruns without a key.
- **Decision (owner): Claude Haiku 5.5** (`claude-haiku-5-5`, $0.10/$0.50 per M tokens) as the model to build against; the model stays one setting so others can be compared on the dev set later.
- **Superseded (owner, same day): free route instead of the paid API.** The owner needs a free option, and the architecture matters more than the results. Options weighed: Gemini free tier (strong JSON-schema support, but tight per-minute and per-day caps that change, complaints sent to Google, whose free-tier data may be used for product improvement, and reproducers need a key) against a **local model via Ollama** (free, no caps, data never leaves the machine, schema-constrained output through Ollama's REST API with httpx, so no new Python dependency). Machine: RTX 4070 Laptop GPU, 8 GB VRAM, CUDA visible in WSL; 15 GB RAM; 22 threads.
- **Decision (owner): local model via Ollama.** The pipeline reaches the model through one small boundary (`triage(narrative) -> Result`), so a hosted model is a one-module swap. Only the backend in use gets built.
- **Decision (owner, later revised): a ~4B model as the default, plus an 8–9B run on the 30 dev labels** to quantify what the smaller model gives up. Owner's reasoning: reproducibility favours the smaller model. Discussed: 5–6B isn't offered by current families (they jump from ~4B to 8–9B; the only 5–6B models are ~2 years old). Smaller widens who can *run* the pipeline (8 GB RAM, CPU-only possible), but it doesn't make results more reproducible: rerunning the eval needs only the committed outputs, and regenerating them needs the pinned model digest, temperature 0 and a seed at any size. Candidates (updated 1–2 months ago): Qwen 3.5 4B, Gemma 4 e4B, Granite 4.2 3B; trialled on 5 complaints, then the owner picks.
- **Gold labels made by Gemini Neon (high effort) and accepted as they are (owner).** Gemini Neon labelled all 80 rows from the labelling guide instead of the owner. Reason: the ~3h estimate doesn't allow reading and labelling 80 complaints by hand, and as a non-expert the owner's own labels wouldn't be much firmer. The owner's view is that a stronger model's labels roughly mimic the gap between the ~4B model and a human. Claude's review found the file valid (80/80, `--check` clean) but saw five patterns where labels follow rules the guide doesn't state: fraud urgency rising with the amount lost, the credit-report-first rule applied unevenly to collector complaints (23243304 vs 23067225), an uneven "severe hardship" line, one locked account rated low, and one high without a scheduled foreclosure. Asked whether those could count as human error: no, since a model made them. The honest framing is agreement with a stronger model, label noise expected even from human labellers, and in production a reference built from the client team's own past routing. **Decision:** don't relabel or patch the guide (a real build wouldn't hand-label either); record it all as README limitations, with the time limit as the stated reason. The README's "labelled blind by the project owner" line was corrected. AI_USAGE.md isn't updated for the labelling (owner's decision, for a separate reason).
- **Rare flags: synthetic set stays; enriched real sampling is a possible addition (owner).** The owner asked whether a synthetic set is standard practice. It is for targeted behaviour tests, red-teaming and fixed trust-and-safety checks, but synthetic cases are cleaner than real ones, so they show that obvious cases get caught, not real-world recall. They should be scored apart from real data and written by a different model from the one being tested. The usual way to measure rare classes on real text is enriched sampling: a keyword search of the wider data, then labelling. It wasn't built because it needs another labelling pass the ~3h budget doesn't cover.
- **Trial narrowed to Granite 4.2 3B and Qwen 3.5 4B (owner).** Gemma 4 e4B dropped: it runs like 4B but downloads and loads like ~8B (6.6 GB against 2.2 and 3.3 GB), which works against choosing a small model so more people can run it.
- **8–9B comparison removed for now and moved to the README as a possible addition (owner).** The owner's point: the Gemini-labelled gold set already compares the pipeline with a stronger model, though not under controlled conditions. Discussed: only the 8–9B run changes model size alone (same prompt, schema, machine, rows), so dropping it loses the "what does going small cost" number; it also saves a ~5–7 GB download.
- **Ollama install (owner runs it, since it needs sudo):** the official script `curl -fsSL https://ollama.com/install.sh | sh` failed on this WSL Ubuntu without `zstd`. Fix: `sudo apt-get install zstd`, then rerun. README Setup needs both steps once the triage setup is written.
- **B3 plan approved (owner).** Sessions: S0 model trial (Granite vs Qwen on 5 dev rows, owner picks, digest pinned), S1 pipeline record + batch runner, S2 evaluation report, S3 write-up, clean-room run and PR. Choices made while planning:
  - **Run all 500** complaints, not just the 80 labelled: it also gives CFPB agreement, template consistency, and failure, latency and token figures from a realistic batch.
  - **Summaries: automatic checks plus an owner spot-check of 10.** The automatic checks catch numbers or amounts not in the complaint, more than 2 sentences, and empty summaries; the owner judges 10 test summaries for faithfulness.
  - **Outputs as CSV** (review reasons `; `-joined), committed so the eval reruns without Ollama.
  - **No synthetic set (owner, supersedes the earlier "rare flags will be exercised by the synthetic set" and the planned synthetic injection cases).** Prompt injection and the `safety_risk`/`discrimination` flags go into the README as limitations: the injection defences are structural (fenced text, schema-constrained output, `requires_human` in code) but untested against attacks. Briefly chosen first: Gemini writes the cases; dropped before the plan was approved.
  - Small extras in S1: `table()`/`pct()` move to `src/payguard/reporting.py` for both parts; `pydantic`, already imported by `llm.py` through fastapi, gets declared.
- **Live panel and limited runs (owner).** The owner wants to watch runs live with rich, as in Part 1, and runs them in their own terminal. `run_triage.py --limit N` takes the first N gold complaints (dev, then test) so the panel compares with gold as rows arrive, and writes a git-ignored `data/triage/trial_<model>.csv`; only a full run writes the committed `triage_sample.csv`. The live trial replaced the scripted 5-complaint trial.
- **Model: Granite 4.2 3B (owner), digest `40577dc168a3`, now `--model`'s default.** Owner's runs on the first 20 dev complaints:
  - Granite: category 20/20, urgency 14/20, sent exactly the 7 the labels need to a human, 0 false flags, 0 sensitive misses; median 3.9 s; but 10/20 summaries exceed 2 sentences.
  - Qwen 3.5 4B (`d8b0f5e9760c`): category 19/20, urgency 12/20, 0 sensitive misses, best summaries (0 issues), but 10 false flags (7 `legal_threat`: it treats citing a law as a threat) sent 15/20 to a human, which undercuts the workload goal; median 4.6 s.
  - Reasoning: Granite's routing matched the labels and its weakness is cosmetic and caught by the summary check; Qwen's weakness hits the business goal. It's also smaller and faster. Caveat: 20 dev complaints only.
  - Finding for the limitations: the same complaint can get a different answer between runs despite temperature 0 and a seed (23130174 was high in the scripted trial, medium in the live run).
- **Summary prompt tightened (owner):** at most two short sentences, under 50 words, leaving out contact histories. Decided on the 20 dev results, before any test results: on the same 20, mean summary length fell from 51 to 33 words (max 77 → 45), output tokens from 188 to 158, with one urgency change (toward gold). Committed `9577b41`.
- **80-complaint run (owner, new prompt):** test 50: category 78%, urgency 72%, `requires_human` recall 24/27 (89%), 3 sensitive misses; 0 failures; summaries 33 words on average, no invented numbers. Patterns: `legal_threat` caught 0/5 (court papers, a lawsuit threat), 7 false fraud flags with complaints routed to `fraud_scams`, never "low" urgency. Workload: 39 of 80 (48.8%) routed with no human; 13 go to a human for a tag alone; 0 lost to preprocessing. Funnel: 326,286 complaints read from the archive, 8,827 (2.7%) with a published narrative (8,120 unique), 500 sampled.
- **Legal-words backstop in the policy (owner, option A), decided after test results were seen.** Legal language (attorney, lawyer, lawsuit, sue, court, small claims, litigation, legal action; word-bounded) sends a complaint to a human whatever the model says, as the reason `legal words`; the model's own flag stays a separate reason. Options weighed: a stronger prompt (hard to trust after 0/5) or accepting it as a limitation. Matches 63 of 500 (12.6%). Re-scored on the owner's 80: automation 48.8% → 46.2%, recall 95% (test 92.6%), misses 4 → 2 (24398174, withheld funds rated medium; 23110857, borderline `other`).
- **Owner's question, answered for the write-up:** the result supports a shadow-mode pilot, not a switch. The 3B model is the largest single limit on accuracy (flags, urgency); label noise, redaction and taxonomy edge cases cap it too. The safety net is in code and doesn't depend on the model. The ~49% is a cut in triage work, not in complaint handling.
- **Gemini comparison attempted, then dropped (owner).** To test whether the 3B model is the limit, the owner tried their free Gemini API key (3 requests a minute, 4 complaints per request; `gemini-4-neon` excluded because it made the gold labels). Every free-tier request with our prompt got 503 "high demand" on `gemini-3.8-flash`, `-3.7-flash` and `-3.6-flash`, even though a tiny test request to 3.6 Flash succeeded, and a step-by-step check gave the same result. The owner scratched it; the script, tests and payloads were removed uncommitted, and no key was ever stored in the repo. The larger-model comparison stays a possible addition.

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

### Layout for Two Problems (2026-11-25)
- **Discussion:** the code was already split by problem (`src/payguard/fraud/`), but `scripts/`, `reports/` and `tests/` were flat and held only fraud files. Three options: (A) split only those shared folders by problem; (B) one self-contained folder per problem, possibly with its own `pyproject.toml` as a uv workspace; (C) add triage beside fraud and move nothing.
- **Decision (owner): option A.** Layout: `src/payguard/{fraud,triage}/`, `scripts/{fraud,triage}/`, `reports/{fraud,triage}/`, `tests/{fraud,triage}/`, with one `pyproject.toml`, one lock and one setup path. Triage-only dependencies can go in their own dependency group so the fraud API doesn't install them (decided in the Part 2 plan). B was rejected as ceremony with no current need (a second dependency file and lock to maintain); C because the flat folders would mix the two problems.
- **Scope argument for the final write-up (owner):** the brief's ~3 hours per part is an estimate, not a requirement. If the work reads as over-built, the answer is a list of what could easily be cut if the timescale were binding, while the "Possible additions" list shows how much further a real build would go.
