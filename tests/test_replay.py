import asyncio

import httpx
import numpy as np
import pandas as pd
import pytest

import replay
import replay_report
from payguard.fraud import api
from payguard.fraud.data import FEATURES, LABEL
from payguard.fraud.models import hgb


def test_schedule_spreads_each_second_and_compresses_by_the_speed_up():
    # Two transactions share second 10, so the second one goes half a second later; then everything halves.
    times = pd.Series([10, 10, 11, 13])
    assert replay.schedule(times, speed=2).tolist() == [0.0, 0.25, 0.5, 1.5]


def test_select_keeps_the_half_open_slice_in_time_order():
    test = pd.DataFrame({"Time": [3000, 60, 600, 0, 599]})
    assert replay.select(test, start_s=0, length_min=10).Time.tolist() == [0, 60, 599]


@pytest.mark.parametrize("text", ["42:75", "42:-5", "4240"])
def test_start_time_refuses_invalid_minutes(text):
    with pytest.raises(ValueError):
        replay.seconds(text)


@pytest.fixture(scope="module")
def scorer(raw) -> api.Scorer:
    model = hgb().fit(raw, raw[LABEL])
    threshold = float(np.sort(model.predict_proba(raw)[:, 1])[len(raw) // 2])
    return api.Scorer(model, threshold, run_id="test-run")


def test_replay_through_the_api_matches_the_model_offline(raw, scorer, monkeypatch):
    # The ASGI transport calls the real app in-process; it skips start-up, so the scorer is set directly.
    monkeypatch.setattr(api.app.state, "scorer", scorer, raising=False)
    out = replay.Results.empty(len(raw))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as c:
            await replay.replay(c, raw[FEATURES].to_dict("records"), replay.schedule(raw.Time, 1e9), out)

    asyncio.run(run())
    offline = scorer.model.predict_proba(raw)[:, 1]
    assert replay_report.parity(out, offline, scorer.threshold) == {"max_diff": 0.0, "mismatches": 0}
    assert not np.isnan(out.latency_ms).any() and not np.isnan(out.lag_ms).any()
    c = replay_report.counts(raw[LABEL].to_numpy(), out.score, scorer.threshold)
    assert c["caught"] + c["missed"] == raw[LABEL].sum() and c["alerts"] == (offline >= scorer.threshold).sum()
