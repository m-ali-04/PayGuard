"""The replay's live terminal panel: what the API has decided so far, and how fast it answered.

rich calls LivePanel.__rich__ on every refresh, so the panel is redrawn from the replay's result arrays as
they fill; it keeps no state of its own besides the start time.
"""
import time
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from rich.console import Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from payguard.fraud.data import LABEL
from payguard.fraud.evaluation import LATENCY_LIMIT_MS, latency_summary

if TYPE_CHECKING:
    from replay import Results

BIN_MIN = 5  # alerts are counted per 5 data minutes
FEED_ROWS = 8


def clock(seconds: float) -> str:
    """Data time as H:MM:SS since the file's first transaction."""
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def hh_mm(seconds: float) -> str:
    """Data time as H:MM, with :SS only when the seconds aren't zero."""
    text = clock(seconds)
    return text[:-3] if text.endswith(":00") else text


def bin_start(t: np.ndarray) -> np.ndarray:
    """Start of each transaction's BIN_MIN-minute bin on the data clock (shared with the report)."""
    return t - t % (BIN_MIN * 60)


def mm_ss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


class LivePanel:
    def __init__(self, data: pd.DataFrame, out: "Results", title: str, duration_s: float) -> None:
        self.time = data.Time.to_numpy()
        self.fraud = data[LABEL].to_numpy() == 1
        self.amount = data.Amount.to_numpy()
        self.out, self.title, self.duration_s = out, title, duration_s
        self.started = time.perf_counter()

    def __rich__(self) -> Panel:
        sent = ~np.isnan(self.out.lag_ms)
        answered = ~np.isnan(self.out.latency_ms)
        return Panel(Group(self._progress(sent), "", self._outcomes(answered), "", self._latency(sent, answered),
                           "", self._per_bin(answered), "", self._feed(answered)),
                     title=self.title, title_align="left")

    def _progress(self, sent: np.ndarray) -> Group:
        n_sent = int(sent.sum())
        data_now = self.time[sent].max() if n_sent else self.time[0]
        line = Text.assemble(("Data clock ", "dim"), (clock(data_now), "bold"),
                             (f"   {n_sent:,} / {len(sent):,} sent   ", ""),
                             (f"elapsed {mm_ss(time.perf_counter() - self.started)} / {mm_ss(self.duration_s)}", "dim"))
        return Group(line, ProgressBar(total=len(sent), completed=n_sent))

    def _outcomes(self, answered: np.ndarray) -> Table:
        alert = self.out.alert & answered
        t = Table(box=None, pad_edge=False, padding=(0, 3))
        for name, style in [("Caught", "green"), ("False alerts", "yellow"), ("Missed", "red"),
                            ("Genuine passed", "dim")]:
            t.add_column(name, style=style, justify="right")
        t.add_row(str((alert & self.fraud).sum()), str((alert & ~self.fraud).sum()),
                  str((answered & ~alert & self.fraud).sum()), f"{(answered & ~alert & ~self.fraud).sum():,}")
        return t

    def _latency(self, sent: np.ndarray, answered: np.ndarray) -> Table:
        t = Table(title=f"Latency, ms (limit p99 ≤ {LATENCY_LIMIT_MS})", title_justify="left", box=None,
                  pad_edge=False, padding=(0, 2))
        for name in ["Answered", "Mean", "p50", "p95", "p99", "Max", f"> {LATENCY_LIMIT_MS} ms", "In flight",
                     "Max send lag"]:
            t.add_column(name, justify="right")
        if not answered.any():
            t.add_row("0", *["–"] * 6, str(int(sent.sum())), "–")
            return t
        s = latency_summary(self.out.latency_ms[answered])
        p99_style = "bold green" if s["p99"] <= LATENCY_LIMIT_MS else "bold red"
        t.add_row(f"{answered.sum():,}", f"{s['mean']:.1f}", f"{s['p50']:.1f}", f"{s['p95']:.1f}",
                  Text(f"{s['p99']:.1f}", style=p99_style), f"{s['max']:.1f}", f"{s['over_limit']:.2%}",
                  str(int(sent.sum() - answered.sum())), f"{np.nanmax(self.out.lag_ms):.1f}")
        return t

    def _per_bin(self, answered: np.ndarray) -> Group:
        """Alerts and missed frauds per BIN_MIN data minutes, one character each, so the fraud bursts stand out."""
        key = Text.assemble(f"Per {BIN_MIN} data minutes   ", ("█ caught  ", "green"), ("█ false alert  ", "yellow"),
                            ("· missed", "red"))
        t = Table(box=None, show_header=False, pad_edge=False)
        alert = self.out.alert & answered
        missed = answered & ~alert & self.fraud
        bins = bin_start(self.time)
        # Every bin is drawn from the start, so the chart's rows don't shift as the replay fills them.
        for start in np.arange(bins[0], bins[-1] + 1, BIN_MIN * 60):
            rows = bins == start
            c, f, m = ((alert & self.fraud)[rows].sum(), (alert & ~self.fraud)[rows].sum(), missed[rows].sum())
            t.add_row(Text(hh_mm(start), style="dim"),
                      Text.assemble(("█" * c, "green"), ("█" * f, "yellow"), ("·" * m, "red")))
        return Group(key, t)

    def _feed(self, answered: np.ndarray) -> Table:
        """The latest alerts and missed frauds, newest first."""
        alert = self.out.alert & answered
        events = np.flatnonzero(alert | (answered & self.fraud))[-FEED_ROWS:][::-1]
        t = Table(title="Latest alerts and missed frauds", title_justify="left", box=None, pad_edge=False,
                  padding=(0, 2))
        for name in ["Data time", "Score", "Amount", "Outcome"]:
            t.add_column(name, justify="right" if name in ("Score", "Amount") else "left")
        for i in events:
            outcome = (("caught", "green") if alert[i] and self.fraud[i] else
                       ("false alert", "yellow") if alert[i] else ("missed", "red"))
            t.add_row(clock(self.time[i]), f"{self.out.score[i]:.3f}", f"{self.amount[i]:,.2f}", Text(*outcome))
        return t
