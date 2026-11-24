"""Scoring rules for the decision report, shared with the API (which reuses the live threshold).
Inputs are arrays: y holds 0/1 labels, scores hold fraud probabilities, both in the same order."""
from collections.abc import Callable

import numpy as np

# Sample figure chosen by the owner, not client-provided: just above the 0.173% fraud rate, so the
# budget doesn't cap recall on its own. See CONTEXT.md "Evaluation Framework".
BUDGET = 0.002


def alerts(n: int) -> int:
    """How many transactions the budget lets us flag out of n."""
    return max(1, round(BUDGET * n))


def _outcome(y: np.ndarray, flagged: np.ndarray) -> dict:
    caught = int(y[flagged].sum())
    n_alerts = int(flagged.sum())
    return {
        "alerts": n_alerts,
        "caught": caught,
        "precision": caught / n_alerts if n_alerts else 0.0,
        "recall": caught / int(y.sum()),
    }


def at_budget(y: np.ndarray, scores: np.ndarray) -> dict:
    """Offline view: flag exactly the top-k scores. Tied scores at the cut are split by position
    (stable sort), so k is exact; the live threshold below flags all ties instead."""
    flagged = np.zeros(len(scores), dtype=bool)
    flagged[np.argsort(-scores, kind="stable")[: alerts(len(scores))]] = True
    return _outcome(y, flagged)


def threshold_for_budget(scores: np.ndarray) -> float:
    """The live cut: the k-th highest score in a window (validation), fixed before live traffic."""
    return float(np.sort(scores)[-alerts(len(scores))])


def at_threshold(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    """Live view: flag every score at or above a cut set in advance, so the alert count can drift."""
    flagged = scores >= threshold
    return {**_outcome(y, flagged), "alert_rate": flagged.mean()}


def paired_bootstrap(
    y: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    metric: Callable[[np.ndarray, np.ndarray], float],
    n: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """95% range of metric(b) - metric(a). Both models are scored on the same resampled rows, so
    the range reflects the gap between them rather than how hard each resample happens to be."""
    rng = np.random.default_rng(seed)
    diffs = np.empty(n)
    for i in range(n):
        rows = rng.integers(0, len(y), len(y))
        diffs[i] = metric(y[rows], b[rows]) - metric(y[rows], a[rows])
    low, high = np.percentile(diffs, [2.5, 97.5])
    return float(low), float(high)
