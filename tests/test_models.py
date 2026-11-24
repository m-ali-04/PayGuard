import mlflow.sklearn
import numpy as np
import pandas as pd
import pytest

from payguard.fraud.data import FEATURES, LABEL
from payguard.fraud.models import CANDIDATES, COMPONENTS, TRUSTED_TYPES, preprocess


@pytest.fixture(scope="module")
def raw() -> pd.DataFrame:
    """Small synthetic stand-in for raw transactions, with the same fields as the client's file."""
    rng = np.random.default_rng(0)
    n = 400
    df = pd.DataFrame(rng.normal(size=(n, 28)), columns=COMPONENTS)
    df["Amount"] = rng.exponential(80, n).round(2)
    df["Time"] = np.sort(rng.uniform(0, 86_400, n))
    df[LABEL] = (df.V14 + rng.normal(scale=0.5, size=n) < -1.5).astype(int)
    return df


def scores(model, df: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(df)[:, 1]


@pytest.fixture(scope="module", params=list(CANDIDATES))
def fitted(request, raw):
    return CANDIDATES[request.param]().fit(raw, raw[LABEL])


def test_preprocess_logs_amount_and_drops_other_fields(raw):
    out = preprocess().fit(raw).transform(raw)
    assert out.shape == (len(raw), len(FEATURES))
    np.testing.assert_allclose(out[:, 0], np.log1p(raw.Amount))
    np.testing.assert_allclose(out[:, 1:], raw[COMPONENTS])


def test_scores_ignore_column_order_and_extra_fields(fitted, raw):
    shuffled = raw[raw.columns[::-1]].assign(merchant="unused")
    np.testing.assert_array_equal(scores(fitted, shuffled), scores(fitted, raw))


def test_saved_model_scores_identically(fitted, raw, tmp_path):
    mlflow.sklearn.save_model(fitted, tmp_path / "model", skops_trusted_types=TRUSTED_TYPES)
    reloaded = mlflow.sklearn.load_model(str(tmp_path / "model"))
    np.testing.assert_array_equal(scores(reloaded, raw), scores(fitted, raw))
