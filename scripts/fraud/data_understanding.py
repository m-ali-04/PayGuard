"""Profile the client's transactions and write reports/fraud/data_understanding.md with figures.

Usage: uv run --group analysis scripts/fraud/data_understanding.py
Look-only: nothing in the data is changed. Each section names the decision it feeds.
"""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from get_data import DEST, SHA256, is_valid

REPORT = Path(__file__).resolve().parents[2] / "reports" / "fraud" / "data_understanding.md"
FIGURES = REPORT.parent / "figures"
DAY = 86_400
# KS reporting cut-offs chosen for this report, not industry standards.
DRIFT_KS, STRONG_KS, WEAK_KS = 0.2, 0.7, 0.2


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Time is seconds since the file's first transaction, so hours are offsets, not clock time.
    df["hour"] = (df.Time // 3600).astype(int)
    df["day"] = np.where(df.Time < DAY, 1, 2)
    return df


def features(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("V")] + ["Amount"]


def ks(a: pd.Series, b: pd.Series) -> float:
    """Two-sample Kolmogorov-Smirnov statistic: 0 = same distribution, 1 = no overlap."""
    a, b = np.sort(a), np.sort(b)
    x = np.concatenate([a, b])
    return float(np.abs(np.searchsorted(a, x, "right") / len(a) - np.searchsorted(b, x, "right") / len(b)).max())


def save(fig: plt.Figure, name: str) -> str:
    fig.tight_layout()
    fig.savefig(FIGURES / name, dpi=120)
    plt.close(fig)
    return f"![{name}](figures/{name})"


def fraud_over_time(df: pd.DataFrame) -> tuple[str, str]:
    hourly = df.groupby("hour").Class.agg(n="size", fraud="sum")
    days = df.groupby("day").Class.agg(n="size", fraud="sum", rate="mean")
    quiet = hourly.n < hourly.n.median() / 2
    quiet_rate = hourly[quiet].fraud.sum() / hourly[quiet].n.sum()
    busy_rate = hourly[~quiet].fraud.sum() / hourly[~quiet].n.sum()

    fig, (top, bottom) = plt.subplots(2, 1, sharex=True, figsize=(9, 5))
    top.bar(hourly.index, hourly.n, color="tab:blue")
    top.set_ylabel("transactions")
    bottom.bar(hourly.index, hourly.fraud, color="tab:red")
    bottom.set_ylabel("frauds")
    bottom.set_xlabel("hours since first transaction")
    for ax in (top, bottom):
        ax.axvline(23.5, color="grey", linestyle="--")
    figure = save(fig, "fraud_by_hour.png")

    d1, d2 = days.loc[1], days.loc[2]
    summary = (f"Day 2 holds **{d2.fraud:.0f} frauds** ({d2.rate:.3%}) against {d1.fraud:.0f} ({d1.rate:.3%}) on day 1, "
               f"so a day-2 test set has about {d2.fraud:.0f} positives. In the {quiet.sum()} quietest hours "
               f"fraud runs at **{quiet_rate / busy_rate:.1f}x** the rate of busier hours.")
    body = f"""## 1. Fraud over time
{figure}

| Day | Transactions | Frauds | Fraud rate |
|---|---|---|---|
| 1 | {d1.n:,.0f} | {d1.fraud:.0f} | {d1.rate:.3%} |
| 2 | {d2.n:,.0f} | {d2.fraud:.0f} | {d2.rate:.3%} |

Volume follows a daily cycle with two quiet stretches. Fraud does not follow volume: in the {quiet.sum()} hours with under
half the median hourly volume, the fraud rate is {quiet_rate:.3%} against {busy_rate:.3%} elsewhere. With about
{d2.fraud:.0f} frauds on day 2, each caught fraud is worth {1 / d2.fraud:.1%} of recall, so model differences of a
few frauds are within noise.

**Feeds:** evaluation framework (split design, test-set size, whether confidence intervals are needed).
"""
    return summary, body


def duplicates(df: pd.DataFrame) -> tuple[str, str]:
    cols = features(df) + ["Time"]
    copies = df.duplicated(cols)
    conflicts = int(df.groupby(cols).Class.nunique().gt(1).sum())
    repeats = int(df.duplicated(features(df)).sum() - copies.sum())

    summary = (f"**{copies.sum():,} exact duplicate rows** ({df[copies].Class.sum()} of them fraud), none with conflicting "
               f"labels. A further {repeats:,} rows repeat another transaction's values at a different second.")
    body = f"""## 2. Duplicates
| | Rows |
|---|---|
| Extra copies of an identical row (same second) | {copies.sum():,} |
| ...of which fraud | {df[copies].Class.sum()} |
| Identical rows with different labels | {conflicts} |
| Same values as another row, different second | {repeats:,} |

Exact copies share the same second, so they always fall on the same side of a time split and cannot leak between train
and test. They still weight those transactions more in training and evaluation. The repeats at different seconds may be
recurring payments or retries, which are genuine live events, so removing them would train on data unlike production.

**Feeds:** evaluation framework (duplicate policy, decided together with the split).
"""
    return summary, body


def drift(df: pd.DataFrame) -> tuple[str, str]:
    genuine = df[df.Class == 0]
    scores = pd.Series({f: ks(genuine[genuine.day == 1][f], genuine[genuine.day == 2][f]) for f in features(df)})
    scores = scores.sort_values(ascending=False)
    shifted = scores[scores > DRIFT_KS]

    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.bar(scores.index, scores.values, color="tab:purple")
    ax.axhline(DRIFT_KS, color="grey", linestyle="--")
    ax.set_ylabel("KS, day 1 vs day 2")
    ax.tick_params(axis="x", rotation=90)
    figure = save(fig, "drift_by_feature.png")

    summary = (f"**{len(shifted)} features shift between the two days** among genuine transactions alone "
               f"(largest: {scores.index[0]}, KS {scores.iloc[0]:.2f}), so a time split tests something a random split hides.")
    body = f"""## 3. Drift between day 1 and day 2
{figure}

KS statistic per feature, comparing day 1 with day 2 for genuine transactions only, so a change in fraud share can't
cause it (0 = same distribution, 1 = no overlap). {len(shifted)} features are above {DRIFT_KS}: {", ".join(shifted.index)}.
A model trained on day 1 meets a slightly different population on day 2, as it would in production. A random split mixes
both days into training and would overstate live performance.

**Feeds:** evaluation framework (time split over random split).
"""
    return summary, body


def separation(df: pd.DataFrame) -> tuple[str, str]:
    fraud, genuine = df[df.Class == 1], df[df.Class == 0]
    scores = pd.Series({f: ks(genuine[f], fraud[f]) for f in features(df)}).sort_values(ascending=False)
    strong = scores[scores > STRONG_KS]

    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.bar(scores.index, scores.values, color="tab:green")
    ax.set_ylabel("KS, fraud vs genuine")
    ax.tick_params(axis="x", rotation=90)
    figure = save(fig, "separation_by_feature.png")

    summary = (f"**{len(strong)} features each separate fraud strongly on their own** (KS above {STRONG_KS}, led by "
               f"{', '.join(strong.index[:3])}).")
    body = f"""## 4. Which features separate fraud
{figure}

KS statistic per feature, comparing fraud with genuine transactions. {len(strong)} features are above {STRONG_KS}
({", ".join(strong.index)}), and {(scores < WEAK_KS).sum()} are below {WEAK_KS}. Strong single-feature signals mean a simple model
is a credible baseline, and any more complex model has to show it gains beyond them. This is a one-feature-at-a-time
view: it doesn't show how features combine.

**Feeds:** model shortlist (strength of the simple baseline).
"""
    return summary, body


def amount(df: pd.DataFrame) -> tuple[str, str]:
    by_class = df.groupby("Class").Amount
    quantiles = by_class.quantile([0.25, 0.5, 0.75, 0.99]).unstack()
    small = by_class.apply(lambda a: (a <= 1).mean())
    zeros = by_class.apply(lambda a: (a == 0).sum())

    fig, ax = plt.subplots(figsize=(9, 3.5))
    bins = np.geomspace(0.01, df.Amount.max(), 60)
    # Share per bin, not density: density divides by bin width, which log bins make tiny at the low end.
    for cls, label, color in ((0, "genuine", "tab:blue"), (1, "fraud", "tab:red")):
        amounts = df[df.Class == cls].Amount.clip(lower=0.01)
        ax.hist(amounts, bins=bins, weights=np.full(len(amounts), 1 / len(amounts)), alpha=0.5, label=label, color=color)
    ax.set_xscale("log")
    ax.set_xlabel("amount (zero shown at 0.01)")
    ax.set_ylabel("share of class")
    ax.legend()
    figure = save(fig, "amount_by_class.png")

    rows = "\n".join(
        f"| {name} | " + " | ".join(f"{v:,.2f}" for v in quantiles.loc[c]) + f" | {small[c]:.1%} | {zeros[c]:,} |"
        for c, name in ((0, "Genuine"), (1, "Fraud"))
    )
    summary = (f"**{small[1]:.0%} of frauds are for 1.00 or less**, against {small[0]:.0%} of genuine transactions, "
               f"yet fraud's 75th-99th percentiles are higher. Amount alone separates weakly.")
    body = f"""## 5. Amount
{figure}

| | 25% | Median | 75% | 99% | ≤ 1.00 | Zero |
|---|---|---|---|---|---|---|
{rows}

Fraud splits into many very small charges and higher 75th-99th percentiles than genuine transactions, so the median alone
(lower for fraud) is misleading. Amount is unscaled and spans several orders of magnitude, so models sensitive to scale
need a log or similar transform, in the shared preprocessing path. Amount is the only field that could cost a missed
fraud in money.

**Feeds:** preprocessing (scaling), evaluation framework (whether evaluation can be weighted by amount).
"""
    return summary, body


def main() -> int:
    if not is_valid(DEST):
        print(f"No verified dataset at {DEST}. Run: uv run scripts/fraud/get_data.py", file=sys.stderr)
        return 1
    FIGURES.mkdir(parents=True, exist_ok=True)
    df = load(DEST)
    sections = [check(df) for check in (fraud_over_time, duplicates, drift, separation, amount)]

    header = f"""# Data Understanding: Client Card Transactions
Generated by `scripts/fraud/data_understanding.py`. Data SHA-256 `{SHA256[:8]}…{SHA256[-3:]}`.
{len(df):,} transactions over {df.Time.max() / 3600:.0f} hours, {df.Class.sum()} frauds ({df.Class.mean():.3%}).

## Summary
"""
    summary = "\n".join(f"- {s}" for s, _ in sections)
    REPORT.write_text(header + summary + "\n\n" + "\n".join(b for _, b in sections), encoding="utf-8")
    print(f"Wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
