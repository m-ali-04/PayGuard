"""Fit each shortlisted model on the training window and log it to MLflow.

Usage: uv run scripts/train.py
Browse: uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
No scores are computed here: the decision report evaluates the logged models.
"""
import sys
import time
from datetime import UTC, datetime

import mlflow
import mlflow.sklearn
import pandas as pd

from get_data import DEST, is_valid
from payguard.fraud.data import FEATURES, LABEL, WINDOWS, load, split
from payguard.fraud.models import CANDIDATES, save_options
from payguard.fraud.tracking import EXPERIMENT, StoreError, use_local_store


def train(name: str, train_df: pd.DataFrame, session: str) -> None:
    with mlflow.start_run(run_name=name):
        model = CANDIDATES[name]()
        start = time.perf_counter()
        model.fit(train_df, train_df[LABEL])
        mlflow.log_metric("fit_seconds", time.perf_counter() - start)
        mlflow.log_params({
            "candidate": name,
            # Shared by every run of one train.py call, so the report never pairs runs from different calls.
            "session": session,
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
    try:
        use_local_store()
    except StoreError as e:
        sys.exit(str(e))
    session = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for name in CANDIDATES:
        train(name, train_df, session)
        print(f"Logged {name} to experiment '{EXPERIMENT}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
