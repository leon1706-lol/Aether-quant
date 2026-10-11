"""V5.7.0 training-pipeline correctness fixes (Problems.md #145+): split-boundary label purge, and the other dataset /
eligibility changes grouped in this round file. Pure-function tests; no torch training."""

from datetime import date

import pandas as pd
import pytest

from train import apply_scaler_stats, build_fx_carry_features, build_holdout_config, purge_label_overlap


def test_apply_scaler_stats_uses_the_given_statistics_and_clips():
    frame = pd.DataFrame({"a": [10.0, 12.0, 1000.0], "b": [1.0, 1.0, 1.0]})
    stats = {"feature_names": ["a", "b"], "mean": [10.0, 1.0], "scale": [2.0, 0.0], "clip_sigma": 5.0}
    scaled = apply_scaler_stats(frame, stats)
    assert scaled["a_scaled"].tolist() == [0.0, 1.0, 5.0]  # (1000-10)/2 clipped to +5 sigma
    assert scaled["b_scaled"].tolist() == [0.0, 0.0, 0.0]  # a zero scale is treated as 1, like the runtime
    assert "a_scaled" not in frame.columns


def test_build_holdout_config_repoints_assets_drops_missing_zips_and_swaps_the_backtest_window(tmp_path, monkeypatch):
    import train

    monkeypatch.setattr(train, "ROOT", tmp_path)
    (tmp_path / "data_holdout" / "equity" / "usa" / "daily").mkdir(parents=True)
    (tmp_path / "data_holdout" / "equity" / "usa" / "daily" / "aapl.zip").write_bytes(b"x")
    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {"ticker": "AAPL", "data_path": "data/equity/usa/daily/aapl.zip"},
                    {"ticker": "GONE", "data_path": "data/equity/usa/daily/gone.zip"},
                ],
                "common_window": {"start": "2014-12-01", "end": "2021-03-31"},
            },
            "windows": {
                "training": {"start": "2014-12-01", "end": "2017-12-31"},
                "validation": {"start": "2018-01-01", "end": "2018-12-31"},
                "backtest": {"start": "2019-01-01", "end": "2021-03-31"},
            },
        }
    }
    holdout, dropped = build_holdout_config(config, "data_holdout", "2021-04-01", "2025-06-30")
    assert dropped == ["GONE"]
    assert [a["data_path"] for a in holdout["phase1"]["universe"]["assets"]] == ["data_holdout/equity/usa/daily/aapl.zip"]
    assert holdout["phase1"]["universe"]["common_window"] == {"start": "2014-12-01", "end": "2025-06-30"}
    assert holdout["phase1"]["universe"]["apply_factor_files"] is False
    assert holdout["phase1"]["universe"]["fred_cache_dir"] == "data_holdout/reference/fred_series"
    assert holdout["phase1"]["windows"]["backtest"] == {"start": "2021-04-01", "end": "2025-06-30"}
    assert holdout["phase1"]["windows"]["training"] == config["phase1"]["windows"]["training"]
    assert config["phase1"]["universe"]["assets"][0]["data_path"] == "data/equity/usa/daily/aapl.zip"  # input untouched


def _quality_inputs(train_rows, validation_rows, backtest_rows, **quality):
    from train import build_asset_quality

    config = {
        "phase1": {"universe": {"assets": [{"ticker": "ETHUSD", "security_type": "crypto", "market": "coinbase"}]}},
        "phase9": {"asset_quality": {"min_total_feature_rows": 50, "min_training_rows": 250, "min_backtest_rows": 20, **quality}},
    }
    splits = ["train"] * train_rows + ["validation"] * validation_rows + ["backtest"] * backtest_rows
    dataset = pd.DataFrame({"ticker": "ETHUSD", "split": splits})
    metadata = {"asset_summaries": [{"ticker": "ETHUSD", "feature_rows": len(splits), "available_rows": len(splits)}]}
    return build_asset_quality(config, dataset, metadata)["ETHUSD"]


def test_trading_eligibility_follows_train_rows_unless_the_history_basis_is_configured():
    short_train = _quality_inputs(54, 365, 800)
    assert not short_train["trading_eligible"] and not short_train["training_eligible"] and short_train["role"] == "observation_only"
    history = _quality_inputs(54, 365, 800, trading_eligibility_basis="history")
    assert history["trading_eligible"] is True and history["training_eligible"] is False
    assert history["quality_tier"] == "core" and history["role"] == "trading_without_training_rows"
    full = _quality_inputs(300, 365, 800, trading_eligibility_basis="history")
    assert full["trading_eligible"] and full["training_eligible"] and full["role"] == "model_training_and_trading"


def test_history_basis_still_requires_enough_validation_and_backtest_rows():
    too_short = _quality_inputs(54, 100, 200, trading_eligibility_basis="history")
    assert too_short["trading_eligible"] is False
    no_backtest = _quality_inputs(54, 700, 10, trading_eligibility_basis="history")
    assert no_backtest["trading_eligible"] is False


def _rank_frames():
    dates = pd.to_datetime([f"2020-01-{day:02d}" for day in range(1, 5)])
    returns = {"E1": 0.04, "E2": 0.02, "E3": -0.01, "E4": -0.03, "F1": 0.002, "F2": 0.001, "F3": -0.001, "F4": -0.002}
    return {
        ticker: pd.DataFrame({"date": dates, "target_return_5d": value, "target_return_20d": value}) for ticker, value in returns.items()
    }


def _rank_config(**ranking):
    classes = {"E1": "equity", "E2": "equity", "E3": "equity", "E4": "equity", "F1": "forex", "F2": "forex", "F3": "forex", "F4": "forex"}
    return {
        "phase1": {
            "universe": {"assets": [{"ticker": t, "security_type": kind} for t, kind in classes.items()]},
            "target": {"ranking": {"min_universe_size": 3, **ranking}},
        }
    }


def test_forex_pairs_can_be_ranked_among_themselves_instead_of_against_equities():
    from train import build_cross_sectional_rank_targets

    pooled = build_cross_sectional_rank_targets(_rank_frames(), _rank_config())
    split = build_cross_sectional_rank_targets(
        _rank_frames(), _rank_config(separate_rank_groups={"forex": ["forex"]}, separate_rank_group_min_size=3)
    )
    # pooled: the best forex pair (+0.2%) is ranked 6th of 8 among equities and pairs together
    assert pooled["F1"]["target_rank_5d"].iloc[0] == pytest.approx(6 / 8)
    # split: ranks are within each class's own pool
    assert split["F1"]["target_rank_5d"].iloc[0] == pytest.approx(1.0) and split["F4"]["target_rank_5d"].iloc[0] == pytest.approx(0.25)
    assert split["E1"]["target_rank_5d"].iloc[0] == pytest.approx(1.0) and split["E4"]["target_rank_5d"].iloc[0] == pytest.approx(0.25)


def test_a_separate_rank_group_below_its_minimum_size_gets_nan_ranks():
    from train import build_cross_sectional_rank_targets

    split = build_cross_sectional_rank_targets(
        _rank_frames(), _rank_config(separate_rank_groups={"forex": ["forex"]}, separate_rank_group_min_size=5)
    )
    assert split["F1"]["target_rank_5d"].isna().all()
    assert split["E2"]["target_rank_5d"].notna().all()


def _fx_config():
    return {
        "phase1": {
            "universe": {
                "assets": [
                    {"ticker": "AUDJPY", "security_type": "forex"},
                    {"ticker": "AAPL", "security_type": "equity"},
                ]
            }
        }
    }


def test_fx_carry_column_is_the_rate_gap_for_forex_rows_and_zero_for_everything_else():
    fred = {
        "interbank_3m_aud": [{"date": date(2020, 1, 1), "value": 0.9}],
        "interbank_3m_jpy": [{"date": date(2020, 1, 1), "value": -0.1}],
    }
    frames = {
        "AUDJPY": pd.DataFrame({"date": pd.to_datetime(["2020-01-10", "2020-03-10"])}),
        "AAPL": pd.DataFrame({"date": pd.to_datetime(["2020-03-10"])}),
    }
    result = build_fx_carry_features(frames, _fx_config(), fred)
    assert result["AUDJPY"]["fx_carry_3m"].tolist() == [0.0, pytest.approx(1.0)]  # 45-day lag: Jan 10 sees no rate yet
    assert result["AAPL"]["fx_carry_3m"].tolist() == [0.0]
    assert "fx_carry_3m" not in frames["AAPL"].columns  # inputs are not mutated


def _labels(train, validation, backtest, gap=0):
    return ["train"] * train + [None] * gap + ["validation"] * validation + ["backtest"] * backtest


def test_purge_is_off_by_default_and_for_non_positive_horizons():
    labels = _labels(30, 10, 10)
    assert purge_label_overlap(labels, 0) == labels
    assert purge_label_overlap(labels, -3) == labels


def test_purge_relabels_the_last_horizon_rows_of_train_and_validation_only():
    labels = _labels(30, 25, 10)
    purged = purge_label_overlap(labels, 20)
    assert purged[:10] == ["train"] * 10
    assert purged[10:30] == ["purged"] * 20  # train rows 10..29: their 20-row label reaches validation (row 30)
    assert purged[30:35] == ["validation"] * 5
    assert purged[35:55] == ["purged"] * 20  # validation rows 35..54 reach the backtest
    assert purged[55:] == ["backtest"] * 10  # the last split has no later split to leak into
    assert len(purged) == len(labels)


def test_purge_counts_rows_not_calendar_gaps_and_ignores_rows_outside_every_window():
    labels = ["train"] * 10 + [None] * 5 + ["validation"] * 10
    purged = purge_label_overlap(labels, 8)
    # validation starts at row 15; a train row at index i reaches it when 15 - i <= 8, i.e. rows 7..9
    assert purged[:7] == ["train"] * 7 and purged[7:10] == ["purged"] * 3
    assert purged[10:15] == [None] * 5
    assert purged[15:] == ["validation"] * 10


def test_purge_leaves_a_frame_with_one_split_untouched():
    assert purge_label_overlap(["train"] * 12, 20) == ["train"] * 12
    assert purge_label_overlap([], 5) == []
    nan = float("nan")
    assert purge_label_overlap([nan, "train", "validation"], 5)[0] != "purged"


@pytest.mark.parametrize("horizon", [1, 5, 20])
def test_a_purged_row_never_has_its_label_window_inside_its_own_split(horizon):
    labels = _labels(60, 60, 30)
    purged = purge_label_overlap(labels, horizon)
    split_start = {"validation": 60, "backtest": 120}
    for index, label in enumerate(purged):
        if label == "train":
            assert index + horizon < split_start["validation"]
        if label == "validation":
            assert index + horizon < split_start["backtest"]
