import numpy as np
import pytest
from sklearn.metrics import average_precision_score

from payguard.fraud.evaluation import (
    LATENCY_LIMIT_MS, alerts, at_budget, at_threshold, latency_summary, paired_bootstrap, threshold_for_budget,
)


@pytest.fixture
def window() -> tuple[np.ndarray, np.ndarray]:
    """2,000 transactions, so the 0.2% budget allows 4 alerts. The four top scores hold
    3 of the 5 frauds; the other two are scored low, so they're missed."""
    y = np.zeros(2000, dtype=int)
    scores = np.linspace(0, 0.5, 2000)
    top = [10, 20, 30, 40]
    scores[top] = [0.99, 0.98, 0.97, 0.96]
    y[[10, 20, 30, 1500, 1600]] = 1
    return y, scores


def test_budget_flags_top_k_and_counts_frauds(window):
    y, scores = window
    assert alerts(len(y)) == 4
    assert at_budget(y, scores) == {"alerts": 4, "caught": 3, "precision": 0.75, "recall": 0.6}


def test_threshold_from_one_window_flags_the_budget_on_it(window):
    y, scores = window
    live = at_threshold(y, scores, threshold_for_budget(scores))
    assert live["alerts"] == 4 and live["caught"] == 3 and live["alert_rate"] == 0.002


def test_threshold_flags_ties_that_top_k_splits():
    y = np.array([1, 0, 0, 0] + [0] * 996)
    scores = np.array([0.9, 0.9, 0.9, 0.1] + [0.0] * 996)  # 1,000 rows -> budget of 2 alerts
    assert at_budget(y, scores)["alerts"] == 2
    assert at_threshold(y, scores, threshold_for_budget(scores))["alerts"] == 3


def test_bootstrap_of_identical_models_is_zero(window):
    y, scores = window
    assert paired_bootstrap(y, scores, scores, average_precision_score, n=50) == (0.0, 0.0)


def test_bootstrap_is_reproducible_and_favours_the_better_model():
    rng = np.random.default_rng(1)
    y = (rng.random(5000) < 0.02).astype(int)
    noise = rng.normal(size=5000)
    weak, strong = y + 2 * noise, y + 0.3 * noise
    low, high = paired_bootstrap(y, weak, strong, average_precision_score, n=200)
    assert 0 < low < high
    assert paired_bootstrap(y, weak, strong, average_precision_score, n=200) == (low, high)
    assert paired_bootstrap(y, strong, weak, average_precision_score, n=200)[1] < 0


def test_latency_summary_counts_requests_over_the_limit():
    ms = np.arange(1, 101, dtype=float)  # 1..100 ms
    s = latency_summary(ms)
    assert (s["mean"], s["p50"], s["max"]) == (50.5, 50.5, 100.0)
    assert s["over_limit"] == (100 - LATENCY_LIMIT_MS) / 100  # strictly above the limit


def test_recall_is_undefined_without_frauds():
    out = at_threshold(np.zeros(5), np.array([0.1, 0.9, 0.2, 0.3, 0.4]), 0.5)
    assert out["alerts"] == 1 and out["caught"] == 0 and np.isnan(out["recall"])
