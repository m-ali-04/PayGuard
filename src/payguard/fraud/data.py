"""Load the client's transactions and cut them into the agreed time windows."""
from pathlib import Path

import pandas as pd

FEATURES = [f"V{i}" for i in range(1, 29)] + ["Amount"]
LABEL = "Class"
# Hours since the first transaction, half-open [start, end). Train on yesterday, set the
# threshold overnight, test on today; see CONTEXT.md "Evaluation Framework" for the reasons.
WINDOWS = {"train": (0, 24), "validation": (24, 36), "test": (36, 48)}


def load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    hours = df.Time / 3600
    return {name: df[(hours >= start) & (hours < end)] for name, (start, end) in WINDOWS.items()}
