import json
import os

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from payguard.fraud import api, tracking
from payguard.fraud.data import FEATURES, LABEL
from payguard.fraud.models import hgb, save_options


@pytest.fixture(scope="module")
def scorer(raw) -> api.Scorer:
    model = hgb().fit(raw, raw[LABEL])
    # A middle score taken from the window itself, so transactions sit below, exactly at and above the cut.
    threshold = float(np.sort(model.predict_proba(raw)[:, 1])[len(raw) // 2])
    return api.Scorer(model, threshold, run_id="test-run")


@pytest.fixture
def client(scorer, monkeypatch):
    """The real app with the MLflow lookup swapped for a model fitted here."""
    monkeypatch.setattr(api, "load_selected", lambda: scorer)
    with TestClient(api.app) as c:  # entering runs the start-up (lifespan)
        yield c


def payload(row: pd.Series) -> dict:
    return {f: float(row[f]) for f in FEATURES}


def test_scores_match_the_model_and_alert_from_the_threshold_up(client, scorer, raw):
    expected = scorer.model.predict_proba(raw)[:, 1]
    for i in range(len(raw)):
        body = client.post("/v1/score", json=payload(raw.iloc[i])).json()
        assert body["fraud_score"] == expected[i]
        assert body["alert"] == (expected[i] >= scorer.threshold)
    assert (expected == scorer.threshold).any(), "no transaction sits exactly at the cut"


def test_fields_outside_the_contract_are_ignored(client, raw):
    row = raw.iloc[0]
    with_extras = payload(row) | {"Time": float(row.Time), LABEL: 1, "merchant": "unused"}
    assert client.post("/v1/score", json=with_extras).json() == client.post("/v1/score", json=payload(row)).json()


def test_a_missing_field_is_named_in_the_error(client, raw):
    incomplete = payload(raw.iloc[0])
    del incomplete["V3"]
    response = client.post("/v1/score", json=incomplete)
    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["detail"]] == [["body", "V3"]]


@pytest.mark.parametrize("field, value", [
    ("V1", "abc"), ("V1", True), ("Amount", "25"), ("V1", float("nan")), ("Amount", -1.0),
])
def test_invalid_values_are_refused(client, raw, field, value):
    # Encoded by hand because httpx won't send NaN, though Python's json (and other clients) will.
    body = json.dumps(payload(raw.iloc[0]) | {field: value})
    response = client.post("/v1/score", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["detail"]] == [["body", field]]


def test_health_names_the_served_run(client, scorer):
    assert client.get("/v1/health").json() == {
        "status": "ok", "model": "hgb", "model_run_id": "test-run", "threshold": scorer.threshold,
    }


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """An empty local store in tmp_path. MLflow keeps the store and active experiment process-wide
    (tracking URI, a module global and an env var), so all three are put back afterwards."""
    monkeypatch.setattr(tracking, "ROOT", tmp_path)
    monkeypatch.setattr(mlflow.tracking.fluent, "_active_experiment_id", None)
    uri, experiment_env = mlflow.get_tracking_uri(), os.environ.get("MLFLOW_EXPERIMENT_ID")
    tracking.use_local_store()
    yield
    mlflow.set_tracking_uri(uri)
    # Restored by hand: monkeypatch.delenv records nothing to undo when the variable was unset.
    if experiment_env is None:
        os.environ.pop("MLFLOW_EXPERIMENT_ID", None)
    else:
        os.environ["MLFLOW_EXPERIMENT_ID"] = experiment_env


def test_start_up_serves_the_model_with_its_own_runs_threshold(tmp_store, scorer, raw):
    with mlflow.start_run() as run:
        mlflow.log_param("candidate", "hgb")
        mlflow.sklearn.log_model(scorer.model, name="model", **save_options(scorer.model, raw[FEATURES].head(5)))
        mlflow.log_metric("live_threshold", scorer.threshold)
    loaded = api.load_selected()
    assert (loaded.run_id, loaded.threshold) == (run.info.run_id, scorer.threshold)
    np.testing.assert_array_equal(loaded.model.predict_proba(raw), scorer.model.predict_proba(raw))


def test_start_up_refuses_a_run_without_a_threshold(tmp_store):
    """A model trained after the last evaluate.py call has no cut of its own yet."""
    with mlflow.start_run():
        mlflow.log_param("candidate", "hgb")
    with pytest.raises(tracking.StoreError, match="evaluate.py"):
        api.load_selected()
