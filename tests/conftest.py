import numpy as np
import pandas as pd
import pytest

from payguard.fraud.data import LABEL
from payguard.fraud.models import COMPONENTS


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
