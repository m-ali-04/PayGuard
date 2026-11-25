import json

import mlflow
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from payguard.fraud import api, tracking
from payguard.fraud.data import FEATURES, LABEL
from payguard.fraud.models import hgb


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


@pytest.mark.parametrize("field, value", [("V1", "abc"), ("V1", float("nan")), ("Amount", -1.0)])
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


def test_start_up_refuses_a_run_without_a_threshold(tmp_path, monkeypatch):
    """A model trained after the last evaluate.py call has no cut of its own yet."""
    monkeypatch.setattr(tracking, "ROOT", tmp_path)
    tracking.use_local_store()
    with mlflow.start_run():
        mlflow.log_param("candidate", "hgb")
    with pytest.raises(tracking.StoreError, match="evaluate.py"):
        api.load_selected()
