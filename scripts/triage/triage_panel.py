"""The triage run's live terminal panel: what the model has decided so far, and how it compares with gold.

rich calls TriagePanel.__rich__ on every refresh, so the panel is redrawn from the runner's list of rows
as it fills; it keeps no state of its own besides the start time and the gold labels.
"""
import time

import numpy as np
import pandas as pd
from rich.console import Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from payguard.triage.evaluation import gold_reasons
from payguard.triage.taxonomy import Flag

FEED_ROWS = 8


def mm_ss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def counts(header: list[tuple[str, str]], values: list, title: str | None = None) -> Table:
    t = Table(title=title, title_justify="left", box=None, pad_edge=False, padding=(0, 3))
    for name, style in header:
        t.add_column(name, style=style, justify="right")
    t.add_row(*map(str, values))
    return t


class TriagePanel:
    def __init__(self, rows: list[dict], total: int, gold: pd.DataFrame, title: str) -> None:
        self.rows, self.total, self.title = rows, total, title
        self.gold = {g["complaint_id"]: (g, gold_reasons(g["narrative"], g["tags"], g)) for g in gold.to_dict("records")}
        self.started = time.perf_counter()

    def __rich__(self) -> Panel:
        return Panel(Group(self._progress(), "", self._routing(), "", self._against_gold(), "", self._speed(), "",
                           self._feed()), title=self.title, title_align="left")

    def _progress(self) -> Group:
        line = Text.assemble((f"{len(self.rows)} / {self.total} triaged   ", "bold"),
                             (f"elapsed {mm_ss(time.perf_counter() - self.started)}", "dim"))
        return Group(line, ProgressBar(total=self.total, completed=len(self.rows)))

    def _routing(self) -> Table:
        return counts([("Routed automatically", "green"), ("To a human", "yellow"), ("Failed calls", "red"),
                       ("Re-asks", "dim")],
                      [sum(r["requires_human"] == "n" for r in self.rows), sum(r["requires_human"] == "y" for r in self.rows),
                       sum(r["error"] != "" for r in self.rows), sum(r["attempts"] != "" and r["attempts"] > 1 for r in self.rows)])

    def _missed(self, row: dict) -> bool:
        """Gold says a human is needed, but the pipeline would route it automatically."""
        return bool(self.gold[row["complaint_id"]][1]) and row["requires_human"] == "n"

    def _against_gold(self) -> Table:
        graded = [r for r in self.rows if r["complaint_id"] in self.gold]
        label = lambda r, column: self.gold[r["complaint_id"]][0][column]
        return counts([("Category right", "green"), ("Urgency right", "green"), ("Sensitive missed", "bold red")],
                      [sum(r["category"] == label(r, "category") for r in graded),
                       sum(r["urgency"] == label(r, "urgency") for r in graded), sum(self._missed(r) for r in graded)],
                      title=f"Against gold ({len(graded)} labelled)")

    def _speed(self) -> Table:
        called = [r for r in self.rows if r["attempts"] != ""]
        t = Table(box=None, pad_edge=False, padding=(0, 2))
        for name in ["Per complaint", "Mean", "p95", "Max", "Tokens in / out (mean)"]:
            t.add_column(name, justify="left" if name == "Per complaint" else "right")
        if not called:
            t.add_row("Latency, s", "–", "–", "–", "–")
            return t
        latency = np.array([r["latency_s"] for r in called])
        tokens = f"{np.mean([r['prompt_tokens'] for r in called]):,.0f} / {np.mean([r['output_tokens'] for r in called]):,.0f}"
        t.add_row("Latency, s", f"{latency.mean():.1f}", f"{np.percentile(latency, 95):.1f}", f"{latency.max():.1f}", tokens)
        return t

    def _verdict(self, row: dict) -> Text:
        if row["attempts"] == "":
            return Text("skipped (too short)", style="dim")
        if row["error"]:
            return Text(f"failed: {row['error']}", style="red")
        if row["complaint_id"] not in self.gold:
            return Text("")
        if self._missed(row):
            return Text("✗ MISSED sensitive", style="bold red")
        g = self.gold[row["complaint_id"]][0]
        cat, urg = row["category"] == g["category"], row["urgency"] == g["urgency"]
        return Text(f"{'✓' if cat else '✗'} cat {'✓' if urg else '✗'} urg", style="green" if cat and urg else "yellow")

    def _feed(self) -> Table:
        t = Table(title="Latest complaints (newest first)", title_justify="left", box=None, pad_edge=False, padding=(0, 2))
        for name in ["ID", "Category", "Urgency", "Flags", "Route", "vs gold"]:
            t.add_column(name)
        for r in self.rows[-FEED_ROWS:][::-1]:
            flags = ", ".join(flag.split("_")[0] for flag in Flag if r[flag] == "y") or "–"
            route = Text("human", style="yellow") if r["requires_human"] == "y" else Text("auto", style="green")
            t.add_row(r["complaint_id"], r["category"] or "–", r["urgency"] or "–", flags, route, self._verdict(r))
        return t
