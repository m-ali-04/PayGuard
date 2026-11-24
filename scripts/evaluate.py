"""Score the latest logged run of each shortlisted model and write reports/decision_report.md.

Usage: uv run scripts/evaluate.py   (after scripts/train.py)
The report's contents were fixed before any model was compared; see CONTEXT.md "Evaluation
Framework". Headline metrics are also logged to each model's training run in MLflow.
"""
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

import mlflow
import mlflow.artifacts
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from get_data import DEST, SHA256, is_valid
from payguard.fraud.data import FEATURES, LABEL, WINDOWS, load, split
from payguard.fraud.evaluation import (
    BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, BUDGET, alerts, at_budget, at_threshold, paired_bootstrap,
    threshold_for_budget,
)
from payguard.fraud.models import CANDIDATES
from train import EXPERIMENT, ROOT, use_local_store

REPORT = ROOT / "reports" / "decision_report.md"
LATENCY_LIMIT_MS = 50
LATENCY_CALLS, WARMUP_CALLS = 2000, 50
BASELINE = next(iter(CANDIDATES))  # the simpler model every other candidate is compared against
# Each note reads its size from the fitted classifier, so it can't go stale if settings change.
NOTES = {
    "logreg": lambda clf: f"{clf.coef_.size} weights plus an intercept. Each score is a weighted sum, so a "
                          "decision can be read off the weights, though the fields are anonymised PCA components.",
    "hgb": lambda clf: f"{clf.n_iter_} trees (early stopping off). Non-linear; explaining a single decision "
                       "needs a tool such as SHAP.",
}


def latest_run(name: str) -> pd.Series:
    runs = mlflow.search_runs(
        experiment_names=[EXPERIMENT],
        filter_string=f"params.candidate = '{name}' and attributes.status = 'FINISHED'",
        order_by=["start_time DESC"],
        max_results=1,
    )
    if runs.empty:
        sys.exit(f"No finished '{name}' run in experiment '{EXPERIMENT}'. Run: uv run scripts/train.py")
    return runs.iloc[0]


def latest_runs() -> dict[str, str]:
    """Run ID of each candidate's latest run, refusing to mix training sessions: if train.py stopped
    partway, the newest runs would otherwise pair a fresh model with a stale one."""
    runs = {name: latest_run(name) for name in CANDIDATES}
    sessions = {name: run.get("params.session") for name, run in runs.items()}
    if None in sessions.values() or len(set(sessions.values())) > 1:
        sys.exit(f"The latest runs come from different training sessions {sessions}. "
                 "Run: uv run scripts/train.py")
    return {name: run.run_id for name, run in runs.items()}


def load_model(run_id: str):
    """The fitted pipeline and the size of its saved file (one download, cleaned up after)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(mlflow.artifacts.download_artifacts(f"runs:/{run_id}/model", dst_path=tmp))
        return mlflow.sklearn.load_model(str(path)), (path / "model.skops").stat().st_size


def latency_ms(model, transactions: pd.DataFrame) -> tuple[float, float]:
    """p50 and p99 of scoring one transaction per call, model only. Rows are built beforehand so
    only predict_proba is timed; request parsing is measured with the API later."""
    rows = [transactions.iloc[[i]] for i in range(WARMUP_CALLS + LATENCY_CALLS)]
    for row in rows[:WARMUP_CALLS]:
        model.predict_proba(row)
    times = []
    for row in rows[WARMUP_CALLS:]:
        start = time.perf_counter()
        model.predict_proba(row)
        times.append((time.perf_counter() - start) * 1000)
    p50, p99 = np.percentile(times, [50, 99])
    return float(p50), float(p99)


def caught(y: np.ndarray, scores: np.ndarray) -> int:
    return at_budget(y, scores)["caught"]


def window_metrics(y: np.ndarray, scores: np.ndarray) -> dict:
    return {
        "ap": average_precision_score(y, scores),
        "roc_auc": roc_auc_score(y, scores),
        **at_budget(y, scores),
    }


def evaluate(run_id: str, windows: dict[str, pd.DataFrame]) -> dict:
    model, size = load_model(run_id)
    y = {w: windows[w][LABEL].to_numpy() for w in ("validation", "test")}
    scores = {w: model.predict_proba(windows[w][FEATURES])[:, 1] for w in ("validation", "test")}
    threshold = threshold_for_budget(scores["validation"])
    p50, p99 = latency_ms(model, windows["test"][FEATURES])
    return {
        "run_id": run_id,
        "size": size,
        "clf": model[-1],
        "scores": scores["test"],
        "val": window_metrics(y["validation"], scores["validation"]),
        "test": window_metrics(y["test"], scores["test"]),
        "live": at_threshold(y["test"], scores["test"], threshold),
        "threshold": threshold,
        "p50": p50,
        "p99": p99,
    }


def log_to_mlflow(r: dict) -> None:
    with mlflow.start_run(run_id=r["run_id"]):
        mlflow.log_metrics({
            "test_ap": r["test"]["ap"],
            "test_caught_at_budget": r["test"]["caught"],
            "test_roc_auc": r["test"]["roc_auc"],
            "val_ap": r["val"]["ap"],
            "p99_ms": r["p99"],
        })


def recommendation(results: dict[str, dict]) -> str:
    """The selection rule fixed before comparison: highest test AP, provided it catches no fewer
    frauds at the budget than any alternative. A disagreement is reported, not resolved here."""
    best = max(results, key=lambda n: results[n]["test"]["ap"])
    rivals = [n for n in results if results[n]["test"]["caught"] > results[best]["test"]["caught"]]
    if rivals:
        return (f"**No default.** `{best}` has the highest AP but catches fewer frauds at the budget than "
                f"{', '.join(f'`{n}`' for n in rivals)}. Reported as a finding; the owner decides.")
    return f"**`{best}`** by the selection rule (highest AP, not worse at the budget)."


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def pct(x: float) -> str:
    return f"{x:.1%}"


def signed_range(low: float, high: float, fmt: str) -> str:
    return f"[{low:+{fmt}}, {high:+{fmt}}]"


def comparison(results: dict[str, dict], y: np.ndarray) -> str:
    base = results[BASELINE]
    lines = []
    for name, r in results.items():
        if name == BASELINE:
            continue
        ap = paired_bootstrap(y, base["scores"], r["scores"], average_precision_score)
        n = paired_bootstrap(y, base["scores"], r["scores"], caught)
        lines.append(
            f"- **{name} − {BASELINE}:** AP {r['test']['ap'] - base['test']['ap']:+.3f} {signed_range(*ap, '.3f')}"
            f" · frauds caught {r['test']['caught'] - base['test']['caught']:+d} {signed_range(*n, '.0f')}"
        )
    return "\n".join(lines)


def write_report(results: dict[str, dict], windows: dict[str, pd.DataFrame]) -> None:
    test, val = windows["test"], windows["validation"]
    y = test[LABEL].to_numpy()
    frauds, k = int(y.sum()), alerts(len(test))
    start, end = WINDOWS["test"]
    runs = ", ".join(f"{n} `{r['run_id'][:8]}`" for n, r in results.items())
    sections = [
        "# Decision Report: Fraud Model Shortlist",
        f"Generated by `scripts/evaluate.py`. Runs: {runs}. Data SHA-256 `{SHA256[:8]}…{SHA256[-3:]}`.  \n"
        f"Test window {start}–{end}h: {len(test):,} transactions, {frauds} frauds. Alert budget {BUDGET:.1%} → "
        f"**{k} alerts in this window**: the daily budget scaled to the window's volume. Counts are per "
        "window, not scaled to a day.",

        "## Default recommendation",
        f"{recommendation(results)} Owner's decision and reason: see README \"Results\".",

        "## 1. Ranking quality and budget performance (test)",
        table(["Model", "AP", f"Frauds caught (of {frauds})", "Precision", "Recall", "ROC-AUC (ref.)"],
              [[n, f"{r['test']['ap']:.3f}", r["test"]["caught"], pct(r["test"]["precision"]),
                pct(r["test"]["recall"]), f"{r['test']['roc_auc']:.3f}"] for n, r in results.items()]),
        f"Paired bootstrap 95% range of the difference ({BOOTSTRAP_RESAMPLES:,} resamples of the test window, "
        f"seed {BOOTSTRAP_SEED}):\n\n"
        + comparison(results, y),

        "## 2. Operational view (threshold set on validation, applied to test)",
        table(["Model", "Threshold", f"Alert rate (budget {BUDGET:.1%})", "Alerts", "Caught", "Precision", "Recall"],
              [[n, f"{r['threshold']:.6f}", f"{r['live']['alert_rate']:.3%}", r["live"]["alerts"], r["live"]["caught"],
                pct(r["live"]["precision"]), pct(r["live"]["recall"])] for n, r in results.items()]),
        "The threshold is the score that flags the budget on validation, fixed in advance as it would be live. "
        "The alert rate on test shows how far that cut drifts from the budget.",

        "## 3. Validation beside test",
        table(["Model", "Window", "AP", "Caught / frauds (at budget)", "ROC-AUC"],
              [[n, w, f"{r[key]['ap']:.3f}", f"{r[key]['caught']} / {int(df[LABEL].sum())}", f"{r[key]['roc_auc']:.3f}"]
               for n, r in results.items() for w, key, df in (("validation", "val", val), ("test", "test", test))]),
        f"Validation ({WINDOWS['validation'][0]}–{WINDOWS['validation'][1]}h) covers the quiet night hours "
        f"(fraud {val[LABEL].mean():.2%}); test is daytime ({test[LABEL].mean():.2%}). A reading over two "
        "points in time, not a measurement of drift.",

        "## 4. Latency (model only, one transaction per call)",
        table(["Model", "p50 ms", "p99 ms", f"≤ {LATENCY_LIMIT_MS} ms"],
              [[n, f"{r['p50']:.2f}", f"{r['p99']:.2f}", "pass" if r["p99"] <= LATENCY_LIMIT_MS else "**fail**"]
               for n, r in results.items()]),
        f"{LATENCY_CALLS:,} calls after {WARMUP_CALLS} warm-up, on {platform.platform()}, {os.cpu_count()} logical "
        "cores. Depends on hardware. End-to-end API latency is measured in the API step.",

        "## 5. Complexity and explainability",
        table(["Model", "Saved model size", "Notes"],
              [[n, f"{r['size'] / 1024:,.0f} KB", NOTES[n](r["clf"])] for n, r in results.items()]),
    ]
    REPORT.write_text("\n\n".join(sections) + "\n")


def main() -> int:
    if not is_valid(DEST):
        print(f"No verified dataset at {DEST}. Run: uv run scripts/get_data.py", file=sys.stderr)
        return 1
    windows = split(load(DEST))
    use_local_store()
    results = {}
    for name, run_id in latest_runs().items():
        results[name] = evaluate(run_id, windows)
        log_to_mlflow(results[name])
        print(f"Evaluated {name} (run {results[name]['run_id'][:8]})")
    write_report(results, windows)
    print(f"Wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
