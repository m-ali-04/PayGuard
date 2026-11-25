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
5. **Train the shortlisted fraud models.** This fits each candidate on the training window and logs it to a local MLflow store (`mlflow.db`, `mlruns/`, both gitignored):
   ```bash
   uv run scripts/train.py
   uv run mlflow ui --backend-store-uri sqlite:///mlflow.db   # from the repo root; browse at http://127.0.0.1:5000
   ```
6. **Write the decision report.** This scores the latest run of each model on the validation and test windows, writes `reports/decision_report.md` and logs the headline metrics to each model's MLflow run (about 3 minutes, mostly the bootstrap):
   ```bash
   uv run scripts/evaluate.py
   ```
7. **Serve the selected model.** The API loads the selected model's latest run and the threshold that step 6 logged on that same run (it refuses to start if that run hasn't been evaluated):
   ```bash
   uv run uvicorn payguard.fraud.api:app   # from the repo root; interactive docs at http://127.0.0.1:8000/docs
   ```
8. **Replay the client's traffic through the API** (in a second terminal, with the API running). The default replays the demo slice, 42:40–43:20 at 4× (~10 minutes), with a live panel, then checks parity against the offline model and writes `reports/replay_report.md`. Run nothing heavy on the machine meanwhile: the replay, API and model share it, so other work shows up as latency.
   ```bash
   uv run scripts/replay.py
   uv run scripts/replay.py --start 39:31 --length 20   # another slice, same pace (keep the speed low enough that requests don't overlap)
   ```
   Score one transaction (the 28 components and Amount; other fields are ignored):
   ```bash
   curl -s http://127.0.0.1:8000/v1/score -H 'content-type: application/json' \
     -d "{$(for i in $(seq 1 28); do printf '"V%d": 0, ' $i; done)\"Amount\": 25}"
   # {"fraud_score":…,"alert":false,"threshold":0.357…,"model_run_id":"…"}
   ```
8. **Run the tests.** The data tests are skipped if the dataset hasn't been downloaded:
   ```bash
   uv run pytest
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
- **Replay demo: the 40 minutes with the most frauds (42:40–43:20, 17 frauds) at 4× real time (~10 minutes), with a live terminal panel.** The client's traffic averages one transaction every ~450 ms there, so at 4× even the busiest second's transactions arrive ~23 ms apart, above the ~10 ms a request takes: requests don't overlap, because load testing is out of scope. Requests go out on schedule without waiting for earlier answers, as real traffic does. Timestamps are whole seconds, so each second's transactions are spread evenly across it rather than sent as one burst, which would be an artefact of the timestamp resolution. A fraud-dense slice runs above average, so the report shows the whole-window figures beside it.
- **Parity check on real data:** after each replay, the served scores are compared with the same MLflow run's model loaded offline (expected: identical scores and decisions).
- **Data understanding** ([report](reports/data_understanding.md)): about 211 frauds on day 2, so small model differences are noise. Several features drift between the two days, which supports a time split. Seven features separate fraud strongly on their own, so a simple baseline is credible. There are 1,081 exact duplicates, all within the same second. Analysis is look-only; no data is changed.
- **Shortlist: logistic regression (interpretable baseline) and gradient-boosted trees** (scikit-learn's `HistGradientBoostingClassifier`), both with default settings except two stability settings on the boosted trees. Early stopping is off, because it holds out a random sample of training rows and would shuffle time. `l2_regularization=1.0` (XGBoost's default for the same term), because with sklearn's default of 0 its training diverged on this data: scores stuck at exactly 1.0, so it couldn't rank its top alerts. Twelve model families were considered. Random forest usually trails boosted trees; k-NN, kernel SVM and neural networks fit poorly here (latency, training cost, tuning); sequence and graph models need card history the data doesn't have.
- **Class imbalance:** no resampling. Logistic regression weights the rare fraud class up (`class_weight="balanced"`); the trees use defaults.
- **Features: the 28 anonymised components and Amount (log-transformed).** `Time` counts seconds since the file started, so it can't be computed live, and it's dropped.
- **Preprocessing lives inside each model's saved pipeline**, so the API loads one artifact that carries its own transforms. The pipeline picks its input fields by name, so a raw transaction scores the same in any field order or with extra fields; tests check this, and that a saved and reloaded model gives identical scores.
- **Models are logged with MLflow** in its default safe format (skops), with the pinned dependency versions and the model's contract recorded beside it: the 29 model fields in (no `Time`, which can't be computed live), fraud probabilities out. Code lives in `src/payguard/fraud/` (`data.py` for the windows, `models.py` for the pipelines), shared by training, tests and the API.
- **Scoring API (FastAPI):** `POST /v1/score` takes one transaction and returns the fraud score, the alert decision, the threshold and the MLflow run that scored it; `GET /v1/health` shows the model being served. It serves the selected model (`SELECTED` in `models.py`) from its latest MLflow run, with the threshold `scripts/evaluate.py` logs on that same run, so a model is never paired with another model's cut. Requests are validated against the 29 model fields (built from the same field list as the model; NaN, Infinity and negative amounts are refused with a 422 naming the field), and paths are versioned so the contract can change without breaking callers.
- **No training-serving skew by design:** training and serving share one preprocessing code path, and a parity test checks the API's scores against the offline scores.

### Evaluation
*Decisions:*
- **Alert budget: 0.2% of transactions** (~285 alerts a day), a sample figure chosen by the owner; the client hasn't provided its review capacity. It started at 0.1%, the Fraud Detection Handbook's real-world figure, but that sat below the 0.173% fraud rate and capped recall at 58% on an assumption of our own. 0.2% is just above the fraud rate, so the model, not the budget, is the limit. Changed before any model was scored.
- **Selection rule, fixed before any model is compared:** choose by average precision, provided the model isn't worse than the alternatives at the alert budget. If the two disagree, that's reported as a finding, not settled by changing the rule.
- **Model gains are judged, not gated.** A decision report puts each candidate next to the simpler model: average precision and frauds caught at the budget (counted per test window, not scaled to a day, since the 12-hour window is the daytime half), each with a bootstrap 95% range for the difference, plus p99 latency and complexity. The owner decides whether a gain is worth its cost, and the reason is recorded. The report's contents are fixed before any comparison is run.
- **Validation: a single time-ordered train / validation / test split.** Random k-fold would train on future transactions, hide the drift between the two days, and put identical duplicate rows on both sides of a fold. Forward-chaining (the time-aware form of k-fold) was considered, but with only 48 hours it can't separate drift from time-of-day effects, so it adds machinery without a reliable reading.
- **Windows:** train on day 1 (0–24h, 281 frauds), set the threshold on the first half of day 2 (24–36h, 96 frauds), test on the second half (36–48h, 115 frauds). There's no gap between windows, and the model is trained on the training window only, so the threshold always comes from a model that never saw the validation data.
- **Duplicates are kept.** The 1,081 exact copies are part of the client's real stream, and deduplicating them belongs upstream, at ingestion, not in the model.
- **Report shows validation beside test**, as a rough two-point view over time. The windows differ in fraud mix (night vs daytime), so it isn't a clean measure of drift.
- **Metrics reported:** average precision (PR-AUC, computed step-wise), precision and recall at the budget, and ROC-AUC (reference only; it can rank models misleadingly on imbalanced data).
- **Live operating point:** a fixed score threshold set on validation data to flag 0.2% of transactions there. A daily top-k ranking isn't possible when scoring one transaction at a time.

### Results
Full numbers: [decision report](reports/decision_report.md) (regenerate with `uv run scripts/evaluate.py`). Test window 36–48h, 115 frauds, budget 0.2% = 185 alerts.

| | Logistic regression | Gradient-boosted trees (HGB) |
|---|---|---|
| Average precision | 0.677 | **0.732** |
| Frauds caught at the budget (of 115) | 88 | **90** |
| Threshold fixed on validation, applied to test: alerts / caught | 82 / 68 | 96 / **82** |
| p99 latency, model only (limit 50 ms) | ~7 ms | 16–18 ms (varies by run) |
| Saved model size | 146 KB | 1,057 KB |

- **Selected model: gradient-boosted trees (owner's decision).** It ranks better and catches 14 more frauds when the threshold is fixed in advance, as it would be live. Its threshold is more stable: logistic regression's scores bunch near 1.0, so a tiny change in its cut moves many alerts. It also holds up better from night to day (71% vs 59% of frauds caught with the night-set threshold). The larger model file isn't a limitation here, and its latency is well under the 50 ms limit.
- **How certain the gain is:** the bootstrap 95% ranges for the difference include zero (average precision +0.055 [−0.016, +0.121], frauds caught +2 [−3, +7]). With 115 test frauds, the two models can't be separated with confidence on those measures; the choice rests on live behaviour as well.
- **Budget beyond 0.2% buys little:** checking 0.3% of transactions catches about 92 of 115, and 5% only about 100. The last ~20% of frauds look genuine to both models, and catching them would take new information such as card history.
- **The night-set threshold is too strict by day:** live, both models flag about half the 0.2% budget on the test window. Both genuine and fraud scores run lower by day, so a single fixed threshold misses daytime fraud. See Limitations.

**Replay through the API** ([replay report](reports/replay_report.md), regenerate with `uv run scripts/replay.py`): the demo slice, 42:40–43:20 at 4× real time, 5,351 transactions and 17 frauds.

| | Replay (API) | Offline, same slice | Offline, whole test window |
|---|---|---|---|
| Caught / false alerts / missed | 14 / 1 / 3 | 14 / 1 / 3 | 82 / 14 / 33 |
| Recall | 82.4% | 82.4% | 71.3% |

- **Parity holds on real data:** all 5,351 served scores equal the offline scores bit for bit, and no alert decision differs, so serving adds no skew.
- **End-to-end latency is within the limit:** p50 12.2 ms, p99 25.6 ms (limit 50 ms), 1 request in 5,351 above 50 ms (max 76.7 ms), measured from request sent to answer received, with the client on the same machine. Latency figures depend on the hardware they're run on (here WSL2 on 22 logical cores) and on what else runs at the same time. Compared with the model alone (p99 ~14 ms), the HTTP round trip, request validation and building the input row add roughly 6–12 ms.
- **The slice runs above average** (82% recall vs 71% on the whole window), because it was chosen as the most fraud-dense 40 minutes.

### Cut / Added
- **Cut: data versioning (DVC).** The data is one fixed source file, so a hash-checked download script gives the same guarantee without needing a storage remote. If the client's data starts changing over time, revisit this with DVC or the client's own data platform.
- **Cut: third-party mirror download.** Kaggle's public download works without an account, so a second automatic source was redundant. If Kaggle ever requires sign-in, the manual route covers it.
- **Possible additions if time allows: Kafka streaming.** Either a local Kafka pipeline, or Kafka beside the API for decision logging and monitoring. A request/response API matches the authorisation path, so the prototype starts there.
- **Cut: Jupyter notebooks.** The presentation shows findings, not analysis code, so data understanding is a script that writes a Markdown report. Model comparison uses MLflow's UI. This leaves no Jupyter tooling in the project.
- **Possible addition: deduplicate exact copies for fitting and threshold setting only** (train and validation windows), keeping them in test and the replay. 13 distinct frauds appear 32 times across the data (9 extra fraud copies in the training window), so they carry extra weight. Not done for now: the gain is unproven, and deduplication normally happens upstream, at ingestion, by transaction ID.
- **Cut: forward-chaining validation.** With one daily cycle of data, changes from one fold to the next can't be told apart from time-of-day effects. It's the recommended method once the client provides several weeks of history, because it shows how a model holds up over time and whether retraining on fresher data helps.
- **Cut: resampling (SMOTE, undersampling).** It adds a step that never runs live, and it hasn't shown gains on ranking metrics such as average precision.
- **Possible addition: hour-of-day feature.** Fraud runs 4.3x higher in quiet hours, but the data's clock start is unknown and covers a single night, so the feature would rest on an assumption and one day of evidence. It can be tested as one variant through the decision report.
- **Possible addition: anomaly detection** (for example Isolation Forest) as a companion signal for new fraud patterns that labels don't cover yet.
- **Cut: SHAP explanations.** The client didn't ask for explainability, and per-decision attributions would point to anonymised PCA fields with no business meaning. Revisit if the client or a regulator requires explanations.
- **Possible addition: time-of-day handling,** once several weeks of data show the day/night pattern regularly. From cheapest to most involved: separate thresholds for busy and quiet hours, a time-of-day feature, or separate models for each (each would train on fewer frauds). Each option would be tested through the decision report.
- **Cut: authentication, rate limiting and request logging on the API.** They belong to the client's gateway and platform; request logging and monitoring are covered by the Kafka addition above.
- **Cut: a browser demo page.** The interactive docs page (`/docs`) already lets anyone send a transaction and see the decision; the live demo is the replay's terminal panel.
- **Suggestion: one inference thread per request (`OMP_NUM_THREADS=1`), if replay results on other hardware differ greatly from ours.** In a short probe with overlapping requests it removed the slowdown and errors seen on default settings, and was slightly faster per request. It isn't adopted, because the demo and the reported results were measured on default settings and it hasn't been tested under the same conditions.
- **Possible addition: Grafana + Prometheus** for live dashboards of scores, alerts and latency. It's the industry monitoring stack, but it needs Docker and a metrics endpoint, so the prototype uses a terminal panel. It pairs with the Kafka/monitoring addition above.
- **Out of scope: feature store.** It's how enterprises centralise feature definitions, but the prototype's single shared code path covers the same need at this scale.

### Limitations
- The data covers only about 2 days of transactions, so we can't simulate realistic feedback delay (the time before fraud labels arrive). The windows have no gap between them for that reason: a gap of a few hours would cost frauds without modelling a delay of days.
- There's no card or customer ID, so card-level metrics (such as card precision top-k, which counts each compromised card once) and history (velocity) features aren't possible.
- There's no transaction ID, so exact duplicates (same values, same second) can't be told apart as retries, double submissions or export errors. Fraud is 10x more common inside these duplicate groups (1.73% against 0.173%), which suggests card-testing behaviour. Using that as a live signal needs state about earlier transactions, which is out of scope for the same reason as velocity features.
- Identical genuine transactions recur at different times, some across window boundaries (805 of 4,383 groups span more than one window), consistent with recurring payments. The model sees these patterns in training, as it would live.
- The threshold is set on the night half of day 2 and tested on the daytime half. Scores run lower by day, so the fixed threshold flags about half the budget and misses daytime fraud. With 48 hours, drift can't be told apart from time-of-day effects. In production, the threshold would be recalibrated regularly on a representative period.
- The features are anonymised with PCA, which limits feature engineering and how well we can explain decisions.
- The API runs as a single local process with no authentication. The replay measures latency at a realistic pace without overlapping requests; capacity under concurrent load isn't tested (out of scope). On default settings, overlapping requests make each model call compete for every core (OpenMP threads), and the API falls behind. See the suggestion on inference threads under Cut / Added.

## Problem 2: Complaint Triage

*Not started.*
