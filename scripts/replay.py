"""Replay a slice of the client's test window to the scoring API, in time order and condensed in time.

Start the API first: uv run uvicorn payguard.fraud.api:app
Usage: uv run scripts/replay.py                                      # demo: 42:40–43:20 at 4x (10 min)
       uv run scripts/replay.py --start 36:00 --length 720 --speed 60   # the whole test window
Only the model fields are sent; the label stays here and is joined to each answer afterwards.
"""
import argparse
import asyncio
import sys
import time
from dataclasses import dataclass

import httpx
import numpy as np
import pandas as pd
from rich.live import Live

from get_data import DEST, is_valid
from payguard.fraud.data import FEATURES, LABEL, WINDOWS, load, split
from payguard.fraud.evaluation import LATENCY_LIMIT_MS
from payguard.fraud.tracking import ROOT
import replay_report
from replay_panel import LivePanel, clock

START_API = "uv run uvicorn payguard.fraud.api:app"
# The 40 minutes of the test window with the most frauds (17), chosen by the owner for the demo. The pace is
# real time x4: a ~112 ms mean gap, and even the busiest second's transactions arrive ~23 ms apart, well above
# the ~10 ms a request takes, so requests don't overlap (load testing is out of scope).
DEMO_START, DEMO_LENGTH_MIN, DEMO_SPEED = "42:40", 40, 4


@dataclass
class Results:
    """One slot per transaction, filled by its request; arrays keep the summary maths vectorised."""
    score: np.ndarray
    alert: np.ndarray
    latency_ms: np.ndarray  # request sent → answer received, so it includes any queueing in the API
    lag_ms: np.ndarray  # actual − scheduled send time: shows whether this script kept to the schedule

    @classmethod
    def empty(cls, n: int) -> "Results":
        return cls(np.full(n, np.nan), np.zeros(n, dtype=bool), np.full(n, np.nan), np.full(n, np.nan))


def seconds(hh_mm: str) -> int:
    """'42:40' → seconds since the file's first transaction (the data's own clock)."""
    h, m = hh_mm.split(":")
    return int(h) * 3600 + int(m) * 60


def select(test: pd.DataFrame, start_s: int, length_min: float) -> pd.DataFrame:
    end_s = start_s + length_min * 60
    return test[(test.Time >= start_s) & (test.Time < end_s)].sort_values("Time", kind="stable")


def schedule(times: pd.Series, speed: float) -> np.ndarray:
    """Send time of each transaction, in seconds from the replay's start. Time is in whole seconds, so the
    k transactions of one second are spread across it at i/k: sending them as one burst would be an
    artefact of the timestamp resolution, and would inflate the latency of the last one served."""
    by_second = times.groupby(times)
    spread = by_second.cumcount() / by_second.transform("size")
    return ((times - times.iloc[0] + spread) / speed).to_numpy()


async def score(client: httpx.AsyncClient, i: int, row: dict, due: float, t0: float, out: Results) -> None:
    sent = time.perf_counter()
    out.lag_ms[i] = (sent - t0 - due) * 1000  # set before the answer, so the panel can count requests in flight
    response = await client.post("/v1/score", json=row)
    out.latency_ms[i] = (time.perf_counter() - sent) * 1000
    response.raise_for_status()
    body = response.json()
    out.score[i], out.alert[i] = body["fraud_score"], body["alert"]


async def replay(client: httpx.AsyncClient, rows: list[dict], due: np.ndarray, out: Results) -> None:
    """Fills out as answers arrive. Open loop: each request goes out at its scheduled time without waiting for
    earlier answers, the way live traffic arrives, so a slow answer queues the ones behind it as it would live."""
    async with asyncio.TaskGroup() as tasks:
        t0 = time.perf_counter()
        for i, (row, d) in enumerate(zip(rows, due)):
            await asyncio.sleep(max(0.0, t0 + d - time.perf_counter()))
            tasks.create_task(score(client, i, row, d, t0, out))


async def run(url: str, rows: list[dict], due: np.ndarray, out: Results) -> None:
    # Pool sized above any overlap we expect, so a request never waits for a free connection here,
    # which would count our client's queue as API latency.
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
    async with httpx.AsyncClient(base_url=url, limits=limits) as client:
        await replay(client, rows, due, out)


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", default=DEMO_START, help=f"data time H:MM where the slice starts (default {DEMO_START})")
    p.add_argument("--length", type=float, default=DEMO_LENGTH_MIN,
                   help=f"slice length in data minutes (default {DEMO_LENGTH_MIN})")
    p.add_argument("--speed", type=float, default=DEMO_SPEED, help=f"speed-up over real time (default {DEMO_SPEED})")
    p.add_argument("--url", default="http://127.0.0.1:8000", help="scoring API base URL")
    a = p.parse_args()
    try:
        a.start_s = seconds(a.start)
    except ValueError:
        p.error(f"--start must be H:MM, got {a.start!r}")
    first, last = (h * 3600 for h in WINDOWS["test"])
    if not (first <= a.start_s and a.start_s + a.length * 60 <= last and a.length > 0 and a.speed > 0):
        p.error(f"the slice must lie inside the test window ({WINDOWS['test'][0]}:00–{WINDOWS['test'][1]}:00), "
                "with a positive length and speed")
    return a


def main() -> int:
    a = args()
    if not is_valid(DEST):
        sys.exit(f"No verified dataset at {DEST}. Run: uv run scripts/get_data.py")
    test = split(load(DEST))["test"]
    data = select(test, a.start_s, a.length)
    try:
        health = httpx.get(f"{a.url}/v1/health", timeout=5).raise_for_status().json()
    except httpx.HTTPError as e:
        sys.exit(f"Can't reach the scoring API at {a.url} ({e}). Start it: {START_API}")

    end = clock(a.start_s + a.length * 60)[:-3]
    slice_desc = (f"Slice {a.start}–{end} ({a.length:g} data minutes, {len(data):,} transactions, "
                  f"{int(data[LABEL].sum())} frauds) at {a.speed:g}x")
    title = (f"PayGuard replay · {a.start}–{end} at {a.speed:g}x · {health['model']} run "
             f"{health['model_run_id'][:8]} · threshold {health['threshold']:.6f}")
    out = Results.empty(len(data))
    started = time.perf_counter()
    try:
        # Live redraws the panel from its own thread while the event loop fills out.
        with Live(LivePanel(data, out, title, a.length * 60 / a.speed), refresh_per_second=4):
            asyncio.run(run(a.url, data[FEATURES].to_dict("records"), schedule(data.Time, a.speed), out))
    except* httpx.HTTPError as group:
        sys.exit(f"Replay stopped: {group.exceptions[0]!r}")
    elapsed = time.perf_counter() - started

    print("Checking parity against the offline model…")
    r = replay_report.write(data, test, out, health["model_run_id"], health["threshold"], slice_desc, elapsed)
    print(f"Caught {r['caught']} · false alerts {r['false alerts']} · missed {r['missed']} (of {r['frauds']} frauds) · "
          f"p99 {r['p99']:.1f} ms (limit {LATENCY_LIMIT_MS}) · parity: largest difference {r['max_diff']:.3g}, "
          f"{r['mismatches']} decisions differ")
    print(f"Wrote {replay_report.REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
