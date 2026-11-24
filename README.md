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
*In planning.*

### Evaluation
*In planning.*

### Results
*Pending.*

### Cut / Added
- **Cut: data versioning (DVC).** The data is one fixed source file, so a hash-checked download script gives the same guarantee without needing a storage remote. If the client's data starts changing over time, revisit this with DVC or the client's own data platform.
- **Cut: third-party mirror download.** Kaggle's public download works without an account, so a second automatic source was redundant. If Kaggle ever requires sign-in, the manual route covers it.

### Limitations
- The data covers only about 2 days of transactions, so we can't simulate realistic feedback delay (the time before fraud labels arrive).
- There's no card or customer ID, so card-level metrics and history (velocity) features aren't possible.
- The features are anonymised with PCA, which limits feature engineering and how well we can explain decisions.

## Problem 2: Complaint Triage

*Not started.*
