"""The shortlisted fraud models. Each is one Pipeline that carries its own preprocessing,
so the saved artifact is the single path from a raw transaction to a score."""
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from payguard.fraud.data import FEATURES

COMPONENTS = [f for f in FEATURES if f != "Amount"]


def preprocess() -> ColumnTransformer:
    """The whole feature definition. Columns are picked by name and everything else (Time,
    Class, extra fields) is dropped, so a raw transaction in any column order scores the same."""
    return ColumnTransformer(
        [
            # Amount is heavily skewed and 0 for some transactions, hence log1p rather than log.
            ("amount", FunctionTransformer(np.log1p, feature_names_out="one-to-one"), ["Amount"]),
            ("components", "passthrough", COMPONENTS),
        ],
        remainder="drop",
    )


def logreg() -> Pipeline:
    return make_pipeline(preprocess(), StandardScaler(), LogisticRegression(class_weight="balanced"))


def hgb() -> Pipeline:
    # The default early stopping holds out a random 10% of training rows, which would shuffle
    # time inside the training window. log1p doesn't change trees; it's kept so both models
    # share one feature definition.
    return make_pipeline(preprocess(), HistGradientBoostingClassifier(early_stopping=False, random_state=0))


CANDIDATES = {"logreg": logreg, "hgb": hgb}

# MLflow saves sklearn models with skops, which refuses types not on its safe list. HGB's tree
# object isn't on it because a tampered file could crash predict(); we only load models we
# trained ourselves, so it's trusted explicitly. Pass this to every MLflow save.
TRUSTED_TYPES = ["sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor"]
