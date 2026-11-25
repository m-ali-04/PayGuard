# PayGuard: Project Report

*Outline draft. Each section says what it will cover; sections are written and reviewed one at a time.*

## 1. Summary
*Both answers on one screen. Fraud: ready for a shadow-mode rollout (82 of 115 test frauds caught at a threshold fixed in advance; p99 25.6 ms end to end; served scores identical to offline). Triage: 45.6% of complaints routed with no human, 20 of 22 auto-routed test complaints to the right team; a shadow-mode pilot, not a switchover. The production plan in one line, linking to the memo.*

## 2. Reading guide
*Written last, once section numbers are final. A table mapping each criterion (judgment, evaluation rigour, code quality, communication, results) to the sections that show it, plus where the generated reports, the decision log (CONTEXT.md) and AI usage (AI_USAGE.md) live.*

## 3. Fraud detection

### 3.1 Framing and scope

**The question.** You asked for a model that flags fraudulent card transactions and works on live traffic. We framed it as three tests: can a model score each transaction while its authorisation is still pending, catch a useful share of fraud, and keep false alerts to a number your team can review?

**Scoring inside the authorisation.** A card authorisation takes about 100–300 ms end to end, and fraud scoring usually gets 10–50 ms of that (practitioner and vendor figures; there's no formal standard). A batch job can't decide before the payment completes, so the prototype scores one transaction at a time, synchronously, and returns the decision with the score. Grouping requests that arrive within a few milliseconds (micro-batching) would raise throughput without changing that contract; it's a serving option for later.

**Latency limit: p99 within 50 ms per transaction,** the lenient end of the published range. Latency is a requirement to meet with the right serving tools, not a reason to rule out a model.

**What a good result means.** Every alert costs analyst time or customer friction, so the number of alerts your team can review sets how the model is used. We judge models by the frauds they catch within an alert budget, a fixed share of transactions (section 3.3). Neither your review capacity nor the cost of a false alert against a missed fraud was available, so the budget is our assumption (section 6).

**Showing real time on a static file.** Your data arrived as a file, so a replay script sends the transactions to a local scoring API in time order, spaced as they were recorded (4 times faster for the demo), and measures each request's latency. It then checks that the served scores match the offline model's exactly, so serving adds nothing the evaluation didn't see. A streaming pipeline (Kafka) is the production route and the memo covers it; for the prototype, a request/response API matches the authorisation path.

**Complexity has to earn its place.** Every model is set beside a simpler baseline, and a gain is weighed against what it costs in latency, size and explainability (section 3.5).

**Out of scope:**
- extensive hyperparameter tuning and ensembling, which raise scores without making the system more useful in practice; both models run on default settings apart from class weighting and two stability settings, each with its reason (section 3.4);
- load testing: the replay shows the model on your traffic at a realistic pace, not the capacity of a production deployment, which depends on traffic volumes we don't know;
- anything the data can't support (velocity features, card-level metrics, label delay), recorded in section 3.7 instead.

### 3.2 Data findings

Your file holds 284,807 card transactions over 48 hours, 492 of them fraud (0.173%). Each has 28 anonymised components (V1–V28, from a PCA transformation applied before we received the data), the amount, the fraud label, and `Time`, the seconds since the file's first transaction. A script writes the full analysis, with figures, to the [data report](reports/fraud/data_understanding.md). The analysis only looks: no transaction was changed or removed.

| Finding | What it allows or rules out |
|---|---|
| **Two days, one daily cycle.** Day 1 has 281 frauds, day 2 has 211. | Too short to model label delay (weeks in practice) or to tell drift apart from time of day. Day 2's frauds are split between setting the threshold (96) and the test (115), so each test fraud is worth almost 1% of recall, and differences of a few frauds are noise (section 3.3). |
| **No card, customer or transaction ID.** | No velocity features (a card's recent activity), no card-level metrics, and no way to tell duplicates apart. Each transaction is scored on its own. |
| **Anonymised components.** | Little room for feature engineering, and explanations would point to components with no business meaning. The upstream transformation has to stay exactly the same at serving time. |
| **The days differ.** 7 components shift between day 1 and day 2 among genuine transactions alone (KS above 0.2, largest V3 at 0.52). | A time-ordered split, not a random one: a model trained on day 1 meets a slightly different population on day 2, as it would live. A random split would mix the days and overstate live performance. |
| **Strong single signals.** 7 components each separate fraud well on their own (KS above 0.7, led by V14, V10 and V12). | A simple model is a credible baseline, and a more complex one has to show a gain beyond it. |
| **Fraud clusters in quiet hours:** 0.561% of transactions in the 14 quietest hours, against 0.131% elsewhere (4.3 times). | Time of day carries signal, but `Time` counts from an unknown start and can't be computed live, so it's dropped; an hour-of-day feature would rest on one night and an assumed clock (section 3.8). A threshold set at night also behaves differently by day (section 3.5). |
| **Duplicates.** 1,081 extra copies of identical rows, all within the same second, none with conflicting labels. Fraud is 10 times more common inside them (1.73% against 0.173%): 13 distinct frauds appear 32 times. A further 8,063 rows repeat an earlier transaction's values at a different second, all genuine. | Copies share a second, so they can't straddle a time split. We kept them: they're part of your real stream, and deduplication belongs upstream, at ingestion, by transaction ID. The repeats look like recurring payments, which recur live too. |
| **Amount.** 37% of frauds are for 1.00 or less, against 11% of genuine transactions, yet fraud's largest amounts run higher. | Amount alone separates weakly and needs a log transform for scale-sensitive models. It's the only field that puts a value on a missed fraud, in a currency the data doesn't name. |

The KS cut-offs (0.2 and 0.7) are reporting thresholds we chose, not industry standards.

### 3.3 Evaluation design

Every choice below was fixed before any model was compared, so the results couldn't steer the method.

| Choice | Why | Considered instead |
|---|---|---|
| **A time-ordered split:** train, then set the threshold, then test, in time order. | Live, a model always scores transactions newer than its training data. 7 components drift between the two days, and a time split prices that in. | Random k-fold, which trains on future transactions, hides the drift, and puts identical same-second copies on both sides of a fold, so it would overstate live performance. Forward-chaining (time-aware k-fold), which can't separate drift from time of day in one daily cycle; we recommend it once you share several weeks of data. |
| **Windows:** train on day 1 (0–24 h, 281 frauds), set the threshold on the night half of day 2 (24–36 h, 96 frauds), test on the daytime half (36–48 h, 92,576 transactions, 115 frauds). | The largest test set of the splits compared, and a simple story: train on yesterday, set the threshold overnight, test on today. | Other time-ordered proportions: 50/25/25 (94 test frauds) and 60/20/20 (75). |
| **No gap between windows.** | A gap of a few hours can't model label delays of weeks, and it would cost about 10 frauds an hour. | A gap; the missing label delay is recorded as a limitation instead (section 3.7). |
| **Train on the training window only.** | The threshold has to come from a model that never saw the validation data. | Refitting on training plus validation before the test. |
| **Alert budget: 0.2% of transactions** (185 alerts in the test window). | Just above the 0.173% fraud rate, so the model rather than the budget limits recall. We started at 0.1%, a published industry figure, but below the fraud rate it capped recall at 58%, so we raised it before any model was scored. After the results we also looked at 0.3% and kept 0.2%, so the budget didn't move with the results. | 0.1%, 0.3%, 0.5% and 1%. |
| **Headline metric: average precision** (the area under the precision-recall curve, computed step-wise). | It measures how well a model ranks the rare frauds above genuine transactions, without needing a threshold. | Accuracy, which is meaningless here: flagging nothing scores 99.8%. ROC-AUC, reported for reference only, because on data this imbalanced it can rank models misleadingly (the Fraud Detection Handbook shows a case where it and average precision disagree). |
| **Operating metrics: precision, recall and frauds caught at the budget.** | What your team would see: how many of the alerts it reviews are fraud, and how many frauds get through. At a fixed budget, precision and recall rank models identically; both are reported. | Card precision top-k, the industry's card-level measure, which needs a card ID. |
| **Live operating point: a fixed score threshold,** set on validation to flag 0.2% there, then applied unchanged to the test window. | Transactions arrive one at a time, so ranking a day's transactions and flagging the top k isn't possible live. Applying the validation threshold to the test window shows what live alerting would do. | A daily top-k ranking, which is used offline only, to compare models at the budget. |
| **Selection rule:** the highest average precision, provided the model catches no fewer frauds at the budget than the alternatives. | Fixing the rule first stops it bending toward a preferred model. If the two measures disagree, that's reported as a finding, not settled by changing the rule. | |
| **Gains are judged, not gated.** The decision report sets each candidate beside the simpler model: average precision and frauds caught, each with a paired bootstrap 95% range for the difference (2,000 resamples, fixed seed); the threshold applied to the test window; p99 latency, pass or fail at 50 ms; and complexity and explainability. | A fixed minimum gain can't weigh a gain against its running costs, which only show once models exist. The ranges say how certain a gain is; the decision weighs it against those costs. | An automatic minimum gain. |

Counts are reported per test window, not scaled to a day: the window is the daytime half, and doubling it would assume the night behaves the same, though fraud runs higher at night. The report also shows validation results beside test as a rough view of how results hold over time; the windows differ in fraud mix (night against day), so it isn't a clean measure of drift. What could still undermine the results is in section 3.7.

### 3.4 What we built

**Shortlist.** We compared 12 model families against what this data and setting allow: anonymised numeric components with no categories or IDs, 281 training frauds, one transaction scored at a time. Two cover both ends. Logistic regression is an interpretable baseline; gradient-boosted trees (scikit-learn's `HistGradientBoostingClassifier`) are usually the strongest on tabular data like this. Random forest usually trails boosted trees and scores single rows more slowly. k-NN (latency grows with the data), kernel SVMs (training cost) and neural networks (sensitive to tuning) fit poorly here. Sequence and graph models need card history the data doesn't have.

**Default settings, apart from a fixed random seed and three exceptions, each for a stated reason:**
- **Logistic regression weights the rare fraud class up** (`class_weight="balanced"`). That handles the imbalance without changing the data; we didn't resample (section 3.8).
- **The boosted trees' early stopping is off.** By default it holds out a random 10% of training rows, which would shuffle time inside the training window.
- **The boosted trees use `l2_regularization=1.0`, to fix a diagnosed failure, not as tuning.** The first decision report showed the trees at an average precision of 0.160 against logistic regression's 0.677. We checked before treating that as a result. The trees' scores had saturated at exactly 1.0 (247 test transactions tied at the top, against a budget of 185, so their top alerts were arbitrary), and the training loss rose after the first tree. With scikit-learn's default of 0, leaves holding a few rare-class rows divide by a near-zero sum, so their values explode (log-odds past 300,000). 1.0 is XGBoost's default for the same term, and with it the training loss falls with every tree. A regression test trains on your training window and fails with the old setting; synthetic data doesn't reproduce the problem. We weighed two alternatives: lowering the learning rate or restricting leaf size works, but has no principled value and slides into tuning; switching to XGBoost or LightGBM adds a dependency for a one-argument fix.

**Features: the 28 components and the amount, log-transformed.** `Time` is dropped because it counts from the file's start and can't be computed live. The log only matters to logistic regression; trees ignore it, but both models share one feature definition.

**One path from transaction to score.** Preprocessing lives inside each model's saved pipeline, so serving loads one artifact that carries its own transforms, and training and serving can't drift apart. The pipeline picks its input fields by name, so a transaction scores the same in any field order or with extra fields. Tests check this, and that a saved and reloaded model scores identically. The code in [`src/payguard/fraud/`](src/payguard/fraud/) is shared by training, the decision report, the tests and the API: [`data.py`](src/payguard/fraud/data.py) defines the windows, [`models.py`](src/payguard/fraud/models.py) the pipelines, and [`evaluation.py`](src/payguard/fraud/evaluation.py) the budget, threshold and bootstrap.

**Model tracking with MLflow.** Each trained model is logged with its input contract (the 29 model fields, without `Time`), its output (fraud probabilities) and the pinned version of every dependency. The decision report logs the live threshold on the same run, and refuses to pair runs from different training sessions. Models are saved in MLflow's default safe format (skops), which refuses to load unvetted types; the boosted trees' internal type is trusted explicitly, since we only load models we trained.

**Scoring API (FastAPI).** `POST /v1/score` takes one transaction and returns the fraud score, the alert decision, the threshold and the MLflow run that scored it; `GET /v1/health` names the model being served. It serves the selected model's latest run with the threshold logged on that same run, and refuses to start if that run has no threshold, so a model is never paired with another model's cut. Requests are checked against the 29 model fields: a missing field, a wrong type, NaN, infinity or a negative amount is refused with an error naming the field, without echoing the value back. Versioned paths let the contract change without breaking callers. The served model is named in code, so changing it is a reviewed change.

**Replay and parity check.** [`scripts/fraud/replay.py`](scripts/fraud/replay.py) sends a slice of the test window to the API in time order. Each transaction goes out on its own schedule without waiting for earlier answers, as real traffic does. Timestamps are whole seconds, so each second's transactions are spread evenly across it; sending them as one burst would be an artefact of the timestamp resolution. The demo slice is the 40 minutes with the most frauds (42:40–43:20, 5,351 transactions, 17 frauds), replayed at 4 times real time (about 10 minutes) with a live terminal panel. At that pace even the busiest second's transactions arrive about 23 ms apart, above the ~10 ms a request takes, so requests don't overlap: the replay measures latency at a realistic pace, not capacity. Afterwards it loads the same MLflow run offline, compares every served score with the offline score, and writes the [replay report](reports/fraud/replay_report.md). A fraud-dense slice runs above average, so the report shows the whole test window's figures beside it.

### 3.5 Results

Full figures are in the [decision report](reports/fraud/decision_report.md) and the [replay report](reports/fraud/replay_report.md), which the README's commands regenerate. Test window 36–48 h: 92,576 transactions, 115 frauds; the 0.2% budget allows 185 alerts. Figures marked † were computed once, on the same runs, to answer follow-up questions; they aren't in the generated reports.

| | Logistic regression | Gradient-boosted trees |
|---|---|---|
| Average precision | 0.677 | **0.732** |
| Frauds caught at the budget (185 alerts) | 88 | **90** |
| Threshold fixed on validation, applied to test: alerts / caught | 82 / 68 | 96 / **82** |
| …precision / recall at that threshold | 82.9% / 59.1% | 85.4% / **71.3%** |
| ROC-AUC (reference only) | 0.937 | 0.973 |
| p99 latency, model only (limit 50 ms) | 6.7 ms | 14.2 ms |
| Saved model size | 146 KB | 1,057 KB |

**We chose the gradient-boosted trees.** They rank better and, with the threshold fixed in advance as it would be live, catch 14 more frauds (82 against 68). Their threshold is also more stable. Logistic regression's scores bunch near 1.0 (its cut is 0.999981), so moving its cut from 0.999 to 0.9999 shifts 26 alerts and 8 frauds†; the trees' scores are spread out, so their cut is stable and readable. The selection rule's default pointed the same way. The costs are acceptable: the larger file isn't a constraint, and the trees' latency sits well inside the limit.

**How certain the gain is.** The bootstrap ranges for the difference include zero: average precision +0.055 [−0.016, +0.121], frauds caught at the budget +2 [−3, +7]. With 115 test frauds, the two models can't be separated with confidence on those measures, so the choice also rests on how they behave with a fixed threshold.

**Checking more transactions buys little.** Frauds caught out of 115, by share of transactions checked†:

| Share checked | Gradient-boosted trees | Logistic regression |
|---|---|---|
| 0.1% | 80 | 70 |
| 0.2% (our budget) | 90 | 88 |
| 0.3% | 91 | 93 |
| 1% | 94 | 95 |
| 5% | 98 | 101 |

Going from 0.3% to 5% buys 5–8 frauds for about 4,300 more genuine checks†. The last ~20% of frauds look genuine to both models: catching 90% would mean checking 11% of transactions with the trees, or 28% with logistic regression†. Catching them needs new information, such as card history. Above 0.2% the two models swap places, within noise.

**The night-set threshold is too strict by day.** Live, the fixed threshold flags 0.104% of daytime transactions, about half the budget (96 alerts against 185). Scores run lower by day for genuine and fraud transactions alike: the threshold flags 0.040% of genuine transactions at night but 0.015% by day†, and catches 79% of frauds at night against 71% by day. Spending the full budget on the same window would catch 90, so the drift costs about 8 frauds. The trees hold up better than logistic regression here (71% against 59% by day).

**Cost of errors.** We weren't given a cost ratio, and there's no industry standard: published estimates vary widely, and industry write-ups often find that false declines cost issuers more than the fraud itself, through churn and lower spending. A false alert costs analyst time and customer friction, plus the sale if it leads to a decline; a missed fraud costs the transaction value and chargeback fees. At the fixed threshold in the test window†:
- **Value caught: 10,791 of 16,413 (65.7%),** below the 71.3% caught by count, because missed frauds are larger (median 12.31 against 2.95 for caught ones).
- **The 14 false alerts carry 25,704 of genuine spending,** more than the fraud value caught. Declining every alert outright would put more genuine spending at risk than it saves, so until the cost ratio is known, alerts suit review or a step-up check better than a decline.

Amounts are in the data's own currency, which it doesn't name. Without a ratio, we weighed errors only through the alert budget, treating a missed fraud as worse than a checked genuine transaction. A ratio from you (section 6) would let the threshold be set on cost.

**Where we recommend operating:**
- **Set the budget to what your team can review.** Our 0.2% is a placeholder (section 6). Beyond about 0.3%, extra alerts land mostly on genuine customers.
- **Recalibrate the threshold on live traffic covering whole days,** and watch the hourly alert rate against the budget. If the day/night pattern holds over weeks, the cheapest fix is separate thresholds for busy and quiet hours, then a time-of-day feature (section 3.8).
- **Split alerts into two bands once the cost of errors is known:** a top band precise enough for an automatic step-up or decline, and a review band for analysts. In this window, 85% of the fixed threshold's alerts were fraud. The memo phases this in (phase 2).

**Replay through the API** (the demo slice, 42:40–43:20 at 4 times real time):

| | Replay (API) | Offline, same slice | Offline, whole test window |
|---|---|---|---|
| Caught / false alerts / missed | 14 / 1 / 3 | 14 / 1 / 3 | 82 / 14 / 33 |
| Recall | 82.4% | 82.4% | 71.3% |

- **Parity holds on real traffic:** all 5,351 served scores equal the offline scores bit for bit, and no alert decision differs. Serving adds no skew.
- **End-to-end latency is inside the limit:** p50 12.2 ms, p99 25.6 ms against 50 ms; 1 request in 5,351 went over (max 76.7 ms). That's from request sent to answer received, with client and API on one machine (WSL2, 22 logical cores). The HTTP round trip, request validation and building the input row add about 6–12 ms over the model alone.
- **Latency depends on the machine.** A rerun from a clean clone gave identical decisions and exact parity but a p99 of 122 ms; another build was running on the machine at the time, the likely cause, though no rerun confirmed it. On battery power, requests took about 100 ms at the median. The figures above come from a quiet machine on mains power.
- **The slice runs above average** (82% recall against 71%), because it was chosen as the most fraud-dense 40 minutes.

### 3.6 Real-time inference

**Features have to exist when the transaction does.** At authorisation, the scorer sees only the transaction and whatever state has been kept about the card. The prototype's features, the 28 components and the amount, all arrive with the transaction, so the model needs no lookups and scores in about 6 ms at the median (14 ms at p99). `Time` fails that test: it counts from the start of a file, which doesn't exist live. Every feature added later has to pass it too: computable from data available at that moment, the same way in training and in serving.

**Velocity features are the largest expected gain, and they need state.** Per-card aggregates, such as spend and attempts in the last minutes and hours, need a card ID and a running record for each card. In production, a stream processor keeps those records in an online store that the scorer reads within a few milliseconds; the memo uses Flink and Redis. The aggregates must come from one definition shared by training and serving, or the model learns one meaning and is scored on another. A feature store is how enterprises centralise those definitions; at the prototype's scale, one shared code path does the same job.

**One code path, checked against the live service.** Preprocessing lives inside the saved model, so the service can't transform a transaction differently from training, and the replay confirmed it: every served score equalled the offline score. The remaining skew risk sits upstream. The 28 components come from a transformation applied before the data reached us; if it changes, scores shift while still looking normal. It needs versioning alongside the model, which is why the memo's monitoring checks input ranges and drift.

**Modelling strategy: a stateless model, a fixed threshold, retraining paced by labels.**
- The model scores each transaction on its own, so its decisions don't depend on arrival order or batching, and the same transaction always gets the same score.
- The threshold is a fixed cut, so it needs recalibrating on live traffic as the score distribution moves; in our data it already moved between night and day (section 3.5).
- Fraud is confirmed when a chargeback arrives, often weeks after the transaction. Until then a fraud looks genuine in the training data, and a fall in recall stays invisible. The label delay sets how often retraining is worth it; analysts' outcomes on alerts give an earlier, partial signal. Two days of data couldn't model this (section 3.7).
- In production, new models would run in shadow beside the live one before promotion, and an anomaly score could flag new fraud patterns that labels don't cover yet (section 3.8).

**Serving: one inference thread per request, scaled out.** By default, each model call spreads across every CPU core. That's fast while requests arrive one at a time, as in the demo, but overlapping calls compete for the same cores. Replaying at 24–30 times real time, the API fell behind: p99 latency reached about 22 seconds and some connections dropped. In a short probe, one inference thread per request removed the slowdown and was slightly faster per call (mean 8.3 ms, against 9.5 ms on default settings). We didn't adopt it, because the reported results were measured on default settings (section 3.8), but it underpins the memo's design: single-threaded scoring pods, added as traffic grows. Several worker processes on one machine also kept up, but the web server's multi-worker mode added about 40 ms to every kept-alive request, another reason to scale with pods rather than workers.

### 3.7 Limitations

| Limitation | What it means for the results | What would remove it |
|---|---|---|
| **Two days of data.** | Label delay isn't modelled, so the windows have no gap between them. Drift can't be told apart from time of day, and the threshold's day/night behaviour rests on a single night. | Several weeks of history and your chargeback delay (section 6); forward-chaining validation. |
| **115 test frauds.** | Each fraud is worth almost 1% of recall, and the two models can't be separated with confidence: both bootstrap ranges include zero. | More history, or a fresh window. |
| **The model was chosen on the test window.** | The selection rule compares two candidates on test average precision, so the chosen model's test figures carry a little selection optimism. With two models on default settings it's small, but it isn't zero. | A further untouched window, or the shadow phase's live figures. |
| **No card, customer or transaction ID.** | No velocity features or card-level metrics. The exact duplicates can't be explained, and the card-testing pattern inside them (fraud 10 times more common) can't be used, since that needs state about earlier transactions. | Identifiers on each transaction (section 6). |
| **Identical genuine transactions recur across windows.** | 805 of 4,383 groups of identical genuine transactions span more than one window, consistent with recurring payments. The model meets these patterns in training, as it would live, but they may make the test slightly easier than entirely new traffic. | Transaction and card IDs, which would show what the repeats are. |
| **The threshold is set at night and tested by day.** | It flags about half the budget by day, about 8 frauds fewer than the full budget would catch (section 3.5). | Recalibration on whole days; separate thresholds for busy and quiet hours. |
| **The alert budget is assumed and there's no cost ratio.** | The operating point is ours, not yours. Results at other budgets are in section 3.5. | Your review capacity and the cost of each kind of error (section 6). |
| **Scores aren't calibrated probabilities.** | A score of 0.36 doesn't mean a 36% chance of fraud. Ranking and a fixed threshold don't need calibration; a threshold set on cost would. | Calibration on a recent window, once costs are known. |
| **Anonymised components.** | Little room for feature engineering, and explanations would point to components with no business meaning. | The raw fields or the transformation's definition (section 6). |
| **Latency measured on one machine, without concurrent load.** | p99 25.6 ms comes from one quiet machine, with client and API side by side. Capacity under overlapping requests is untested on the settings we used, and default threading falls behind once requests overlap (section 3.6). | A load test at your peak volume before launch, as the memo plans. |
| **The API is a single local process with no authentication.** | Fine for a prototype; not deployable as it stands. | Your gateway and platform (section 3.8, and the memo). |

### 3.8 Cut, added and possible additions

**What we built, by line count.** Python code lines, without blank lines, comments or docstrings; each component is counted with its tests.

| Component | Code lines | | Why it's there |
|---|---|---|---|
| Time windows, model pipelines, metrics, fitting, decision report | 297 | **Essential** | The brief's answer: the method, a baseline against a stronger model, the metrics and the threshold. |
| Replay and parity check | 213 | Added | **Production in mind.** It proves served scores equal offline scores on your traffic and measures end-to-end latency. It also found the threading problem behind the memo's single-thread scaling. |
| Data analysis report | 184 | Added | **Evidence the decisions rest on:** the time split, the duplicate policy and the limitations. A script regenerates the same report every time. |
| Scoring API | 151 | Added | **Production in mind.** The request/response service an authorisation path calls, with a versioned, validated contract. |
| Live replay panel | 94 | Added | **Presentation.** An audience can watch decisions as they're made. |
| MLflow tracking | 81 | Added | **Production in mind.** Each model is stored with its contract and threshold, so the API serves exactly the run that was evaluated. |
| Hash-checked download | 57 | Added | **Reproducibility.** Anyone gets the exact bytes we used. |
| Bootstrap ranges and complexity notes | 48 | Added | **More confidence for little code.** They showed the model gain isn't certain. |
| Latency measurement | 20 | Added | **More confidence for little code.** It checks the 50 ms limit. |
| **Total** | **1,145** | 26% essential | |

**Why the replay and API answer "real-time" rather than decorate it.** The brief asks for a short note on real-time inference. We answered with measurements as well as a note: the API is the request/response contract an authorisation path calls, and the replay sends your transactions through it at their recorded pace. That turned three claims into evidence: p99 25.6 ms end to end, served scores identical to offline, and how threading behaves when requests overlap. The last of these only showed up by running it. If the timescale were binding, these would still be the first things to cut (section 7), and the note in section 3.6 would rest on the model-only latency figure.

**What we cut:**

| Cut | Why | Revisit when |
|---|---|---|
| Notebooks | The presentation shows findings, not analysis code: a script writes the data report, and MLflow's interface compares models. | — |
| Data versioning (DVC) | The data is one fixed file; a hash-checked download gives the same guarantee without a storage remote. | The data changes over time. The memo adds DVC for production. |
| A second download source (a third-party mirror) | Kaggle's public download works without an account, and a manual route covers the case where that changes. | Kaggle requires sign-in. |
| Forward-chaining validation | One daily cycle can't separate drift from time of day (section 3.3). | Several weeks of history exist. |
| Resampling (SMOTE, undersampling) | It adds a step that never runs live, and hasn't shown gains on ranking measures such as average precision. Class weighting handles the imbalance. | — |
| A second boosting library (XGBoost, LightGBM) | scikit-learn's boosted trees did the job; the one fix they needed was a single setting. | A gain over scikit-learn's version is shown. |
| SHAP explanations | Not asked for, and they would point to anonymised components with no business meaning. | You or your regulator need explanations (memo, phase 2). |
| A model registry | The served model is named in code, so changing it is a reviewed code change. | Production: MLflow's registry with aliases is the standard promotion flow, as in the memo. |
| Authentication, rate limiting and request logging on the API | They belong to your gateway and platform. | Production (memo). |
| A browser demo page | The API's interactive docs page already lets anyone score a transaction, and the live demo is the replay's panel. | — |
| A feature store | One shared code path covers the same need at this scale. | Features are shared across models or teams. |
| Load testing | Out of scope (section 3.1). | Before launch (memo). |

**Possible additions:**

| Addition | What it would give | Why not now |
|---|---|---|
| Kafka streaming | A local streaming pipeline, or Kafka beside the API to log every decision for monitoring. | A request/response API matches the authorisation path, so the prototype starts there. The memo's production design adds Kafka. |
| Grafana and Prometheus | Live dashboards of scores, alerts and latency: the industry's monitoring stack. | It needs Docker and a metrics endpoint, and the terminal panel serves the demo. The memo includes it. |
| Time-of-day handling | A fix for the night/day threshold drift. Cheapest first: separate thresholds for busy and quiet hours, then a time-of-day feature, then separate models (each training on fewer frauds). | One night of evidence and an unknown clock. Each option would go through the decision report once weeks of data show the pattern. |
| Deduplicating exact copies for fitting and threshold setting only | Each transaction counted once when fitting: 13 distinct frauds appear 32 times. | The gain is unproven, and deduplication normally happens upstream, by transaction ID. |
| Anomaly detection (for example Isolation Forest) | A companion signal for new fraud patterns that labels don't cover yet. | Not needed to answer the brief. The memo places it in the analyst queue in phase 2. |

**Suggestion, not adopted: one inference thread per request** (`OMP_NUM_THREADS=1`), if replay results on other hardware differ greatly from ours. It removed the slowdown under overlapping requests in a short probe, but the reported results were measured on default settings and it hasn't been tested under the same conditions (section 3.6).

## 4. Complaint triage

### 4.1 Framing

**The question.** Your support team handles thousands of free-text complaints a month, all by hand. You asked whether an LLM can triage them: route each complaint to the right team with a summary, without hallucinating or misrouting sensitive cases.

**What the pipeline produces.** A batch script turns each complaint narrative into a structured record:
- `category`: the team to route to, from our own taxonomy of seven (the brief asked for 5–8);
- `urgency`: low, medium or high;
- `summary`: 1–2 sentences;
- `requires_human`: whether a person must handle the complaint, with the reasons, so a reviewer sees why;
- `confidence_note`: when and why the triage might be wrong.

**What success means.** Today every complaint is handled by hand, so each one the pipeline routes on its own takes work off the team, and each one it sends to a person arrives already routed and summarised. Your two worries became the evaluation's priorities:
- **Misrouted sensitive cases come first.** A complaint that needs a person must reach one, so recall on `requires_human` matters more than the automation rate. Fraud allegations and legal threats must never be auto-closed.
- **Hallucination comes next.** The category must come from the taxonomy, and the summary must be faithful to the complaint.

After those: how many complaints skip manual triage, how often those reach the right team, and the cost and latency at your 50,000 complaints a month.

**The model is a component that can fail.** The brief judges the LLM as engineering: structured output enforced, failures retried, malformed answers handled. So the design keeps the model to judgements a schema can constrain, and puts the safety rule (who must see a person) in code (section 4.3).

**Out of scope, as the brief says:** fine-tuning and a chatbot interface. The deliverable is a script that processes a batch.

### 4.2 Data

**The brief's source no longer carries narratives.** The brief names CFPB's Consumer Complaint Database, but CFPB removed consumer narratives from its live database in September 2026 (Release 24). The live API ignores the narrative filter and rejects the narrative field, and today's bulk file has no narrative column. We weighed three routes: an archived copy from before the removal, a sample of your own complaints, and synthetic narratives on real metadata. Synthetic text was ruled out, since evaluating a model on text a model wrote is circular. We used CFPB's own bulk file as the Internet Archive captured it on 2026-08-15, served byte for byte as published, and the change of source is a question for you (section 6).

**The slice.** 500 complaints with narratives, drawn with a fixed seed from the whole rows in the archive's first 10,000,000 bytes: 326,286 complaints, of which 8,827 have a published narrative. Most were filed between February and July 2026. All 16 columns are kept as CFPB published them. Reading only the first 10 MB spares every rebuild a 1.4 GB download; the risk was a sample skewed by the file's order, and the review below ruled that out.

**Reproducible by anyone.** The slice is committed (CFPB data is public domain; 822 KB), so setup needs no download. A rebuild script re-downloads the same 10 MB, checks its hash and the slice's, and must produce identical bytes (README).

**Data review.** A one-off analysis, so its figures aren't regenerated by a script.

| Finding | What it means |
|---|---|
| **The mix reflects published narratives.** CFPB's database is about 90% credit reporting, and so is the 10 MB chunk. But only 0.1% of credit-reporting complaints have a published narrative, against 25.8% for other products, so the slice is mostly debt collection (32%), checking (19%) and credit cards (16%), with 5% credit reporting. | The slice represents the brief's population, complaints with narratives, and isn't an artefact of the file's order. CFPB publishes a narrative only with the consumer's consent, so this shows which narratives were published, not which complaints had text. Your intake mix could differ, and with it the automation rate (section 6). |
| **Short texts:** a median of 177 words (about 270 tokens), the longest about 2,500 tokens. | No truncation or chunking is needed. |
| **Noisy CFPB labels.** One template complaint appears 12 times, against 12 companies with different product labels. | CFPB's product field follows the company more than the text, so it can only serve as a weak reference, not as ground truth (section 4.4). The duplicates are kept: they're real data and a free consistency check. |
| **Many sensitive cases.** Keyword counts suggest about 22% mention fraud or unauthorised activity and 12% legal action; 19% carry an Older American or Servicemember tag. | Sensitive cases are common, not rare, so the review rule will send many complaints to a person. CFPB's own issue field marks only 12 complaints as fraud, so the weak reference is weakest where the stakes are highest. |
| **CFPB's redaction.** 84% of narratives contain `XXXX`-style redaction, dates appear as `XX/XX/XXXX`, and amounts as `{$…}`. 69% have no usable time cue, and only one explicit date survives. | Names, dates and deadlines the triage might use are hidden, so urgency can't lean on time (section 4.3). Your complaints would arrive unredacted, which helps urgency and raises a data-handling question for any hosted model (section 6). |
| **No prompt injections in the real data.** All 5 keyword hits were ordinary uses of "disregard". | Attacks had to be built: 10 real complaints with attack text added (section 4.4). |

### 4.3 Triage design

The design keeps the model to judgements a schema can constrain, and puts the safety rule in code.

**One vocabulary, one set of definitions.** The categories, urgency levels and flags, with their definitions, live in one file ([`taxonomy.py`](src/payguard/triage/taxonomy.py)). The labelling guide is generated from it and the model's prompt uses the same text, so the reference labels and the model's answers are judged against identical wording.

**Seven routing categories, applied in order.** Fraud or unauthorised activity goes to `fraud_scams` on any product. Otherwise, credit-report content goes to `credit_reporting`, from any company. Otherwise the product decides: `debt_collection`, `banking_payments`, `credit_cards` or `lending`. `other` is only for text that's unclear or fits none. Categories are defined by where the complaint's text says it should be handled, not by CFPB's product field, which follows the company (section 4.2). The output schema allows only these values, so the model can't invent a category.

**Urgency is led by harm.** The kind of harm and its state set the level: high for ongoing or imminent loss of money, funds, home or car, or any safety risk; medium for real but not imminent harm; low for service or information problems, or resolved ones. Time cues in the text can raise urgency, but missing or redacted time never lowers it, since 69% of the slice has no usable time cue. When a redacted date could matter, the model says so in its confidence note. On your unredacted complaints, time would carry more weight.

**Five flags, each with a boundary:**
- `fraud_allegation`: a dispute over a debt's amount isn't fraud;
- `legal_threat`: citing a law isn't a threat;
- `vulnerable_customer`: judged from the text only;
- `safety_risk`: a rude collector isn't a safety risk;
- `discrimination`: needs a protected characteristic.

There's no tone flag, and no regulator flag, since every complaint here was filed with a regulator.

**`requires_human` is a policy in code, not a prompt instruction** ([`policy.py`](src/payguard/triage/policy.py)). The model returns flags and urgency; code decides who sees a person, so complaint text can't change the rule itself. The policy collects every reason that applies, so no check can hide another:
- any CFPB tag (Older American, Servicemember);
- an unusable narrative (under 5 words, our assumption; these skip the model);
- a failed model call;
- category `other`;
- high urgency;
- any flag;
- legal words in the text, whatever the model says.

The reasons go into the output so reviewers see why. The policy never changes urgency, so a tagged complaint about a minor issue is reviewed at low priority but never auto-closed. The tag rule alone sends 42 of the 500 complaints (8.4%) to a person with nothing else flagged; we accepted that cost for protected groups. Text can still mislead the model whose flags and urgency the policy reads: only the tag, legal-words and unusable-narrative rules don't depend on the model (section 4.5).

**The legal-words rule was added after we saw the test results.** On the 80 labelled complaints the model caught `legal_threat` 0 times out of 5, missing court papers and an explicit lawsuit threat, and the brief says legal threats must never be auto-closed. A stronger prompt was unlikely to fix a 3B model that missed all five, so a keyword rule (attorney, lawyer, lawsuit, sue, court, small claims, litigation, legal action) sends legal language to a person. It closed both legal misses, and sends 28 of the 500 to a person on legal words alone. The model's own flag stays a separate reason, so the results still show what the model caught by itself, and figures that include the rule are marked as optimistic.

**The model: Granite 4.2 3B, run locally through Ollama** (`granite4.2:3b`, digest `40577dc168a3`, recorded in every output row). We first chose a paid hosted API, then switched to a free route. Against a free hosted tier (tight rate caps that change, complaints sent to the provider, and a key needed by anyone reproducing the run), a local model won: free, no rate limits, complaints never leave the machine, and output constrained to the schema as it's generated. A small model widens who can run the pipeline: 8 GB of memory is enough. The pipeline reaches the model through one small module ([`llm.py`](src/payguard/triage/llm.py)), so a hosted model is a one-module swap.
- **Chosen over Qwen 3.5 4B on the first 20 dev complaints.** Granite got every category right, sent exactly the 7 complaints the labels need to a person and raised no false flags, but half its summaries ran past 2 sentences. Qwen wrote the best summaries but raised 10 false flags (7 times treating a cited law as a legal threat) and sent 15 of 20 to a person, which works against taking load off the team. Granite's weakness was cosmetic and caught by the summary check; Qwen's hit the goal. Twenty complaints is a small trial.
- **Gemma 4 e4B was dropped before the trial:** it runs like a 4B model but downloads and loads like an 8B one (6.6 GB).
- **Summaries are kept under 50 words.** Granite padded them with the consumer's history of contacts with the company. A tighter instruction, decided on the dev results before any test result, cut the dev summaries from 51 to 33 words on average without changing the decisions.

**The model is treated as unreliable:**
- its output is constrained to the schema while it's generated, then validated again in code, with sampling pinned (temperature 0, fixed seed);
- a truncated or invalid answer gets one re-ask with a new seed, and connection errors get retries with backoff;
- anything still failing goes to a person, with the error recorded;
- if the model server is lost, the batch stops and writes nothing, so an output file is never partial;
- complaint text is fenced in tags it can't close, and the prompt says it's data, not instructions. The injection test shows the 3B model often follows embedded instructions anyway (section 4.5).

**Runner and outputs** ([`run_triage.py`](scripts/triage/run_triage.py)). Every complaint takes one path: narratives under 5 words skip the model, and the review policy always runs. A live terminal panel shows each decision and, for labelled complaints, how it compares with the reference. The CSV output has fixed columns: the judgement, every review reason, attempts, errors, tokens, latency and the model digest. `--limit N` runs a trial on the first N labelled complaints without touching the committed outputs.

### 4.4 Evaluation approach
*The gold set (80 complaints labelled by Gemini, dev and test, provenance); what "correct" means for each field; metrics and Wilson ranges; tagged and untagged recall; CFPB as a weak reference; consistency on duplicates; summary checks and the spot-check; the `confidence_note` check; the prompt-injection test, with pass rules fixed before the run.*

### 4.5 Results
*Results table; the workload cut; cost at 50,000 a month; where it goes wrong; whether the model is the limit.*

### 4.6 Limitations
*Model-made reference labels and their known inconsistencies; few sensitive test cases; prompt injection; the unevaluated `confidence_note`; run-to-run differences; the minimal legal-words list; the client's mix; redaction.*

### 4.7 Measuring at scale, and recommendation
*What we would measure in production, and the shadow-mode pilot.*

### 4.8 Cut and possible additions
*Opens with what we built, by line count: essential code (969 of 1,246 lines) and each addition with its lines and reason. Then each cut and possible addition with its reason, including the output format (CSV with y/n against the brief's JSON example).*

## 5. Production
*The memo in brief (architecture, monitoring, data and residency, phased rollout, what we need from PayGuard), linking to the memo and its PDF.*

## 6. Questions for PayGuard

We built both prototypes without further input from you. Wherever we needed an answer we didn't have, we made an assumption and recorded it. Each row below is a question we would put to you, what we assumed meanwhile, and what changes with your answer. The questions that block a production launch of fraud scoring also appear in the memo's [What we need from PayGuard](docs/memo.md#what-we-need-from-payguard).

### Fraud detection: your data

| Question | What we assumed | What changes with your answer |
|---|---|---|
| **Identifiers.** Can each transaction carry a card token, customer ID, merchant and channel? | None of these is in the data, so the model scores each transaction on its own. | Velocity features (spend and attempts per card over recent minutes and hours), the largest expected gain; card-level metrics that count each compromised card once; partitioning the event stream by card in production. |
| **Duplicates.** Do transactions carry a unique ID, and what are the 1,081 exact copies (same values, same second)? | Kept as real traffic: deduplication belongs upstream, at ingestion, not in the model. | Upstream deduplication. Fraud is 10 times more common inside the copies (1.73% against 0.173%), which suggests card testing; an ID would show whether that can become a live signal. |
| **Label delay.** How long until a fraud is confirmed, and can we receive a chargeback feed? | Unknown. With 2 days of data, the windows have no gap for label delay. | The gap between training and test data, the retraining cadence, and how soon a fall in recall becomes visible. |
| **History.** Can you share several weeks of transactions? | Two days were available. | Forward-chaining validation; telling drift apart from time-of-day effects; time-of-day handling; firmer model comparisons (115 test frauds couldn't separate the two models with confidence). |
| **Clock.** When, and in which time zone, does the timestamp start? | Unknown, so `Time` is dropped and there's no hour-of-day feature, though fraud runs 4.3 times higher in quiet hours. | An hour-of-day feature, or separate thresholds for busy and quiet hours. |
| **Feature transformation.** What produces the 28 anonymised components, and is it fixed and versioned? | Live traffic goes through the same transformation as this data. | A silent change upstream would shift scores (training-serving skew). Access to the raw fields would allow feature engineering and readable explanations. |
| **Currency.** Which currency are amounts in? | Not named in the data, so value caught is given as a share (66% of fraud value). | The value of fraud caught and missed, in money. |

### Fraud detection: your operations

| Question | What we assumed | What changes with your answer |
|---|---|---|
| **Review capacity.** How many fraud alerts can your team review a day? | 0.2% of transactions (about 285 a day), just above the 0.173% fraud rate, so the model rather than the budget limits recall. We started at 0.1%, a published industry figure, but below the fraud rate it capped recall at 58%; we changed it before any model was scored. | The threshold, and how many frauds are caught. Returns fall fast beyond 0.3%: about 92 of 115 test frauds at 0.3%, about 100 at 5%. |
| **Cost of errors.** What does a false alert cost you (customer friction, declined sales, analyst time) against a missed fraud (chargeback, fees)? | No ratio. Errors are weighed only through the alert budget, with a missed fraud treated as worse than a checked genuine transaction. | The operating point, a cost-weighted threshold, and which score band is declined or stepped up rather than reviewed. |
| **Decision timing.** Must the score decide inside the authorisation, or can action follow it? | Inside the authorisation: one transaction at a time, synchronously. | The architecture: scoring after the authorisation, or in small batches, would relax the latency limit. |
| **Latency limit.** How much of the authorisation window can fraud scoring take? | p99 within 50 ms, the lenient end of the published 10–50 ms range. | The headroom: we measured p99 25.6 ms end to end on one machine. |
| **Traffic volume.** What are your average and peak transaction rates? | None assumed. The replay runs at 4 times the data's own pace without overlapping requests; load testing was out of scope. | Sizing, and the load test before launch. |
| **Explanations.** Do you or your regulator need a reason for each decision? | No: per-decision explanations would point to anonymised components with no business meaning. | SHAP explanations (phase 2 in the memo), which are more useful on raw fields. |

### Fraud detection: production

| Question | What we assumed | What changes with your answer |
|---|---|---|
| **Residency.** Is there an AWS region in your country? | Yes: the memo's design runs in one in-country region. | Otherwise the same components run on AWS Outposts or on-premises Kubernetes. |
| **Retention and PCI DSS.** What are your retention periods and PCI DSS scope? | Stated generally: data kept for the legal minimum; scope kept small by tokenisation and segmentation. | Storage lifecycle rules and network segmentation. |
| **Team skills.** Which of Kafka, Flink, Redis and EKS does your team run today? | Tools chosen for their fit at scale; your team's skills unknown. | Who runs what, training needs, or managed alternatives. |
| **Rollout targets.** What precision, false-decline and complaint levels must each phase meet? | The rollout gates are named without numbers. | When each phase moves on. |
| **Fallback and actions.** What happens when scoring times out, and do you support step-up checks? | Not covered by the prototype; the memo's phase 2 assumes a step-up check or a decline. | The design of phase 2. |

### Complaint triage: your data

| Question | What we assumed | What changes with your answer |
|---|---|---|
| **Complaint source.** CFPB removed narratives from its live database in September 2026. Can you share a sample of your own complaints, or is the archived CFPB file acceptable? | CFPB's own bulk file as archived on 2026-08-15, documented and hash-checked. | The slice, and the scores if your complaints differ from CFPB's. |
| **Fields and tags.** Do your complaints arrive with the same fields as CFPB's, including the Older American and Servicemember tags? | Yes, the same fields. | Without tags the tag rule can't fire, and the recall on untagged complaints (10 of 14, or 12 of 14 with the legal-words rule) becomes the guide. |
| **Intake mix.** What's your mix of complaints by product? | The slice's mix: mostly debt collection, checking and credit cards, with 5% credit reporting. CFPB's database is about 90% credit reporting, but few of those complaints have a published narrative. | The automation rate on your intake (45.6% on the slice). |
| **Personal data.** Your complaints arrive unredacted. May they go to a hosted model, or must they stay on your infrastructure? | A local model on our machine; CFPB had already redacted the slice. | Hosted against local (about $10–37 a month on small hosted models, about $29 of GPU time locally), data handling, and better urgency from visible dates. |
| **Past decisions.** Can you share your team's past routing and escalation decisions? | An 80-complaint reference labelled by a stronger model (Gemini) from our labelling guide. | A reference grounded in your own decisions, and the override monitoring a production system learns from. |

### Complaint triage: your operations

| Question | What we assumed | What changes with your answer |
|---|---|---|
| **Teams.** Do our seven routing categories match your teams? | Our own taxonomy, read from the complaint's text: fraud first, then credit-report content, then product. | The taxonomy. One file drives the prompt, the labelling guide and the CFPB mapping, so a change stays consistent. |
| **Always-human cases.** Beyond fraud allegations and legal threats, which cases must always reach a human? | Seven reasons: any CFPB tag, any flag, high urgency, category `other`, legal words, a failed model call, or unusable text. | How many complaints reach a human (54.4% of the slice; 8.4% for a tag alone). |
| **Response-time targets.** Do you have response-time targets for complaints, or your own definition of urgency? | Harm-led urgency: the kind of harm, and whether it's ongoing, imminent or past, sets the level. Time cues in the text can raise it; missing or redacted time never lowers it. | The urgency definitions, and with them which complaints the review rule sends to a human (high urgency always goes to one). |
| **Very short complaints.** What should happen to complaints with almost no text? | Under 5 words, they go to a human without the model (none in the slice). | The cut-off. |
| **Timing.** Can triage wait for a batch, or must it run as complaints arrive? | A batch script, as the brief asked. | Hosted models' batch APIs halve their prices. |

### About the brief

| Question | What we assumed | What changes with your answer |
|---|---|---|
| **Time estimate.** Is ~3 hours per part a requirement or a guide? | A guide. We built further where it answered the brief: the replay and API are the answer to real-time scoring. Section 7 lists what could be cut if the time were binding. | What gets cut. |
| **Hand labels.** Is a reference labelled by a stronger model acceptable in place of hand labels? | Yes, given the time estimate; disclosed with its limits in section 4.6. | Hand labels for the test set, and a measure of how far the model's labels agree with them. |
| **Summary length.** Must summaries stay within 1–2 sentences? | A target, not enforced: 23% run longer (all under 50 words) where the extra length keeps details needed to handle the complaint. | A sentence check that sends long summaries back to the model. |
| **Output format.** What format does your system ingest? | CSV with y/n values and extra columns (review reasons, tokens, model digest); the brief's example was JSON. | A JSON writer with the brief's five fields. |

## 7. Engineering and scope
*Repository structure; shared code paths (training and serving; taxonomy, prompt and labelling guide); the tests and what they guard; reproducibility (hash-checked data, clean-room runs); the workflow (branches, PRs, automated review); AI use; size against the ~3 h estimate (1,271 of 2,396 Python code lines essential, with the counting method); an overview of the cuts we made and the additions we suggest, and why, linking to each part's full list (3.8, 4.8); what could be cut if the timescale were binding, and how far the possible additions would go.*
