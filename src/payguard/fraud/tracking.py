"""The local MLflow store: where runs live and which run of a model is current. Shared by the
training and report scripts and the API, so all three look runs up the same way."""
from pathlib import Path

import mlflow
import pandas as pd

# The repo root, because the package runs from its source tree (uv's default editable install).
# A packaged deployment would point this at its own store instead.
ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = "fraud-shortlist"


class StoreError(Exception):
    """The store can't serve what was asked; the message says how to fix it."""


def use_local_store() -> None:
    # MLflow's default store and artifact folder resolve against the working directory;
    # pin both to the repo root so runs land in one place wherever the code is started.
    mlflow.set_tracking_uri(f"sqlite:///{ROOT / 'mlflow.db'}")
    experiment = mlflow.get_experiment_by_name(EXPERIMENT)
    if experiment is None:
        mlflow.create_experiment(EXPERIMENT, artifact_location=(ROOT / "mlruns").as_uri())
    elif experiment.lifecycle_stage == "deleted":
        # MLflow only soft-deletes, so the name stays taken. Not restored automatically,
        # since that would quietly undo the deletion.
        raise StoreError(f"Experiment '{EXPERIMENT}' is deleted. Restore it in the MLflow UI, or purge it "
                         "from the repo root with: uv run mlflow gc --backend-store-uri sqlite:///mlflow.db "
                         "--tracking-uri sqlite:///mlflow.db")
    mlflow.set_experiment(EXPERIMENT)


def latest_run(name: str) -> pd.Series:
    """The newest finished run of one candidate."""
    runs = mlflow.search_runs(
        experiment_names=[EXPERIMENT],
        filter_string=f"params.candidate = '{name}' and attributes.status = 'FINISHED'",
        order_by=["start_time DESC"],
        max_results=1,
    )
    if runs.empty:
        raise StoreError(f"No finished '{name}' run in experiment '{EXPERIMENT}'. Run: uv run scripts/train.py")
    return runs.iloc[0]
