"""V6.2.0 round file (todo lead 1, rule R-DEDUPE): one switch for how live counts a crypto / forex rank event in the
rolling-IC gate, honoured by main.py's buffer and by the offline replica alike."""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.live_parity import make_rolling_ic_gate_fn
from portfolio.rolling_ic_gate import resolve_late_bar_event_count, should_record_ic_event


def test_the_default_is_the_v61_double_count_and_once_drops_only_a_late_bars_re_score():
    assert resolve_late_bar_event_count({}) == "per_tick"
    assert resolve_late_bar_event_count({"late_bar_event_count": "ONCE"}) == "once"
    assert resolve_late_bar_event_count({"late_bar_event_count": "twice"}) == "per_tick"
    assert should_record_ic_event("crypto", fresh_bar=False, mode="per_tick")
    assert not should_record_ic_event("crypto", fresh_bar=False, mode="once")
    assert should_record_ic_event("crypto", fresh_bar=True, mode="once")
    assert should_record_ic_event("equity", fresh_bar=False, mode="once")
    assert not should_record_ic_event("forex", fresh_bar=False, mode="once")


def _frame(seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for day_index, day in enumerate(pd.bdate_range("2024-01-02", periods=70)):
        for index in range(14):
            ticker = "BTCUSD" if index == 0 else f"E{index}"
            skill = (index - 7) / 14 if index else -0.9
            rows.append({"date": day.strftime("%Y-%m-%d"), "ticker": ticker, "raw": skill + rng.normal(0, 0.3),
                         "close": 100.0 * (1 + 0.002 * day_index * (skill + rng.normal(0, 0.5)))})
    return pd.DataFrame(rows)


def test_the_offline_gate_counts_late_bars_the_way_the_config_says():
    frame = _frame()
    config = {"horizon_days": 5, "rolling_window_days": 30, "min_names_per_date": 5, "min_resolved_dates_required": 5,
              "min_rolling_mean_ic": 0.0}
    late = {"BTCUSD"}
    doubled = make_rolling_ic_gate_fn(frame, raw_score_column="raw", gate_config=config, late_bar_tickers=late)
    once = make_rolling_ic_gate_fn(frame, raw_score_column="raw", gate_config=dict(config, late_bar_event_count="once"),
                                   late_bar_tickers=late)
    plain = make_rolling_ic_gate_fn(frame, raw_score_column="raw", gate_config=config, late_bar_tickers=None)
    last = sorted(frame["date"].unique())[-1]
    assert once(last) == plain(last)  # "once" is the single-count replica
    assert doubled(last)["observed_rolling_mean_ic"] != once(last)["observed_rolling_mean_ic"]
