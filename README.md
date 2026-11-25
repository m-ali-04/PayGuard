# PayGuard

Two prototypes for PayGuard: real-time fraud scoring and LLM complaint triage.

- **Fraud scoring API.** A gradient-boosted tree model behind a FastAPI service scores one card transaction at a time, and a replay sends PayGuard's transactions through it at their recorded pace. On a held-out 12-hour window it caught 82 of 115 frauds at a threshold fixed in advance, and answered within 25.6 ms at p99.
- **Complaint triage pipeline.** A batch script gives each complaint a category, urgency, summary and confidence note using a local LLM (Granite 4.2 3B through Ollama), while code decides which complaints need a person. On 500 CFPB complaints it routed 45.6% with no person, and 20 of the 22 test complaints it routed alone reached the right team.

[REPORT.md](REPORT.md) explains the approach, results, limitations and our questions for PayGuard. The [memo](docs/memo.md) ([PDF](docs/memo.pdf)) sets out the production design for fraud scoring.

## Requirements

- **Linux, or Windows through WSL2.** Tested on Ubuntu under WSL2 on Windows 11. Native Windows isn't supported: with Smart App Control on, Windows blocks the unsigned compiled files that uv's Python and the scientific packages ship. On Windows, run `wsl --install` in an administrator PowerShell, restart, open Ubuntu, and clone the repo into the Linux home folder (for example `~/PayGuard`), not under `/mnt/c`, which is much slower from WSL. The API is reachable from a Windows browser at the same `127.0.0.1` addresses.
- `curl` and an internet connection.
- Complaint triage only: `sudo` to install Ollama, and about 2 GB for the model. An NVIDIA GPU is used if present.
- Memo PDF only: Chrome or Chromium.

## Setup

1. **Install uv**, the Python package and project manager, then open a new terminal, or run `source $HOME/.local/bin/env`, so the shell finds `uv`:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. **Install the dependencies.** This also installs Python 3.12 if it's missing:
   ```bash
   uv sync
   ```

Run every command below from the repo root.

## Fraud scoring

1. **Get the data.** The script asks which source to use, or you can pass `--source`:
   ```bash
   uv run scripts/fraud/get_data.py                  # asks: kaggle / manual
   uv run scripts/fraud/get_data.py --source kaggle  # Kaggle CLI via uvx; no install or account needed
   ```
   For a manual download, get `creditcard.csv` from https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud, place it at `data/raw/creditcard.csv` and re-run the script to verify it. Both routes check the same SHA-256: `76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89`.
2. **(Optional) Regenerate the data report.** The analysis tools sit in their own dependency group, so the serving runtime doesn't install them:
   ```bash
   uv run --group analysis scripts/fraud/data_understanding.py   # writes reports/fraud/data_understanding.md and its figures
   ```
3. **Train both models.** Each is fitted on the training window and logged to a local MLflow store (`mlflow.db` and `mlruns/`, both git-ignored). MLflow warns that it can't find pip's version: uv environments don't include pip, and the warning is harmless. If a coding agent runs these commands, MLflow also prints a hint about its agent skills in each step that uses it; `MLFLOW_DISABLE_AGENT_HINT=1` hides it.
   ```bash
   uv run scripts/fraud/train.py
   uv run mlflow ui --backend-store-uri sqlite:///mlflow.db   # optional: browse the runs at http://127.0.0.1:5000
   ```
4. **Write the decision report.** This scores the latest run of each model, writes `reports/fraud/decision_report.md` and logs the live threshold on each run (about 3 minutes, mostly the bootstrap):
   ```bash
   uv run scripts/fraud/evaluate.py
   ```
5. **Serve the selected model.** The API loads the selected model's latest run with the threshold step 4 logged on it, and refuses to start if that run hasn't been evaluated:
   ```bash
   uv run uvicorn payguard.fraud.api:app   # interactive docs at http://127.0.0.1:8000/docs
   ```
   If port 8000 is taken, add `--port 8001` and give the replay the same address with `--url`.
6. **Replay transactions through the API**, in a second terminal while the API runs. The default replays the demo slice, data time 42:40–43:20 at 4 times real time (about 10 minutes), with a live panel. It then checks every served score against the offline model and writes `reports/fraud/replay_report.md`. For meaningful latency, run it on mains power with nothing heavy running, since the replay, the API and the model share the machine.
   ```bash
   uv run scripts/fraud/replay.py
   uv run scripts/fraud/replay.py --start 39:31 --length 20     # another slice of the test window (36:00–48:00)
   uv run scripts/fraud/replay.py --url http://127.0.0.1:8001   # an API on another port
   ```
   Keep `--speed` low enough that requests don't overlap: with default threading, overlapping requests slow the API sharply ([REPORT §3.6](REPORT.md#36-real-time-inference)).
7. **Score one transaction** (the 28 components and Amount; other fields are ignored):
   ```bash
   curl -s http://127.0.0.1:8000/v1/score -H 'content-type: application/json' \
     -d "{$(for i in $(seq 1 28); do printf '"V%d": 0, ' $i; done)\"Amount\": 25}"
   # {"fraud_score":…,"alert":false,"threshold":0.357…,"model_run_id":"…"}
   ```

## Complaint triage

1. **The complaint slice** is committed at `data/triage/complaints_sample.csv`, so there's nothing to download. Optionally verify it, or rebuild it from the archived CFPB file (reads the first 10 MB, about 20 seconds):
   ```bash
   uv run scripts/triage/get_complaints.py            # checks the committed file's SHA-256; no network
   uv run scripts/triage/get_complaints.py --rebuild  # re-draws it from the archive; must give the same bytes
   ```
2. **Install Ollama and the model.** Ollama is a system install, not a Python package. Ubuntu on WSL needs `zstd` for its installer:
   ```bash
   sudo apt-get install -y zstd
   curl -fsSL https://ollama.com/install.sh | sh   # installs and starts the Ollama service
   ollama pull granite4.2:3b                        # about 2 GB
   ```
3. **Run the pipeline** in a terminal you can watch: a live panel shows each decision and, for labelled complaints, how it compares with the reference labels.
   ```bash
   uv run scripts/triage/run_triage.py --limit 20   # trial: the first 20 labelled complaints -> data/triage/trial_granite4.2_3b.csv (git-ignored)
   uv run scripts/triage/run_triage.py --injection  # the 10 prompt-injection cases -> data/triage/injection_outputs.csv
   uv run scripts/triage/run_triage.py              # all 500 -> data/triage/triage_sample.csv
   ```
   A full run takes about 25 minutes on an 8 GB laptop GPU (RTX 4070). The full and injection runs overwrite the committed outputs, and answers can differ slightly between runs ([REPORT §4.6](REPORT.md#46-limitations)).
4. **Write the evaluation report** from the committed outputs; no model is needed:
   ```bash
   uv run scripts/triage/evaluate_triage.py   # writes reports/triage/evaluation_report.md
   ```
5. **(Optional) Validate the reference labels** against the taxonomy:
   ```bash
   uv run scripts/triage/make_labelling_file.py --check
   ```

## Memo PDF

After editing `docs/memo.md`, rebuild `docs/memo.pdf`:
```bash
docs/build_memo_pdf.sh
```
It needs uv and Chrome. On WSL it uses Windows Chrome by default; elsewhere, set `CHROME` to a Chrome or Chromium binary.

## Tests

```bash
uv run pytest
```
98 tests. The ones that need the fraud data are skipped until it's downloaded.
