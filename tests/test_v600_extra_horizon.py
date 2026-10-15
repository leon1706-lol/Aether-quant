"""V6.0.0: a 60-day rank target and head that exist only when the config asks for them.

The default dataset, model, export and head config must stay exactly what they were, so a run without
`phase1.target.ranking.extra_horizon_days` / `horizon_heads.rank_60d` is unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from train import (
    HORIZON_HEAD_SPECS,
    AetherNetMultiTaskHorizons,
    compute_combined_multitask_loss,
    engineer_features,
    export_multitask_horizons_architecture,
    horizon_head_specs,
    resolve_extra_horizon_days,
    resolve_horizon_head_config,
)
from train_multitask import frame_to_multitask_tensors

FEATURE_NAMES = [
    "close_to_close_return_1d", "close_to_close_return_5d", "close_to_close_return_20d",
    "rolling_volatility_5d", "rolling_volatility_20d", "momentum_5d", "momentum_20d",
    "high_low_range_pct", "open_close_range_pct", "volume_change_1d",
]
WINDOWS = {
    "training": {"start": "2019-01-01", "end": "2019-12-31"},
    "validation": {"start": "2020-01-01", "end": "2020-12-31"},
    "backtest": {"start": "2021-01-01", "end": "2021-12-31"},
}


def _equity_frame(n: int = 160, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-02", periods=n)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return pd.DataFrame(
        {"timestamp": dates, "date": dates, "open": closes, "high": closes * 1.01, "low": closes * 0.99, "close": closes,
         "volume": 1e6, "ticker": "AAA", "security_type": "equity", "market": "usa"}
    )


def test_no_extra_horizon_by_default_and_the_purge_must_cover_it():
    assert resolve_extra_horizon_days({}) == ()
    config = {"phase1": {"target": {"ranking": {"extra_horizon_days": [60, 20]}}, "windows": {"purge_label_horizon_days": 60}}}
    assert resolve_extra_horizon_days(config) == (60,)
    config["phase1"]["windows"]["purge_label_horizon_days"] = 20
    with pytest.raises(ValueError):
        resolve_extra_horizon_days(config)


def test_the_60_day_target_is_the_forward_return_and_leaves_the_rest_unchanged():
    frame = _equity_frame()
    plain = engineer_features(frame, FEATURE_NAMES, WINDOWS)
    extended = engineer_features(frame, FEATURE_NAMES, WINDOWS, extra_horizon_days=(60,))
    pd.testing.assert_frame_equal(plain, extended.drop(columns=["target_return_60d"]))
    closes = frame.set_index("date")["close"]
    row = extended.iloc[10]
    expected = closes.shift(-60).loc[row["date"]] / closes.loc[row["date"]] - 1.0
    assert row["target_return_60d"] == pytest.approx(expected)
    assert extended["target_return_60d"].tail(59).isna().all()  # the last row (no 1-day label) is already dropped


def test_default_head_config_and_model_are_unchanged():
    resolved = resolve_horizon_head_config({})
    assert "rank_60d" not in resolved
    assert horizon_head_specs(resolved) == HORIZON_HEAD_SPECS
    torch.manual_seed(0)
    default = AetherNetMultiTaskHorizons(input_dim=4, hidden_layers=[8], dropout=0.0)
    torch.manual_seed(0)
    extended = AetherNetMultiTaskHorizons(input_dim=4, hidden_layers=[8], dropout=0.0, extra_heads=("rank_60d",))
    for name, tensor in default.state_dict().items():
        assert torch.equal(tensor, extended.state_dict()[name]), name  # same init for every shared parameter
    assert "rank_60d" not in export_multitask_horizons_architecture(default)["heads"]
    assert "rank_60d" in export_multitask_horizons_architecture(extended)["heads"]


def test_an_enabled_60_day_head_trains_through_the_shared_loss():
    config = resolve_horizon_head_config({"horizon_heads": {"rank_60d": {"enabled": True, "loss_weight": 1.0}}})
    specs = horizon_head_specs(config)
    assert specs["rank_60d"] == ("target_rank_60d", "rank", 60)
    frame = pd.DataFrame(
        {"f1": [0.1, -0.2, 0.3], "f2": [0.0, 0.5, -0.5], "target_direction": [1, 0, 1], "target_return_1d": [0.01, -0.01, 0.0],
         "target_volatility_next_day": [0.02, 0.01, 0.03], "target_rank_60d": [0.9, np.nan, 0.1]}
        | {column: [0.5, 0.5, 0.5] for column, _kind, _stride in HORIZON_HEAD_SPECS.values()}
    )
    features, targets = frame_to_multitask_tensors(frame, ["f1", "f2"], specs)
    assert torch.isnan(targets["rank_60d"][1])
    model = AetherNetMultiTaskHorizons(input_dim=2, hidden_layers=[4], dropout=0.0, extra_heads=("rank_60d",))
    outputs = model(features)
    loss = compute_combined_multitask_loss(outputs, targets, torch.nn.BCEWithLogitsLoss(), 1.0, 1.0, config)
    loss.backward()
    assert model.head_rank_60d.weight.grad is not None and torch.isfinite(loss)
