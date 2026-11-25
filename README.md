# PayGuard

Prototype solutions for a finance client's two problems: **(1) real-time fraud detection** on card transactions, and **(2) complaint triage**.

## Setup

Tested from a clean environment on Linux (WSL2 on Windows 11). You need `curl` and an internet connection.

**On Windows, use WSL2.** In an administrator PowerShell, run `wsl --install` and restart; then open Ubuntu and follow the steps below unchanged. Clone into the Linux home folder (e.g. `~/PayGuard`), not under `/mnt/c` or `/mnt/d`, which are much slower from WSL. The API is reachable from a Windows browser at the same `127.0.0.1` addresses. Native Windows isn't supported: on machines with Smart App Control on, Windows blocks the unsigned compiled files that uv's Python and the scientific packages (numpy, pandas, scikit-learn) ship.

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
   uv run scripts/fraud/get_data.py                  # asks: kaggle / manual
   uv run scripts/fraud/get_data.py --source kaggle  # Kaggle CLI via uvx; no install or account needed
   ```
   For a manual download, get it from https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud, place `creditcard.csv` at `data/raw/creditcard.csv` and re-run the script to verify it.
   Both routes are checked against the same SHA-256: `76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89`.
4. **(Optional) Regenerate the data report.** The analysis tools sit in a separate `analysis` dependency group, so the serving runtime doesn't install them:
   ```bash
   uv run --group analysis scripts/fraud/data_understanding.py   # writes reports/fraud/data_understanding.md + figures
   ```
5. **Train the shortlisted fraud models.** This fits each candidate on the training window and logs it to a local MLflow store (`mlflow.db`, `mlruns/`, both gitignored):
   ```bash
   uv run scripts/fraud/train.py
   uv run mlflow ui --backend-store-uri sqlite:///mlflow.db   # from the repo root; browse at http://127.0.0.1:5000
   ```
6. **Write the decision report.** This scores the latest run of each model on the validation and test windows, writes `reports/fraud/decision_report.md` and logs the headline metrics to each model's MLflow run (about 3 minutes, mostly the bootstrap):
   ```bash
   uv run scripts/fraud/evaluate.py
   ```
7. **Serve the selected model.** The API loads the selected model's latest run and the threshold that step 6 logged on that same run (it refuses to start if that run hasn't been evaluated):
   ```bash
   uv run uvicorn payguard.fraud.api:app   # from the repo root; interactive docs at http://127.0.0.1:8000/docs
   ```
8. **Replay the client's traffic through the API** (in a second terminal, with the API running). The default replays the demo slice, 42:40–43:20 at 4× (~10 minutes), with a live panel, then checks parity against the offline model and writes `reports/fraud/replay_report.md`. Run nothing heavy on the machine meanwhile: the replay, API and model share it, so other work shows up as latency.
   ```bash
   uv run scripts/fraud/replay.py
   uv run scripts/fraud/replay.py --start 39:31 --length 20   # another slice, same pace (keep the speed low enough that requests don't overlap)
   ```
   Score one transaction (the 28 components and Amount; other fields are ignored):
   ```bash
   curl -s http://127.0.0.1:8000/v1/score -H 'content-type: application/json' \
     -d "{$(for i in $(seq 1 28); do printf '"V%d": 0, ' $i; done)\"Amount\": 25}"
   # {"fraud_score":…,"alert":false,"threshold":0.357…,"model_run_id":"…"}
   ```
9. **Complaint data (triage).** The 500-complaint slice ships in the repo at `data/triage/complaints_sample.csv`, so there's nothing to download. Optionally verify it, or rebuild it from the archived CFPB file (reads the first 10 MB, about 20 seconds) to confirm it's reproducible:
   ```bash
   uv run scripts/triage/get_complaints.py            # checks the committed file's SHA-256, no network
   uv run scripts/triage/get_complaints.py --rebuild  # re-draws it from the archive; must give the same bytes
   ```
10. **Triage the complaints with the local model.** The pipeline runs `granite4.2:3b` through [Ollama](https://ollama.com), a system install rather than a Python package (needs `sudo`; about 2 GB of model download). Ubuntu on WSL needs `zstd` for the installer:
   ```bash
   sudo apt-get install -y zstd
   curl -fsSL https://ollama.com/install.sh | sh   # installs and starts the Ollama service; uses an NVIDIA GPU when present
   ollama pull granite4.2:3b
   ```
   Then run the pipeline in a terminal you can watch: a live panel shows each decision as it's made, and for labelled complaints how it compares with the gold labels.
   ```bash
   uv run scripts/triage/run_triage.py --limit 20   # trial: the first 20 gold complaints -> data/triage/trial_granite4.2_3b.csv (git-ignored)
   uv run scripts/triage/run_triage.py              # all 500 -> data/triage/triage_sample.csv (committed)
   uv run scripts/triage/evaluate_triage.py         # reads the committed outputs, no model needed -> reports/triage/evaluation_report.md
   ```
   Latency depends on the GPU: about 4 s per complaint on an RTX 4070 Laptop GPU (8 GB).
11. **Run the tests.** The fraud data tests are skipped if the dataset hasn't been downloaded:
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
- **Data understanding** ([report](reports/fraud/data_understanding.md)): about 211 frauds on day 2, so small model differences are noise. Several features drift between the two days, which supports a time split. Seven features separate fraud strongly on their own, so a simple baseline is credible. There are 1,081 exact duplicates, all within the same second. Analysis is look-only; no data is changed.
- **Shortlist: logistic regression (interpretable baseline) and gradient-boosted trees** (scikit-learn's `HistGradientBoostingClassifier`), both with default settings except two stability settings on the boosted trees. Early stopping is off, because it holds out a random sample of training rows and would shuffle time. `l2_regularization=1.0` (XGBoost's default for the same term), because with sklearn's default of 0 its training diverged on this data: scores stuck at exactly 1.0, so it couldn't rank its top alerts. Twelve model families were considered. Random forest usually trails boosted trees; k-NN, kernel SVM and neural networks fit poorly here (latency, training cost, tuning); sequence and graph models need card history the data doesn't have.
- **Class imbalance:** no resampling. Logistic regression weights the rare fraud class up (`class_weight="balanced"`); the trees use defaults.
- **Features: the 28 anonymised components and Amount (log-transformed).** `Time` counts seconds since the file started, so it can't be computed live, and it's dropped.
- **Preprocessing lives inside each model's saved pipeline**, so the API loads one artifact that carries its own transforms. The pipeline picks its input fields by name, so a raw transaction scores the same in any field order or with extra fields; tests check this, and that a saved and reloaded model gives identical scores.
- **Models are logged with MLflow** in its default safe format (skops), with the pinned dependency versions and the model's contract recorded beside it: the 29 model fields in (no `Time`, which can't be computed live), fraud probabilities out. Code lives in `src/payguard/fraud/` (`data.py` for the windows, `models.py` for the pipelines), shared by training, tests and the API.
- **Scoring API (FastAPI):** `POST /v1/score` takes one transaction and returns the fraud score, the alert decision, the threshold and the MLflow run that scored it; `GET /v1/health` shows the model being served. It serves the selected model (`SELECTED` in `models.py`) from its latest MLflow run, with the threshold `scripts/fraud/evaluate.py` logs on that same run, so a model is never paired with another model's cut. Requests are validated against the 29 model fields (built from the same field list as the model; NaN, Infinity and negative amounts are refused with a 422 naming the field), and paths are versioned so the contract can change without breaking callers.
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
Full numbers: [decision report](reports/fraud/decision_report.md) (regenerate with `uv run scripts/fraud/evaluate.py`). Test window 36–48h, 115 frauds, budget 0.2% = 185 alerts.

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

**Replay through the API** ([replay report](reports/fraud/replay_report.md), regenerate with `uv run scripts/fraud/replay.py`): the demo slice, 42:40–43:20 at 4× real time, 5,351 transactions and 17 frauds.

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

Goal: a batch pipeline that turns a raw complaint narrative into a structured triage record (category, urgency, summary, requires_human, confidence_note), with an evaluation of how good the triage is. **Result in one line:** on 500 complaints, a free local 3B model routed 45.6% with no human, with no failed calls, while sending 23 of the 27 test complaints that need a human to one, or 25 of 27 with a legal-words rule added after seeing those misses (see Results).

### Data

- **Source:** the CFPB Consumer Complaint Database, as the brief asks. CFPB removed consumer narratives from the live database in September 2026 (Release 24). The live API ignores the narrative filter, and today's bulk file has no narrative column. So the slice comes from **CFPB's own bulk file as the Internet Archive captured it on 2026-08-15**, before the removal: `https://web.archive.org/web/20260815141332id_/https://files.consumerfinance.gov/ccdb/complaints.csv.zip` (1,415,011,387 bytes). The `id_` link serves the archived bytes unchanged. The change of source is being raised with the client.
- **Slice:** 500 complaints with narratives, drawn with seed 42 (NumPy `RandomState`) from the whole rows in the file's first 10,000,000 bytes (326,286 rows). All 16 columns are kept as CFPB published them. Narratives carry CFPB's own redaction (`XXXX`, `XX/XX/2023`).
- **Reproducibility:** the slice is committed (CFPB data is public domain, CC0; 822 KB). `scripts/triage/get_complaints.py --rebuild` re-downloads the same 10 MB and checks both hashes:
  - first 10 MB of the archive: `334b6c638fe4f2395e6c5d2b95d33201a5eff7ab492a27028f035fe3c4a014d5`
  - slice: `42b27d0b1f7e7a593840dd3192c74390c3fb341d79dd88fd911c9d8224a74dcc`
- **Why only the first 10 MB:** a full download would cost every rebuild 1.4 GB to keep 500 rows. The risk was a sample skewed by the order of CFPB's file. The data review ruled that out: the chunk's product mix matches CFPB's whole database for the same months.
- **Data review** (ad hoc; no report script, by decision):
  - **Representative of published narratives.** CFPB's database is ~90% credit reporting, but only 0.1% of credit-reporting complaints have a published narrative (25.8% for other products). So the slice is mostly debt collection (32%), checking (19%) and credit card (16%). Narratives are published only with the consumer's consent, so this shows which narratives were published, not which complaints had text.
  - **Short texts:** median ~270 tokens, longest ~2,500, so no truncation or chunking is needed.
  - **Noisy CFPB labels:** one identical template complaint appears 12 times against 12 companies with different product labels. CFPB's product field follows the company more than the text, so it can only serve as a weak reference label. Duplicates are kept: they're real data and give a free consistency check.
  - **Many sensitive cases:** keyword counts suggest about 22% mention fraud or unauthorised activity and 12% legal action. 19% are tagged Servicemember or Older American.
  - **No prompt injections** in the real data. No synthetic attacks were built, so injection resistance isn't measured (see Limitations).
  - **Redaction:** CFPB removed personal details before publishing (`XXXX`, `XX/XX/2026`; amounts as `{$…}`). That hides names, dates and deadlines the triage might use. The client's own complaints would arrive unredacted, which raises a data-handling question for production (personal data sent to an LLM provider).

### Triage design

The client's question: can an LLM take work off a fully manual support team, routing each complaint to the right team with a summary, **without hallucinating or misrouting sensitive cases**? The design keeps the LLM to judgements a schema can constrain, and puts the safety rule in code.

- **One vocabulary, one set of definitions** (`src/payguard/triage/taxonomy.py`). The labelling guide is generated from them and the LLM prompt uses the same text, so human labels and model output are judged against identical wording.
- **Seven routing categories,** applied in order: fraud or unauthorised activity → `fraud_scams` on any product; otherwise credit-report content → `credit_reporting` from any company; otherwise by product: `debt_collection`, `banking_payments`, `credit_cards`, `lending`. `other` is used only when the text is unclear or fits none. The output schema allows only these values, so the model can't invent a category.
- **Urgency is harm-led** (low, medium, high): the kind of harm and whether it's ongoing, imminent or past. Time cues in the text can raise urgency. Missing or redacted time never lowers it: 69% of the slice has no usable time cue after CFPB's redaction, and only one explicit date survives. On the client's unredacted complaints, time would carry more weight.
- **Five flags** the LLM sets from the text, each with a boundary:
  - `fraud_allegation`: a dispute over a debt's amount isn't fraud
  - `legal_threat`: citing a law isn't a threat
  - `vulnerable_customer`: from the text only
  - `safety_risk`: a rude collector isn't a safety risk
  - `discrimination`: needs a protected characteristic

  There's no tone flag and no regulator flag, since every complaint here was filed with a regulator.
- **`requires_human` is a policy in code** (`src/payguard/triage/policy.py`), not a prompt instruction, so text in a complaint can't switch it off. It collects **every** reason that applies, and no check can hide another:
  - any CFPB tag (Older American, Servicemember)
  - an unusable narrative (under 5 words, an assumption; these skip the LLM)
  - a failed LLM call
  - category `other`
  - high urgency
  - any flag
  - **legal words** in the text (attorney, lawyer, lawsuit, sue, court, small claims, litigation, legal action), whatever the model says

  The reasons go into the output so reviewers see why. The policy never changes urgency, so a tagged complaint about a minor issue is reviewed at low priority but never auto-closed. The tag rule costs 42 reviews in the 500 (8.4%) for tagged complaints with nothing else flagged, accepted deliberately for protected groups.
- **Legal-words backstop, added after the test results were seen.** On the 80 labelled complaints the model caught `legal_threat` 0 of 5 times, including court papers and an explicit lawsuit threat, and the brief says legal threats must never be auto-closed. A stronger prompt was unlikely to fix a 3B model that missed all five, so a deterministic keyword rule sends legal language to a human. It closed both legal misses and sends 28 of the 500 to a human for legal words alone. The model's own legal flag stays a separate reason, so the report still shows what the model caught by itself.
- **Model: Granite 4.2 3B through Ollama** (`granite4.2:3b`, digest `40577dc168a3`, recorded in every output row). A local model is free, has no rate limits, keeps complaints on the machine, and constrains output to the schema; a small one widens who can run the pipeline (8 GB of memory is enough). The pipeline reaches the model through one small boundary (`src/payguard/triage/llm.py`), so a hosted model is a one-module swap.
  - **Chosen over Qwen 3.5 4B** on the first 20 dev complaints. Granite got every category right, sent exactly the 7 complaints the labels need to a human and raised no false flags, but half its summaries ran past 2 sentences. Qwen wrote the best summaries but raised 10 false flags (7 times treating a cited law as a legal threat) and sent 15 of 20 to a human, which works against taking load off the team.
  - Gemma 4 e4B was dropped before the trial: it runs like a 4B model but downloads and loads like an ~8B one (6.6 GB).
- **Summaries are kept under 50 words.** Granite padded them with the history of the consumer's contacts with the company; a tighter instruction (decided on the dev results, before any test results) cut the dev summaries from 51 to 33 words on average without changing the decisions.
- **The model is treated as unreliable.** Its output is constrained to the schema while it's generated and validated again in code; a truncated or invalid answer gets one re-ask, connection errors get retries with backoff, and anything still failing goes to a human. Complaint text is fenced in tags it can't close, and the prompt tells the model it's data, not instructions.
- **Runner and live panel** (`scripts/triage/run_triage.py`): one path per complaint (narratives under 5 words skip the model; the review policy always runs), a live rich panel, and a CSV with fixed columns: the judgement, every review reason, attempts, errors, tokens, latency and the model digest. A run that loses the Ollama server writes nothing, so a file is never partial. `--limit N` runs the first N gold complaints as a git-ignored trial.
- **Evaluation report** (`scripts/triage/evaluate_triage.py`): scores against the gold labels (test is the headline; dev was available while building), every complaint the labels send to a human that the pipeline would route automatically, agreement with CFPB's fields, consistency on identical complaints, summary checks (more than 2 sentences, numbers absent from the complaint) plus a 10-summary human spot-check, and cost and latency at the client's 50,000 complaints a month, with Claude Haiku 5.5 as a hosted comparison.
- **Weak CFPB reference:** CFPB's product and issue fields map to the same categories in the same rule order, to check broad agreement on all 500. It's weakest where the stakes are highest: CFPB's issue field marks 12 complaints as fraud, while about 22% of narratives use fraud language.
- **Gold set:** 80 complaints labelled by Gemini Neon at its high effort setting from the labelling guide (narrative and tags only; no CFPB product or issue), 30 dev / 50 held out, one copy per narrative so template complaints can't sit on both sides. Created with `uv run scripts/triage/make_labelling_file.py`, validated with `--check`. Gold `requires_human` comes from the same policy applied to these labels. See Limitations for why a model labelled them and what that means for the scores.
- **Future modification:** if the review queue still outruns the team, add priority tiers or narrow the tag rule. Today every complaint is handled manually, so reviewer capacity isn't a constraint for the prototype.
- **Possible addition: a larger-model comparison.** Rerun the same prompt and schema with an 8–9B model (e.g. Qwen 3.5 9B, ~6.6 GB, or Granite 4.2 8B, ~5.3 GB) on the 30 dev rows. Only the model size changes, so it isolates what the small model gives up. The Gemini-labelled gold set doesn't answer that, because it differs from the pipeline in model, provider and setup at once. A hosted comparison on the owner's free Gemini API key was tried and dropped: every request with our prompt got "503 high demand" on three Flash models, though a tiny test request went through.
- **Possible addition: an enriched real sample for rare flags.** The gold set has no test cases for `safety_risk` or `discrimination`, so neither is measured. The standard way to measure rare classes on real text is to search the wider data for likely cases (e.g. "suicide", "domestic", "abuse", "disabled", race terms), label those real complaints, and score `safety_risk` and `discrimination` on them separately. The 10 MB chunk already downloaded holds about 326,000 complaints to search. Not built: it needs another labelling pass the time budget doesn't cover.

### Results

From `reports/triage/evaluation_report.md`: `granite4.2:3b` (digest `40577dc168a3`) on all 500 complaints, on an RTX 4070 Laptop GPU.

| | |
|---|---|
| **Routed with no human** | **228 of 500 (45.6%)** |
| Sent to a human | 272 (54.4%) |
| Failed calls, re-asks, narratives too short | 0, 0, 0 |
| **Test set (50): complaints needing a human that got one** | **23 of 27 (85.2%)** from the model and its flags; **25 of 27 (92.6%)** with the legal-words rule, which was added after seeing these misses, so the 92.6% is optimistic. Precision 89.3% |
| Test set: category / urgency accuracy | 76% / 74% |
| Sensitive cases routed without a human (80 labelled) | 2: a bank withholding $3,300 rated medium instead of high; a vague complaint the labels mark `other` (the label notes call it borderline) |
| Summaries | 10 of 10 judged faithful in the owner's spot-check; 117 of 500 (23%) still run past 2 sentences, though under 50 words; 1 of 500 flagged for a number not in the complaint, a false alarm ("thirty days" written as 30) |
| Latency per complaint | 2.96 s mean, 3.42 s p95 |
| At 50,000 complaints a month | 41 compute-hours for one worker on this machine; the same tokens on Claude Haiku 5.5 would cost about $10 a month |

- **The workload cut is in triage, not handling.** Today every complaint is read and routed by hand; with the pipeline 45.6% skip that step, and the 54.4% that reach a human arrive routed, summarised and with the reasons they were flagged. Of those, 42 (8.4% of all) go only because of a CFPB tag, 5 only for the vulnerable-customer flag, and 28 only for legal words.
- **Where it goes wrong:**
  - The model caught `legal_threat` on none of the 5 labelled legal threats (it raised the flag 13 times across the 500); the legal-words rule covers it.
  - It leans toward fraud: `fraud_allegation` is the most common review reason (131), with 5 false alarms in test, and 4 test banking complaints routed to `fraud_scams`. That direction is safe for review but sends some complaints to the wrong team, and it is why agreement with CFPB's own fields is only 45.8% (the gold labels reach 61%).
  - It never rates urgency "low": of the 7 low-urgency test complaints, 6 were rated medium and 1 high.
- **Is the model the limit?** It's the largest single one: the flag and urgency gaps above are capability gaps of a 3B model following a long rubric, and a larger or hosted model would very likely close many of them (the larger-model comparison is a possible addition). Label noise, CFPB's redaction and taxonomy edge cases cap the scores too. The safety rules are in code and don't depend on the model.
- **Owner's spot-check notes.** Some complaints need more than 2 sentences to keep the important details (23150610), so the 2-sentence check is a guide, not a rule. One faithful summary lost the "why" (23051429: the lawsuit had proved the consumer right, which is why they wanted the charges removed).
- **Recommendation for the client:** enough to justify a **shadow-mode pilot**, not a switchover. Run the pipeline on live complaints while staff keep handling everything as today, measure how often they would override its routing, then start automating the lowest-risk categories, keeping every `requires_human` reason in force.
- **What we'd measure at scale:** staff overrides of the routing (the label stream a production system learns from), `requires_human` misses found in sampled audits of auto-routed complaints, the automation rate and review-reason mix over time (drift), failure and re-ask rates, latency, and summary faithfulness on a regular sample.

### Limitations

- **Reference labels come from a stronger model, not a domain expert.** The ~3h time estimate doesn't allow reading and labelling 80 complaints by hand, so Gemini Neon (high effort setting) labelled them from the same guide the pipeline uses. What this means:
  - **What the scores measure:** how closely the ~4B pipeline model agrees with a stronger model given the same definitions. That stands in for the gap between a small model and a human reviewer, but isn't that gap itself.
  - **Noise in the reference is expected either way:** human labellers disagree on this kind of triage too, especially non-experts, so hand labels from the project team wouldn't have been a much firmer reference.
  - **In production** the reference would be the client support team's own past routing and escalation decisions, not hand labels made for the evaluation.
- **Known inconsistencies in the labels, left uncorrected.** A review found places where the labels follow rules the guide doesn't state: fraud urgency rising with the amount lost (past, denied fraud claims are high at $5,900 and $23k but medium at $170 and $290), the credit-report-first rule applied unevenly to collector complaints, an uneven line for "severe financial hardship", one locked account rated low while other blocked funds are high, and one high urgency without a scheduled foreclosure. The pipeline model only sees the guide, so some measured errors are noise in the reference rather than model mistakes.
- **Few sensitive cases to score flags on.** The 50 test rows hold no `safety_risk` or `discrimination` cases and only 4–5 each for the other flags, so one miss moves recall by 20–25 points. Flag results should be read as counts (e.g. "4 of 5 caught"); the two empty flags aren't measured (enriched real sampling is listed as a possible addition).
- **Prompt injection isn't tested.** The real slice contains none, and no synthetic attacks were built (owner's decision, for the time budget). The defences are structural: complaint text is fenced and can't close its tag, the output is schema-constrained, and `requires_human` is decided in code, so text can't switch it off. They haven't been tested against attacks.
- **The same complaint can get a different answer,** despite temperature 0 and a fixed seed: one complaint was rated high in one run and medium in the next, and within the 500-complaint run one template that appears 12 times got the legal flag on some copies and not others. 6 of the 7 repeated narratives were judged identically.
- **The legal-words list is minimal.** It matches all 5 labelled legal threats but misses words such as "summons", "suit", "counsel" and "judgment", and it also matches "attorney general" (a regulator, 6 of its 63 matches), which errs toward review. Widening it would change the stored review reasons, so it needs a rerun or re-scoring of the outputs; left for a production version.
- **The client's mix differs from the slice.** About 90% of CFPB's complaints are credit reporting, but few of those have a published narrative, so the slice is 5% credit reporting. On the client's own intake the automation rate could differ from 45.6%.
- **Redacted public data.** CFPB's redaction hides names, dates and deadlines; the client's complaints would arrive unredacted, which would help urgency and raises a data-handling question if a hosted model were used.
