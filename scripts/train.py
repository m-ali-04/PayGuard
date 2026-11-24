"""Fit each shortlisted model on the training window and log it to MLflow.

Usage: uv run scripts/train.py
Browse: uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
No scores are computed here: the decision report evaluates the logged models.
"""
import sys
import time
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd

from get_data import DEST, is_valid
from payguard.fraud.data import FEATURES, LABEL, WINDOWS, load, split
from payguard.fraud.models import CANDIDATES, save_options

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "fraud-shortlist"


def use_local_store() -> None:
    # MLflow's default store and artifact folder resolve against the working directory;
    # pin both to the repo root so runs land in one place wherever the script is started.
    mlflow.set_tracking_uri(f"sqlite:///{ROOT / 'mlflow.db'}")
    experiment = mlflow.get_experiment_by_name(EXPERIMENT)
    if experiment is None:
        mlflow.create_experiment(EXPERIMENT, artifact_location=(ROOT / "mlruns").as_uri())
    elif experiment.lifecycle_stage == "deleted":
        # MLflow only soft-deletes, so the name stays taken. Not restored automatically,
        # since that would quietly undo the deletion.
        sys.exit(f"Experiment '{EXPERIMENT}' is deleted. Restore it in the MLflow UI, or purge it "
                 "from the repo root with: uv run mlflow gc --backend-store-uri sqlite:///mlflow.db "
                 "--tracking-uri sqlite:///mlflow.db")
    mlflow.set_experiment(EXPERIMENT)


def train(name: str, train_df: pd.DataFrame) -> None:
    with mlflow.start_run(run_name=name):
        model = CANDIDATES[name]()
        start = time.perf_counter()
        model.fit(train_df, train_df[LABEL])
        mlflow.log_metric("fit_seconds", time.perf_counter() - start)
        mlflow.log_params({
            "candidate": name,
            "train_window_hours": WINDOWS["train"],
            "train_rows": len(train_df),
            "train_frauds": int(train_df[LABEL].sum()),
        })
        # Model fields only: Time can't be computed live and the label doesn't exist yet.
        example = train_df[FEATURES].head(5)
        mlflow.sklearn.log_model(model, name="model", **save_options(model, example))


def main() -> int:
    if not is_valid(DEST):
        print(f"No verified dataset at {DEST}. Run: uv run scripts/get_data.py", file=sys.stderr)
        return 1
    train_df = split(load(DEST))["train"]
    use_local_store()
    for name in CANDIDATES:
        train(name, train_df)
        print(f"Logged {name} to experiment '{EXPERIMENT}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
