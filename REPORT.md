# PayGuard: Project Report

*Outline draft. Each section says what it will cover; sections are written and reviewed one at a time.*

## 1. Summary
*Both answers on one screen. Fraud: ready for a shadow-mode rollout (82 of 115 test frauds caught at a threshold fixed in advance; p99 25.6 ms end to end; served scores identical to offline). Triage: 45.6% of complaints routed with no human, 20 of 22 auto-routed test complaints to the right team; a shadow-mode pilot, not a switchover. The production plan in one line, linking to the memo.*

## 2. Reading guide
*Written last, once section numbers are final. A table mapping each criterion (judgment, evaluation rigour, code quality, communication, results) to the sections that show it, plus where the generated reports, the decision log (CONTEXT.md) and AI usage (AI_USAGE.md) live.*

## 3. Fraud detection

### 3.1 Framing and scope
*Scoring inside the authorisation window; synchronous single-transaction scoring; the p99 ≤ 50 ms limit and where it comes from; what "good" means operationally (alerts a team can review); what was out of scope (tuning, ensembling, load testing).*

### 3.2 Data findings
*About 2 days, PCA-anonymised, no card, customer or transaction ID; 0.173% fraud; drift between the days; 1,081 exact duplicates (fraud 10x more common inside them); fraud 4.3x higher in quiet hours; what each of these allows and rules out. Links to the data report.*

### 3.3 Evaluation design
*Time split, and why not random k-fold or forward-chaining; no gap between windows; the 0.2% alert budget and how it was set (0.1% first, changed before any model was scored); metrics (average precision as the headline, precision and recall at the budget, ROC-AUC for reference); the selection rule fixed in advance; bootstrap ranges as information, not a gate.*

### 3.4 What we built
*The shortlist (12 families considered → logistic regression and gradient-boosted trees) and the two stability settings; preprocessing inside the saved pipeline; MLflow with skops; the scoring API contract; the replay at the client's pace; the parity check.*

### 3.5 Results
*Results table; why gradient-boosted trees were chosen; how certain the gain is; the operating-point recommendation (threshold, recalibration, the daytime finding); cost of errors: what a false alert and a missed fraud cost, and the value of fraud caught; replay results; optional threshold chart.*

### 3.6 Real-time inference
*Features must exist at authorisation time (why `Time` is dropped); velocity features need streaming state, the biggest production lever; label delay sets the retraining cadence; the upstream PCA step as a skew risk; the OpenMP finding and single-thread workers.*

### 3.7 Limitations
*Short history, no IDs, duplicates of unknown origin, day/night threshold drift, anonymised features, untested concurrent load.*

### 3.8 Cut, added and possible additions
*Each with its reason, including why the replay and API are the answer to "real-time" rather than extras.*

## 4. Complaint triage

### 4.1 Framing
*The client's situation (fully manual handling, two worries: hallucination and misrouted sensitive cases) and how it set the evaluation's priorities; the brief's record; 50,000 complaints a month.*

### 4.2 Data
*CFPB's removal of narratives and the archived source; the slice and how to reproduce it; the data review (product mix, noisy CFPB labels, sensitive share, redaction).*

### 4.3 Triage design
*Taxonomy and rule order; harm-led urgency; the five flags; `requires_human` as a policy in code; the legal-words backstop (added after the results); model choice (Granite against Qwen and Gemma); robustness (schema, re-ask, retries, failure goes to a human); fenced complaint text.*

### 4.4 Evaluation approach
*The gold set (80 complaints labelled by Gemini, dev and test, provenance); what "correct" means for each field; metrics and Wilson ranges; tagged and untagged recall; CFPB as a weak reference; consistency on duplicates; summary checks and the spot-check; the `confidence_note` check; the prompt-injection test, with pass rules fixed before the run.*

### 4.5 Results
*Results table; the workload cut; cost at 50,000 a month; where it goes wrong; whether the model is the limit.*

### 4.6 Limitations
*Model-made reference labels and their known inconsistencies; few sensitive test cases; prompt injection; the unevaluated `confidence_note`; run-to-run differences; the minimal legal-words list; the client's mix; redaction.*

### 4.7 Measuring at scale, and recommendation
*What we would measure in production, and the shadow-mode pilot.*

### 4.8 Cut and possible additions
*Each with its reason, including the output format (CSV with y/n against the brief's JSON example).*

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
*Repository structure; shared code paths (training and serving; taxonomy, prompt and labelling guide); the tests and what they guard; reproducibility (hash-checked data, clean-room runs); the workflow (branches, PRs, automated review); AI use; size against the ~3 h estimate (line counts recounted); an overview of the cuts we made and the additions we suggest, and why, linking to each part's full list (3.8, 4.8); what could be cut if the timescale were binding, and how far the possible additions would go.*
