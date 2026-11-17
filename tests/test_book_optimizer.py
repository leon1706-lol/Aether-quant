"""portfolio/book_optimizer.py: each optimizer on a case small enough to check by hand, and the properties they share (V6.6.9)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from portfolio import book_optimizer as bo
from portfolio.premia_signals import POOLED, _raw_weights

CLASSES = {**{f"E{i}": "equity" for i in range(6)}, **{f"B{i}": "bond" for i in range(4)}, "C0": "crypto", "C1": "crypto"}


def _returns(seed: int = 3, sessions: int = 150, scale: dict[str, float] | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    scale = scale or {}
    return pd.DataFrame({name: rng.normal(0.0, scale.get(name, 0.02 if cls == "crypto" else 0.01 if cls == "equity" else 0.004), sessions)
                         for name, cls in CLASSES.items()})


def _scores(seed: int = 4) -> pd.Series:
    return pd.Series(np.random.default_rng(seed).uniform(0.0, 1.0, len(CLASSES)), index=list(CLASSES))


def test_centred_ranks_sum_to_zero_per_class_and_skip_a_class_too_small_to_rank():
    ranks = bo.centred_ranks(_scores(), CLASSES)
    assert set(ranks.index) == {name for name, cls in CLASSES.items() if cls != "crypto"}  # two coins are not a ranking
    for cls in ("equity", "bond"):
        members = ranks[[name for name in ranks.index if CLASSES[name] == cls]]
        assert float(members.sum()) == pytest.approx(0.0, abs=1e-12)
    four = bo.centred_ranks(pd.Series({"B0": 0.1, "B1": 0.2, "B2": 0.3, "B3": 0.4}), CLASSES)
    assert four.to_dict() == pytest.approx({"B0": -0.375, "B1": -0.125, "B2": 0.125, "B3": 0.375})
    assert bo.centred_ranks(pd.Series({"C0": 1.0, "C1": 2.0, "X": 3.0}), CLASSES).empty
    assert bo.centred_ranks(pd.Series(dtype=float), CLASSES).empty


def test_pooled_equals_the_path_the_target_weights_code_already_takes():
    scores = _scores()
    ours = bo.pooled(scores, _returns(), CLASSES)
    theirs = _raw_weights(scores, POOLED, pd.Series(dtype=float), CLASSES)
    pd.testing.assert_series_equal(ours.sort_index(), theirs.sort_index())


def test_inverse_vol_gives_each_class_the_same_gross_and_the_calmer_name_more():
    returns = _returns(scale={"E0": 0.002, "E5": 0.05})
    scores = pd.Series({**{f"E{i}": i / 10 for i in range(6)}, **{f"B{i}": i / 10 for i in range(4)}})
    weights = bo.inverse_vol_ranks(scores, returns, CLASSES)
    equity = weights[[name for name in weights.index if CLASSES[name] == "equity"]]
    bond = weights[[name for name in weights.index if CLASSES[name] == "bond"]]
    assert float(equity.abs().sum()) == pytest.approx(1.0) and float(bond.abs().sum()) == pytest.approx(1.0)
    assert abs(weights["E0"]) > abs(weights["E5"])  # the same |rank|, a twenty-fifth of the volatility
    assert weights["E0"] < 0.0 < weights["E5"]


def test_inverse_vol_drops_a_class_left_with_only_its_middle_name_and_survives_no_history():
    scores = pd.Series({"B0": 0.1, "B1": 0.2, "E0": 0.1, "E1": 0.2, "E2": 0.3, "E3": 0.4, "E4": 0.5})
    returns = _returns()
    returns[["E0", "E1", "E3", "E4"]] = np.nan  # only E2 has risk history, and its centred rank is zero
    assert bo.inverse_vol_ranks(scores, returns, CLASSES).empty
    assert bo.inverse_vol_ranks(pd.Series({"C0": 1.0}), returns, CLASSES).empty


def test_class_risk_parity_puts_every_class_at_the_same_ex_ante_risk():
    returns = _returns()
    weights = bo.class_risk_parity(_scores(), returns, CLASSES)
    covariance = returns.iloc[-60:].cov()
    risks = []
    for cls in ("equity", "bond"):
        members = weights[[name for name in weights.index if CLASSES[name] == cls]]
        risks.append(math.sqrt(float(members.to_numpy() @ covariance.loc[members.index, members.index].to_numpy() @ members.to_numpy())))
    assert risks[0] == pytest.approx(risks[1], rel=1e-9)
    assert float(weights.abs().sum()) == pytest.approx(1.0)
    # bonds are calmer, so they get the larger gross
    gross = bo.class_gross(weights.to_dict(), CLASSES)
    assert gross["bond"] > gross["equity"]


def test_class_risk_parity_drops_a_class_whose_risk_cannot_be_measured():
    returns = _returns()
    returns[[f"B{i}" for i in range(4)]] = 0.0
    weights = bo.class_risk_parity(_scores(), returns, CLASSES)
    assert all(CLASSES[name] == "equity" for name in weights.index) and len(weights) == 6
    flat = _returns() * 0.0
    assert bo.class_risk_parity(_scores(), flat, CLASSES).empty


def test_hrp_book_holds_the_best_and_worst_third_of_each_ranked_class():
    scores = pd.Series({**{f"E{i}": float(i) for i in range(6)}, **{f"B{i}": float(i) for i in range(4)}, "C0": 1.0, "C1": 2.0, "GONE": 3.0})
    classes = {**CLASSES, "GONE": "equity"}
    scores = scores.drop("GONE")
    weights = bo.hrp_book(scores, _returns(), classes)
    assert set(weights.index) == {"E0", "E1", "E4", "E5", "B0", "B3"}
    assert weights["E5"] > 0.0 > weights["E0"] and weights["B3"] > 0.0 > weights["B0"]
    assert float(weights.abs().sum()) == pytest.approx(1.0)
    partial_history = _returns().drop(columns=["E5"])
    without = bo.hrp_book(scores, partial_history, classes)
    assert "E5" not in without.index and set(without.index) == {"E0", "E4", "B0", "B3"}  # no risk history: not selected


def test_shrunk_covariance_keeps_variances_and_pulls_correlations_to_their_mean():
    frame = pd.DataFrame(np.random.default_rng(1).normal(size=(200, 3)), columns=list("abc"))
    frame["b"] = frame["a"] * 0.9 + frame["b"] * 0.1
    sample = frame.cov()
    full = bo.shrunk_covariance(frame, 1.0)
    assert np.diag(full.to_numpy()) == pytest.approx(np.diag(sample.to_numpy()))
    correlation = full.to_numpy() / np.sqrt(np.outer(np.diag(full), np.diag(full)))
    assert correlation[0, 1] == pytest.approx(correlation[0, 2]) == pytest.approx(correlation[1, 2])
    pd.testing.assert_frame_equal(bo.shrunk_covariance(frame, 0.0), sample)
    pd.testing.assert_frame_equal(bo.shrunk_covariance(frame, -5.0), sample)
    one = bo.shrunk_covariance(frame[["a"]], 0.5)
    assert float(one.iloc[0, 0]) == pytest.approx(float(sample.loc["a", "a"]))
    with_flat = bo.shrunk_covariance(frame.assign(flat=1.0), 0.5)
    assert float(with_flat.loc["flat", "flat"]) == 0.0 and np.isfinite(with_flat.to_numpy()).all()


def test_mean_variance_goes_with_the_rank_and_needs_a_full_window():
    returns = _returns()
    scores = pd.Series({f"E{i}": float(i) for i in range(6)})
    weights = bo.shrunk_mean_variance(scores, returns, CLASSES)
    assert float(weights.abs().sum()) == pytest.approx(1.0)
    assert weights["E5"] > 0.0 > weights["E0"]
    gap = returns.copy()
    gap.loc[gap.index[-3], "E5"] = np.nan
    assert "E5" not in bo.shrunk_mean_variance(scores, gap, CLASSES).index
    assert bo.shrunk_mean_variance(scores, returns.iloc[:1], CLASSES).empty
    assert bo.shrunk_mean_variance(pd.Series({"C0": 1.0, "C1": 2.0}), returns, CLASSES).empty


def test_mean_variance_returns_nothing_rather_than_a_non_finite_weight(monkeypatch):
    monkeypatch.setattr(bo.np.linalg, "pinv", lambda matrix: np.full(matrix.shape, np.nan))
    assert bo.shrunk_mean_variance(pd.Series({f"E{i}": float(i) for i in range(6)}), _returns(), CLASSES).empty


def test_the_core_is_long_only_and_shares_risk_between_the_classes():
    returns = _returns()
    core = bo.risk_parity_core(returns, CLASSES)
    assert (core > 0.0).all() and float(core.sum()) == pytest.approx(1.0)
    gross = bo.class_gross(core.to_dict(), CLASSES)
    assert gross["bond"] > gross["equity"] > gross["crypto"]
    assert bo.risk_parity_core(returns * 0.0, CLASSES).empty


def test_the_tilt_moves_weight_toward_the_view_and_never_goes_short():
    returns = _returns()
    core = bo.risk_parity_core(returns, CLASSES)
    scores = pd.Series({**{f"E{i}": float(i) for i in range(6)}, "C0": 1.0, "C1": 9.0, **{f"B{i}": 0.5 for i in range(4)}})
    tilted = bo.tilted_core(scores, returns, CLASSES)
    assert (tilted > 0.0).all() and float(tilted.sum()) == pytest.approx(1.0)
    assert "E0" not in tilted.index  # z = -1.46, so 1 + z is below zero: a zero weight, not a short
    assert tilted["E4"] / tilted["E1"] > core["E4"] / core["E1"]
    # two coins are too few to rank, and bonds all carry the same score: both keep their core proportions
    assert tilted["C1"] / tilted["C0"] == pytest.approx(core["C1"] / core["C0"])
    assert tilted["B1"] / tilted["B0"] == pytest.approx(core["B1"] / core["B0"])
    harsh = bo.tilted_core(scores, returns, CLASSES, kappa=5.0)
    assert "E0" not in harsh.index and (harsh > 0.0).all()  # a tilt below zero is a zero weight, not a short
    assert bo.tilted_core(scores, returns, CLASSES, kappa=0.0).to_dict() == pytest.approx(core.to_dict())


def test_no_trade_band_keeps_small_changes_drops_what_the_target_drops_and_is_idempotent():
    current = {"A": 0.10, "B": 0.10, "GONE": 0.05}
    target = {"A": 0.11, "B": 0.20, "NEW": 0.03, "ZERO": 0.0}
    out = bo.no_trade_band(current, target, band=0.25)
    assert out == {"A": 0.10, "B": 0.20, "NEW": 0.03}
    assert bo.no_trade_band(out, target, band=0.25) == out
    assert bo.no_trade_band(current, target, band=0.0)["A"] == 0.11
    assert bo.no_trade_band({"A": -0.1}, {"A": 0.1}, band=0.25) == {"A": 0.1}  # a change of sign is never inside the band


def test_class_helpers():
    row = {"E0": 0.2, "E1": -0.1, "B0": 0.3, "X": 0.05}
    assert bo.class_gross(row, CLASSES) == pytest.approx({"equity": 0.3, "bond": 0.3, "None": 0.05})
    assert bo.drop_classes(row, CLASSES, ["bond"]) == {"E0": 0.2, "E1": -0.1, "X": 0.05}


def test_the_paper_loss_guard_needs_a_record_and_reads_only_the_trailing_window():
    assert bo.paper_loss_guard([0.0] * 59, lookback=60, max_loss=0.01) is False  # too little record: stay out
    assert bo.paper_loss_guard([0.0] * 60, lookback=60, max_loss=0.01) is True
    assert bo.paper_loss_guard([0.0] * 30 + [-0.001] * 30, lookback=60, max_loss=0.01) is False  # 3% down
    assert bo.paper_loss_guard([-0.05] + [0.0] * 60, lookback=60, max_loss=0.01) is True  # the old loss has left the window
    assert bo.paper_loss_guard([0.0] * 5, lookback=0, max_loss=0.01) is False


def test_the_registry_is_closed_and_carries_only_an_optimizers_own_parameters():
    assert bo.optimizer_for(None) is None and bo.optimizer_for({"table": "ml_a1"}) is None
    assert bo.optimizer_for({"optimizer": "pooled", "kappa": 3.0}) is bo.pooled
    with pytest.raises(ValueError, match="unknown optimizer"):
        bo.optimizer_for({"optimizer": "os.system"})
    returns, scores = _returns(), _scores()
    tilted = bo.optimizer_for({"optimizer": "tilted_core", "kappa": 0.0, "window": 5})(scores, returns, CLASSES)
    assert tilted.to_dict() == pytest.approx(bo.risk_parity_core(returns, CLASSES).to_dict())
    core = bo.optimizer_for({"optimizer": "core"})(scores, returns, CLASSES)
    assert core.to_dict() == pytest.approx(bo.risk_parity_core(returns, CLASSES).to_dict())
    assert set(bo.OPTIMIZERS) == set(bo.OPTIMIZER_PARAMS)


@settings(max_examples=40, deadline=None, derandomize=True)
@given(
    seed=st.integers(min_value=0, max_value=10_000),
    missing=st.lists(st.sampled_from(list(CLASSES)), max_size=6, unique=True),
    flat=st.lists(st.sampled_from(list(CLASSES)), max_size=4, unique=True),
    scale=st.floats(min_value=0.1, max_value=20.0),
)
def test_every_optimizer_returns_finite_weights_whatever_is_missing(seed, missing, flat, scale):
    returns = _returns(seed)
    returns[flat] = 0.0
    scores = _scores(seed + 1)
    scores[missing] = np.nan
    for name, optimizer in bo.OPTIMIZERS.items():
        weights = optimizer(scores, returns, CLASSES)
        assert np.isfinite(weights.to_numpy(dtype=float)).all(), name
        if name != "pooled":  # the control sizes by rank alone, exactly as the existing path does
            assert not set(weights.index) & set(flat), name  # no risk history, no weight
        if name in ("tilted_core", "core"):
            assert (weights >= 0.0).all(), name
        # the same book whatever the unit of the returns: the vol target, not the optimizer, sets the size
        rescaled = optimizer(scores, returns * scale, CLASSES)
        assert rescaled.reindex(weights.index).to_numpy() == pytest.approx(weights.to_numpy(), rel=1e-6, abs=1e-9), name
    assert bo.pooled(scores * np.nan, returns, CLASSES).empty
