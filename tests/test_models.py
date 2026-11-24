import mlflow.pyfunc
import mlflow.sklearn
import numpy as np
import pandas as pd
import pytest

from get_data import DEST
from payguard.fraud.data import FEATURES, LABEL, load, split
from payguard.fraud.models import CANDIDATES, COMPONENTS, hgb, preprocess, save_options


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


def test_scores_need_only_the_model_fields(fitted, raw):
    np.testing.assert_array_equal(scores(fitted, raw[FEATURES]), scores(fitted, raw))


def test_saved_model_scores_identically(fitted, raw, tmp_path):
    """Saves the way scripts/train.py does, then scores live-shaped rows (no Time, no label)
    through both loaders: the sklearn one and MLflow's generic one used by serving tools."""
    live = raw[FEATURES]
    path = str(tmp_path / "model")
    mlflow.sklearn.save_model(fitted, path, **save_options(fitted, live.head(5)))
    expected = scores(fitted, raw)
    np.testing.assert_array_equal(scores(mlflow.sklearn.load_model(path), live), expected)
    np.testing.assert_array_equal(np.asarray(mlflow.pyfunc.load_model(path).predict(live))[:, 1], expected)


@pytest.mark.skipif(not DEST.is_file(), reason="dataset missing: run scripts/get_data.py")
def test_hgb_training_does_not_saturate_on_client_data():
    """With sklearn's default l2_regularization=0, training diverged on the client's training window
    and hundreds of scores hit exactly 1.0, so the top alerts couldn't be ranked. Synthetic data
    doesn't reproduce it, hence the real window."""
    train = split(load(DEST))["train"]
    s = scores(hgb().fit(train, train[LABEL]), train)
    assert 0 < s.min() and s.max() < 1
