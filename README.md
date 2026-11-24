# PayGuard

Prototype solutions for a finance client's two problems: **(1) real-time fraud detection** on card transactions, and **(2) complaint triage**.

## Setup

Tested from a clean environment on Linux. You need `curl` and an internet connection.

1. **Install uv** (the Python package and project manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. **Install dependencies.** This also installs Python 3.12 if it's missing:
   ```bash
   uv sync
   ```
3. **Get the data.** The script asks which source to use, or you can pass `--source`:
   ```bash
   uv run scripts/get_data.py                  # asks: kaggle / manual
   uv run scripts/get_data.py --source kaggle  # Kaggle CLI via uvx; no install or account needed
   ```
   For a manual download, get it from https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud, place `creditcard.csv` at `data/raw/creditcard.csv` and re-run the script to verify it.
   Both routes are checked against the same SHA-256: `76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89`.
4. **(Optional) Regenerate the data report.** The analysis tools sit in a separate `analysis` dependency group, so the serving runtime doesn't install them:
   ```bash
   uv run --group analysis scripts/data_understanding.py   # writes reports/data_understanding.md + figures
   ```

## Development Workflow

This is a single-developer project with AI assistance (see [AI_USAGE.md](AI_USAGE.md)).

1. `main` always works. Each step happens on a short-lived branch (`feat/…`, `fix/…`, `docs/…`).
2. Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, …).
3. Each branch becomes a PR that explains what changed, why, how to verify it, and any AI_USAGE update.
4. An automated code review runs on each PR and its findings are posted as comments. Real problems are fixed; anything left unfixed gets an explanation.
5. The owner reviews and merges. Merging means the code is final.
6. At milestones, such as when a problem is finished, the owner may run a deeper multi-agent review.

## Problem 1: Fraud Detection

**Goal:** flag fraudulent card transactions with a model that serves real-time inference.

### Approach
*In planning. Decisions so far:*
- **Latency baseline: p99 ≤ 50 ms per transaction.** This is the lenient end of the published 10–50 ms range for fraud scoring, and improving on it is a goal if we have capacity.
- **Synchronous scoring, one transaction at a time.** Batch scoring can't decide on a transaction inside its authorisation window. *Review later:* server-side micro-batching.
- **Real-time simulation: replay to a scoring API.** A script sends the client's transactions in time order to a local scoring service, and we measure latency per request.
- **Data understanding** ([report](reports/data_understanding.md)): about 211 frauds on day 2, so small model differences are noise. Several features drift between the two days, which supports a time split. Seven features separate fraud strongly on their own, so a simple baseline is credible. There are 1,081 exact duplicates, all within the same second. Analysis is look-only; no data is changed.
- **No training-serving skew by design:** training and serving share one preprocessing code path, and a parity test checks the API's scores against the offline scores.

### Evaluation
*In planning. Decisions so far:*
- **Alert budget: 0.1% of transactions** (~140 alerts a day), a sample figure based on the Fraud Detection Handbook's note that real systems run close to 0.1%. The client hasn't provided its review capacity.
- **Selection rule, fixed before any model is compared:** choose by average precision, provided the model isn't worse than the alternatives at the 0.1% budget. If the two disagree, that's reported as a finding, not settled by changing the rule.
- **Model gains are judged, not gated.** A decision report puts each candidate next to the simpler model: average precision and frauds caught a day at the budget, each with a bootstrap 95% range for the difference, plus p99 latency and complexity. The owner decides whether a gain is worth its cost, and the reason is recorded. The report's contents are fixed before any comparison is run.
- **Validation: a single time-ordered train / validation / test split.** Random k-fold would train on future transactions, hide the drift between the two days, and put identical duplicate rows on both sides of a fold. Forward-chaining (the time-aware form of k-fold) was considered, but with only 48 hours it can't separate drift from time-of-day effects, so it adds machinery without a reliable reading.
- **Windows:** train on day 1 (0–24h, 281 frauds), set the threshold on the first half of day 2 (24–36h, 96 frauds), test on the second half (36–48h, 115 frauds). There's no gap between windows, and the model is trained on the training window only, so the threshold always comes from a model that never saw the validation data.
- **Duplicates are kept.** The 1,081 exact copies are part of the client's real stream, and deduplicating them belongs upstream, at ingestion, not in the model.
- **Report shows validation beside test**, as a rough two-point view over time. The windows differ in fraud mix (night vs daytime), so it isn't a clean measure of drift.
- **Metrics reported:** average precision (PR-AUC, computed step-wise), precision and recall at the 0.1% budget, and ROC-AUC (reference only; it can rank models misleadingly on imbalanced data).
- **Live operating point:** a fixed score threshold set on validation data to flag about 0.1% of transactions. A daily top-k ranking isn't possible when scoring one transaction at a time.

### Results
*Pending.*

### Cut / Added
- **Cut: data versioning (DVC).** The data is one fixed source file, so a hash-checked download script gives the same guarantee without needing a storage remote. If the client's data starts changing over time, revisit this with DVC or the client's own data platform.
- **Cut: third-party mirror download.** Kaggle's public download works without an account, so a second automatic source was redundant. If Kaggle ever requires sign-in, the manual route covers it.
- **Possible additions if time allows: Kafka streaming.** Either a local Kafka pipeline, or Kafka beside the API for decision logging and monitoring. A request/response API matches the authorisation path, so the prototype starts there.
- **Cut: Jupyter notebooks.** The presentation shows findings, not analysis code, so data understanding is a script that writes a Markdown report. Model comparison uses MLflow's UI. This leaves no Jupyter tooling in the project.
- **Possible addition: deduplicate exact copies for fitting and threshold setting only** (train and validation windows), keeping them in test and the replay. 13 distinct frauds appear 32 times, so they carry extra weight in training. Not done for now: the gain is unproven, and deduplication normally happens upstream, at ingestion, by transaction ID.
- **Cut: forward-chaining validation.** With one daily cycle of data, changes from one fold to the next can't be told apart from time-of-day effects. It's the recommended method once the client provides several weeks of history, because it shows how a model holds up over time and whether retraining on fresher data helps.
- **Out of scope: feature store.** It's how enterprises centralise feature definitions, but the prototype's single shared code path covers the same need at this scale.

### Limitations
- The data covers only about 2 days of transactions, so we can't simulate realistic feedback delay (the time before fraud labels arrive). The windows have no gap between them for that reason: a gap of a few hours would cost frauds without modelling a delay of days.
- There's no card or customer ID, so card-level metrics (such as card precision top-k, which counts each compromised card once) and history (velocity) features aren't possible.
- There's no transaction ID, so exact duplicates (same values, same second) can't be told apart as retries, double submissions or export errors. Fraud is 10x more common inside these duplicate groups (1.73% against 0.173%), which suggests card-testing behaviour. Using that as a live signal needs state about earlier transactions, which is out of scope for the same reason as velocity features.
- Identical genuine transactions recur at different times, some across the train/test boundary (805 groups), consistent with recurring payments. The model sees these patterns in training, as it would live.
- The features are anonymised with PCA, which limits feature engineering and how well we can explain decisions.

## Problem 2: Complaint Triage

*Not started.*
