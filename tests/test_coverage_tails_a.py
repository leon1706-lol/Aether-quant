"""The last unreached branches of small evaluation, execution and portfolio modules (V6.6.6, #359): each test names the input that reaches one defensive branch and asserts what the module does with it."""

from __future__ import annotations

import contextlib
import math
import os

import numpy as np
import pandas as pd
import pytest

from evaluation import alpha_decay, feature_quality_audit, hello_world, ml_cleanup, monte_carlo, rolling_ic_series, walk_forward_linear


# ---- ml_cleanup ----------------------------------------------------------------------------------------------------------


def test_directory_size_skips_an_entry_it_cannot_stat_and_a_directory_it_cannot_open(monkeypatch, tmp_path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "file.bin").write_bytes(b"x" * 10)
    (tmp_path / "locked").mkdir()
    real_scandir = os.scandir

    class Unreadable:
        path = "ghost"

        def is_dir(self, follow_symlinks=False):
            return False

        def stat(self, follow_symlinks=False):
            raise OSError("denied")

    def scandir(path):
        if str(path).endswith("locked"):
            raise OSError("no access")
        if str(path).endswith("keep"):
            return contextlib.nullcontext([Unreadable()])
        return real_scandir(path)

    monkeypatch.setattr(ml_cleanup.os, "scandir", scandir)
    assert ml_cleanup.directory_size(tmp_path) == 0


# ---- hello_world ---------------------------------------------------------------------------------------------------------


def test_finite_drops_none_and_non_finite_values():
    assert hello_world._finite(None) is None and hello_world._finite(float("inf")) is None and hello_world._finite(2) == 2.0


def test_the_coin_download_falls_back_to_the_sample_with_a_notice_unless_every_coin_arrives(monkeypatch):
    from data_pipeline import public_candles

    sample = pd.DataFrame({"BTCUSD": [1.0, 2.0]}, index=pd.to_datetime(["2020-01-01", "2020-01-02"]))
    monkeypatch.setattr("aether_quant.samples.load_sample_prices", lambda: sample)
    monkeypatch.setattr(public_candles, "fetch_daily_bars", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    closes, source, notice = hello_world.load_closes(start="2022-01-01", end="2022-02-01")
    assert closes is sample and source == hello_world.SAMPLE_SOURCE and "network: offline" in notice
    monkeypatch.setattr(public_candles, "fetch_daily_bars", lambda *a, **k: ({"BTCUSD": [1]}, []))
    monkeypatch.setattr(public_candles, "bars_to_panel", lambda bars, field: sample * 2)
    closes, source, notice = hello_world.load_closes(start="2022-01-01", end="2022-02-01", cache_dir=None)
    assert closes["BTCUSD"].tolist() == [2.0, 4.0] and "cache off" in source and notice is None
    _, source, _ = hello_world.load_closes(start="2022-01-01", end="2022-02-01", cache_dir=__import__("pathlib").Path("cache"))
    assert "cache cache" in source


# ---- walk_forward_linear -------------------------------------------------------------------------------------------------


def test_a_start_date_that_is_not_a_session_begins_at_the_next_one_and_a_start_after_the_data_is_all_nan():
    index = [f"2020-01-{day:02d}" for day in range(1, 31)]
    columns = [f"T{n}" for n in range(6)]
    rng = np.random.default_rng(0)
    feature = pd.DataFrame(rng.normal(size=(30, 6)), index=index, columns=columns)
    label = pd.DataFrame(rng.normal(size=(30, 6)), index=index, columns=columns)
    common = dict(signs={"a": 1.0}, kappa=3, ridge=1.0, horizon=1, purge_sessions=1, every=3)
    between = walk_forward_linear.fama_macbeth_ridge({"a": feature}, label, start="2020-01-10x", **common)
    assert between.shape == label.shape
    after = walk_forward_linear.fama_macbeth_ridge({"a": feature}, label, start="2021-01-01", **common)
    assert after.isna().all().all()


# ---- feature_quality_audit -----------------------------------------------------------------------------------------------


def test_daily_ic_skips_thin_and_constant_days():
    frame = pd.DataFrame({"date": ["d1"] * 3 + ["d2"] * 12 + ["d3"] * 12, "target_rank_20d": list(range(3)) + list(range(12)) + [1.0] * 12})
    frame["score"] = list(range(3)) + list(range(12)) + list(range(12))
    assert feature_quality_audit._daily_ic(frame, "score", "target_rank_20d", "date", 10) == pytest.approx(1.0)
    assert feature_quality_audit._daily_ic(frame.iloc[:3], "score", "target_rank_20d", "date", 10) is None


def test_a_feature_that_is_not_a_column_is_left_out_of_the_drop_in_ic():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"date": np.repeat([f"d{n}" for n in range(6)], 12), "feature": rng.normal(size=72)})
    frame["target_rank_20d"] = frame["feature"] + rng.normal(scale=0.1, size=72)
    drops = feature_quality_audit.permutation_ic_drop(frame, ["absent", "feature"], lambda data: data["feature"].to_numpy(), target="target_rank_20d", min_names=10)
    assert drops["absent"] is None and drops["feature"] is not None and drops["feature"] > 0.0


# ---- rolling_ic_series ---------------------------------------------------------------------------------------------------


def test_an_origin_with_constant_predictions_has_no_ic_and_a_zero_close_is_not_a_return_base():
    assert rolling_ic_series._origin_ic(np.array([1.0, 1.0, 1.0]), np.array([0.1, 0.2, 0.3]), 3) is None
    assert rolling_ic_series._origin_ic(np.array([1.0, 2.0]), np.array([0.1, 0.2]), 3) is None
    events = [{"ticker": "A", "created_at": f"2020-01-0{day}", "resolved_predicted_rank_20d": 0.5, "close_price": 0.0 if day == 1 else 10.0} for day in range(1, 6)]
    state_at = rolling_ic_series.make_rolling_ic_state_fn(events, horizon_days=1, rolling_window_days=5, min_names_per_date=1)
    assert state_at("2020-01-09")["rolling_mean_ic"] is None


# ---- monte_carlo ---------------------------------------------------------------------------------------------------------


def test_a_single_return_has_no_sharpe_and_a_zero_run_count_is_reported_as_skipped():
    assert monte_carlo._annualized_sharpe(np.array([0.01])) == 0.0
    returns = np.random.default_rng(0).normal(0.001, 0.01, 60)
    assert monte_carlo.run_monte_carlo(returns, n_runs=0)["status"] == "SKIPPED: n_runs < 1"


# ---- alpha_decay ---------------------------------------------------------------------------------------------------------


def test_a_short_return_history_has_no_decayed_sharpe_and_the_simulation_stops_once_every_path_has_alarmed():
    assert alpha_decay._ew_sharpe(np.zeros(5)) is None
    config = alpha_decay.DecayConfig(threshold=0.01, min_sessions=1)
    runs = alpha_decay.average_run_lengths(expected_sharpe=3.0, config=config, paths=4, horizon=50, decayed_sharpe=-3.0)
    assert runs["paths"] == 4
    assert math.isfinite(alpha_decay.decay_state([0.001] * 5, expected_sharpe=1.0).statistic)
