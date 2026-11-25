"""The scoring API: one transaction in, a fraud score and an alert decision out.

Run from the repo root: uv run uvicorn payguard.fraud.api:app   (docs at http://127.0.0.1:8000/docs)
Serves the selected candidate's latest run, with the threshold evaluate.py logged on that same run.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version
from typing import Literal

import mlflow.sklearn
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, create_model
from sklearn.pipeline import Pipeline

from payguard.fraud.data import FEATURES
from payguard.fraud.models import SELECTED
from payguard.fraud.tracking import StoreError, latest_run, use_local_store


@dataclass(frozen=True)
class Scorer:
    model: Pipeline
    threshold: float
    run_id: str


def load_selected() -> Scorer:
    use_local_store()
    run = latest_run(SELECTED)
    threshold = run.get("metrics.live_threshold")
    # A run trained after the last evaluate.py call has no cut yet; serving it with another run's
    # cut would pair a model with a threshold set on different scores.
    if pd.isna(threshold):
        raise StoreError(f"The latest '{SELECTED}' run ({run.run_id[:8]}) has no live threshold. "
                         "Run: uv run scripts/evaluate.py")
    return Scorer(mlflow.sklearn.load_model(f"runs:/{run.run_id}/model"), float(threshold), run.run_id)


# The PCA components are centred on zero, so all-zero components describe a typical transaction.
# Synthetic on purpose: the docs page shouldn't carry a real client transaction.
EXAMPLE = {f: 0.0 for f in FEATURES} | {"Amount": 25.0}

# Built from FEATURES so the API and the model share one field list.
_fields = {f: (float, Field(description="Anonymised PCA component from the client's upstream pipeline."))
           for f in FEATURES}
# Amount is log1p-transformed, which is undefined below -1, and amounts are never negative.
_fields["Amount"] = (float, Field(ge=0, description="Transaction amount."))
Transaction = create_model(
    "Transaction",
    # Unknown fields are dropped, as the model pipeline does; NaN/Infinity are refused because the
    # contract has no missing values.
    __config__=ConfigDict(extra="ignore", allow_inf_nan=False, json_schema_extra={"examples": [EXAMPLE]}),
    **_fields,
)


class Score(BaseModel):
    fraud_score: float = Field(description="The model's fraud probability (not calibrated); higher is riskier.")
    alert: bool = Field(description="True when fraud_score is at or above the threshold.")
    threshold: float = Field(description="Cut fixed on the validation window to flag the alert budget.")
    model_run_id: str = Field(description="MLflow run of the model that produced the score.")


class Health(BaseModel):
    status: Literal["ok"]
    model: str = Field(description="Candidate being served.")
    model_run_id: str
    threshold: float


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Loaded once, before the first request, so no request pays for loading the model.
    app.state.scorer = load_selected()
    yield


app = FastAPI(
    title="PayGuard Fraud Scoring",
    version=version("payguard"),
    description="Scores one card transaction at a time and flags it for review when the fraud score "
                "reaches the threshold set on validation data.",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default 422 echoes each rejected value back, and a NaN can't be written as JSON, so a
    # NaN request crashed the error handler into a 500. Without the echo, loc and msg still name the
    # field and the problem, and transaction values aren't repeated back.
    errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


# A plain def, so FastAPI runs the CPU-bound scoring in its threadpool instead of the event loop.
@app.post("/v1/score", tags=["scoring"], summary="Score one transaction")
def score(transaction: Transaction, request: Request) -> Score:
    scorer: Scorer = request.app.state.scorer
    s = float(scorer.model.predict_proba(pd.DataFrame([transaction.model_dump()]))[0, 1])
    return Score(fraud_score=s, alert=s >= scorer.threshold, threshold=scorer.threshold,
                 model_run_id=scorer.run_id)


@app.get("/v1/health", tags=["operations"], summary="Show the model being served")
def health(request: Request) -> Health:
    scorer: Scorer = request.app.state.scorer
    return Health(status="ok", model=SELECTED, model_run_id=scorer.run_id, threshold=scorer.threshold)
