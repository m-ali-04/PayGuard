import pandas as pd
import pytest

from get_data import DEST
from payguard.fraud.data import LABEL, load, split

pytestmark = pytest.mark.skipif(not DEST.is_file(), reason="dataset missing: run scripts/fraud/get_data.py")


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return load(DEST)


@pytest.fixture(scope="module")
def windows(df) -> dict[str, pd.DataFrame]:
    return split(df)


def test_windows_cover_every_row_once(df, windows):
    index = pd.concat(windows.values()).index
    assert len(index) == len(df) and index.is_unique


def test_fraud_counts_match_agreed_split(windows):
    assert {name: int(w[LABEL].sum()) for name, w in windows.items()} == {
        "train": 281, "validation": 96, "test": 115,
    }
