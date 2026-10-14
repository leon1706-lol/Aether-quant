"""evaluation/gate_audit.py (V5.8.0, todo lead 1): the rolling-IC gate against the IC it estimates."""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.gate_audit import audit_rolling_ic_gate, daily_rank_ic, resolved_trailing_ic
from evaluation.live_parity import make_rolling_ic_gate_fn
from evaluation.rolling_ic_gate_calibration import build_event_buffer
from evaluation.rolling_ic_series import make_rolling_ic_state_fn


def _signal_frame(true_ic: float, days: int = 260, names: int = 100, seed: int = 11) -> pd.DataFrame:
    """Daily closes whose 20-session forward return is correlated `true_ic` with a score known on the origin date."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=days + 25)
    rows = []
    for name in range(names):
        closes = [100.0]
        for _ in range(len(dates) - 1):
            closes.append(closes[-1] * np.exp(rng.normal(0, 0.01)))
        closes = np.array(closes)
        for index, date in enumerate(dates[:days]):
            forward = np.log(closes[index + 20] / closes[index])
            score = true_ic * forward / 0.045 + np.sqrt(max(1 - true_ic**2, 0.0)) * rng.normal()
            rows.append({"date": date.strftime("%Y-%m-%d"), "ticker": f"T{name}", "close": closes[index], "score": score,
                         "forward": forward})
    frame = pd.DataFrame(rows)
    frame["target_rank"] = frame.groupby("date")["forward"].rank(pct=True)
    return frame


def test_resolved_trailing_ic_only_uses_origins_whose_horizon_elapsed():
    dates = [f"d{i:02d}" for i in range(10)]
    daily = {date: float(index) for index, date in enumerate(dates)}
    trailing = resolved_trailing_ic(daily, dates, horizon=3, window=2)
    assert trailing["d02"] is None  # nothing resolved yet
    assert trailing["d05"] == 0.5  # origins d00, d01 (d01 + 3 < d05)
    assert trailing["d09"] == 4.5  # origins d04, d05


def test_a_constant_positive_signal_is_rarely_vetoed_by_the_live_gate():
    """Self-check from the V5.8.0 plan: true IC +0.05, floor 0.0 - the gate must veto well under half the rebalances."""
    frame = _signal_frame(0.05)
    config = {"enabled": True, "horizon_days": 20, "rolling_window_days": 80, "min_resolved_dates_required": 20,
              "min_rolling_mean_ic": 0.0, "min_names_per_date": 10}
    events = build_event_buffer(frame, raw_score_column="score")
    state_fn = make_rolling_ic_state_fn(events, horizon_days=20, rolling_window_days=80, min_names_per_date=10)
    gate_fn = make_rolling_ic_gate_fn(frame, raw_score_column="score", gate_config=config, state_fn=state_fn)
    daily = daily_rank_ic(frame, score_column="score", target_column="target_rank")
    dates = sorted(frame["date"].unique())
    report = audit_rolling_ic_gate(
        decision_dates=dates[100:], gate_fn=gate_fn, state_fn=state_fn, daily_ic=daily, trading_dates=dates,
        horizon=20, window=80,
    )
    assert 0.02 < report["mean_forward_ic_all"] < 0.12
    assert report["veto_share"] < 0.5
    assert report["state_vs_resolved_correlation"] is None or report["state_vs_resolved_correlation"] > 0


def test_false_vetoes_are_counted_against_the_forward_ic():
    def gate_fn(date):
        return {"engaged": date != "d1", "reason": "rolling_ic_below_floor" if date == "d1" else "ok"}

    report = audit_rolling_ic_gate(
        decision_dates=["d0", "d1"], gate_fn=gate_fn, state_fn=lambda date: {"rolling_mean_ic": 0.0},
        daily_ic={"d0": 0.1, "d1": 0.2}, trading_dates=["d0", "d1"], horizon=1, window=1,
    )
    assert report["num_vetoed"] == 1 and report["num_false_vetoes"] == 1 and report["false_veto_share_of_vetoes"] == 1.0
