"""portfolio/premia_signals.py: no sleeve reads the future, placebos remove the skill, and caps hold."""

import numpy as np
import pandas as pd
import pytest

from portfolio.premia_signals import (
    DIRECT,
    FAMILIES,
    TS,
    XS,
    ResearchPanel,
    SleeveSpec,
    WeightSettings,
    combine_sleeves,
    known_closes,
    null_signal,
    scale_and_cap,
    signal_to_weights,
    sleeve_signal,
)

EQUITY = ("SPY", "AAA", "BBB", "CCC", "DDD", "EEE", "QQQ", "IWM", "EEM", "USO")
BOND = ("TLT", "IEF", "SHY", "HYG", "LQD")
FOREX = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
CRYPTO = ("BTCUSD", "ETHUSD", "LTCUSD")


def _panel(rows: int = 700, seed: int = 3) -> ResearchPanel:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=rows).strftime("%Y-%m-%d").tolist()
    tickers = list(EQUITY + BOND + FOREX + CRYPTO)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, size=(rows, len(tickers))), axis=0))
    asset_class = {**{t: "equity" for t in EQUITY}, **{t: "bond" for t in BOND}, **{t: "forex" for t in FOREX}, **{t: "crypto" for t in CRYPTO}}
    known = known_closes(dates, tickers, closes, asset_class, set(dates))
    fred = {
        key: pd.Series(rng.normal(level, 0.2, size=rows), index=dates)
        for key, level in (("treasury_10yr", 3.0), ("treasury_3mo", 1.0), ("credit_spread_baa10y", 2.0),
                           ("implied_volatility_vix", 18.0), ("implied_volatility_3m", 20.0))
    }
    carry = pd.DataFrame(rng.normal(0.0, 1.0, size=(rows, len(FOREX))), index=dates, columns=list(FOREX))
    score = pd.DataFrame(rng.normal(size=(rows, len(EQUITY))), index=dates, columns=list(EQUITY))
    return ResearchPanel(known, asset_class, fred, {"fx_carry": carry, "model": score})


SPECS = [
    SleeveSpec("crypto_blend", "T3", TS, "crypto_trend", ("crypto",), 5, {"lookback_a": 20, "lookback_b": 60}),
    SleeveSpec("fx_mom", "T3", XS, "cross_sectional_return", ("forex",), 5, {"lookback": 63}),
    SleeveSpec("fx_carry", "T3", XS, "fx_carry", ("forex",), 20, {}),
    SleeveSpec("fx_carry_mom", "T3", XS, "fx_carry", ("forex",), 20, {"momentum_weight": 0.5}),
    SleeveSpec("reversal", "T3", XS, "residual_reversal", ("equity",), 5, {"window": 5}),
    SleeveSpec("resmom", "T3", XS, "residual_momentum", ("equity",), 20, {"lookback": 252, "skip": 21}),
    SleeveSpec("lowvol", "T3", XS, "low_volatility", ("equity",), 20, {}),
    SleeveSpec("bond_ts", "T3", TS, "time_series_momentum", ("bond",), 20, {"lookback_a": 126}),
    SleeveSpec("trend", "T3", TS, "time_series_momentum", ("equity", "bond"), 20, {"lookback_a": 63, "lookback_b": 126, "lookback_c": 252, "trend_set": 1}),
    SleeveSpec("slope", "T3", DIRECT, "bond_slope_timing", ("bond",), 20, {}),
    SleeveSpec("credit", "T3", DIRECT, "bond_credit_timing", ("bond",), 20, {}),
    SleeveSpec("vix_on", "T3", DIRECT, "vix_term_structure", ("equity",), 5, {"threshold": 0.95}),
    SleeveSpec("vix_scaled", "T3", DIRECT, "vix_term_structure", ("equity",), 5, {}),
    SleeveSpec("tom", "T3", DIRECT, "turn_of_month", ("equity",), 1, {}),
    SleeveSpec("model", "T1", XS, "external_score", ("equity",), 20, {"table": "model"}),
]


def test_every_family_is_covered_by_a_spec():
    assert {spec.family for spec in SPECS} == set(FAMILIES)


@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec.id)
def test_no_lookahead(spec):
    """Row D computed from data cut at D is row D computed from everything."""
    panel = _panel()
    full = sleeve_signal(spec, panel)
    for cut in (full.index[320], full.index[500], full.index[-40]):
        partial = sleeve_signal(spec, panel.truncated(cut))
        pd.testing.assert_series_equal(partial.loc[cut], full.loc[cut], check_names=False, check_exact=False, rtol=1e-9)


def test_known_closes_hold_crypto_and_forex_back_a_day_and_equities_not():
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    closes = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]])
    known = known_closes(dates, ["A", "B"], closes, {"A": "equity", "B": "crypto"}, {"2024-01-02", "2024-01-03"})

    assert known.loc["2024-01-02", "A"] == 2.0
    assert known.loc["2024-01-02", "B"] == 10.0
    assert known.loc["2024-01-03", "B"] == 20.0


def test_a_weekend_crypto_bar_is_known_on_monday():
    dates = ["2024-01-05", "2024-01-06", "2024-01-07", "2024-01-08"]
    closes = np.array([[1.0, 10.0], [np.nan, 20.0], [np.nan, 30.0], [2.0, 40.0]])
    known = known_closes(dates, ["A", "B"], closes, {"A": "equity", "B": "crypto"}, {"2024-01-05", "2024-01-08"})
    assert known.loc["2024-01-08", "B"] == 30.0


def test_turn_of_month_decides_a_session_before_it_holds():
    dates = pd.bdate_range("2024-01-02", "2024-03-29").strftime("%Y-%m-%d").tolist()
    known = pd.DataFrame(100.0, index=dates, columns=["SPY"])
    signal = FAMILIES["turn_of_month"](ResearchPanel(known, {"SPY": "equity"}), SPECS[-2])["SPY"]

    assert signal.loc["2024-01-30"] == 1.0  # the day before the month's last weekday
    assert signal.loc["2024-02-01"] == 1.0
    assert signal.loc["2024-01-15"] == 0.0


def test_weights_respect_every_cap_and_keep_crypto_long_only():
    panel = _panel()
    settings = WeightSettings(target_vol=5.0, gross_cap=1.4, name_cap=0.15)
    for spec in SPECS:
        rows = signal_to_weights(sleeve_signal(spec, panel), panel, kind=spec.kind, rebalance_every=spec.rebalance_every, settings=settings)
        for row in rows.values():
            assert sum(abs(value) for value in row.values()) <= 1.4 + 1e-9
            for ticker, value in row.items():
                limit = 0.05 if panel.asset_class[ticker] == "crypto" else 0.15
                assert abs(value) <= limit + 1e-9
                if panel.asset_class[ticker] == "crypto":
                    assert value >= 0.0
            assert sum(abs(v) for t, v in row.items() if panel.asset_class[t] == "crypto") <= 0.15 + 1e-9


def test_a_cross_sectional_book_is_dollar_neutral_within_each_class():
    panel = _panel()
    spec = next(s for s in SPECS if s.id == "lowvol")
    rows = signal_to_weights(sleeve_signal(spec, panel), panel, kind=XS, rebalance_every=20, settings=WeightSettings(name_cap=10.0, gross_cap=10.0))
    row = next(row for row in rows.values() if row)
    assert sum(row.values()) == pytest.approx(0.0, abs=1e-9)


def test_volatility_target_sets_the_ex_ante_vol():
    rng = np.random.default_rng(1)
    returns = pd.DataFrame(rng.normal(0.0, 0.01, size=(60, 2)), columns=["A", "B"])
    weights = scale_and_cap(pd.Series({"A": 1.0, "B": -1.0}), returns.cov(), {"A": "equity", "B": "equity"},
                            WeightSettings(target_vol=0.1, name_cap=10.0, gross_cap=10.0))
    vector = np.array([weights["A"], weights["B"]])
    assert float(vector @ returns.cov().to_numpy() @ vector) * 252.0 == pytest.approx(0.01, rel=1e-6)


def test_phase_offset_moves_the_rebalance_days():
    panel = _panel()
    spec = next(s for s in SPECS if s.id == "lowvol")
    signal = sleeve_signal(spec, panel)
    first = set(signal_to_weights(signal, panel, kind=XS, rebalance_every=20, phase_offset=0))
    second = set(signal_to_weights(signal, panel, kind=XS, rebalance_every=20, phase_offset=7))
    assert first and second and not first & second


def test_listing_filter_excludes_a_pair_not_yet_listed():
    panel = _panel()
    spec = next(s for s in SPECS if s.id == "crypto_blend")
    rows = signal_to_weights(sleeve_signal(spec, panel), panel, kind=TS, rebalance_every=5, listed=lambda ticker, date: ticker != "ETHUSD")
    assert all("ETHUSD" not in row for row in rows.values())


def _frame():
    dates = pd.bdate_range("2018-01-01", periods=600).strftime("%Y-%m-%d").tolist()
    rng = np.random.default_rng(0)
    data = rng.normal(size=(600, 6))
    data[:100, 5] = np.nan
    return pd.DataFrame(data, index=dates, columns=["A", "B", "C", "D", "E", "F"]), {t: "equity" for t in "ABCDEF"}


def test_asset_block_null_is_deterministic_keeps_availability_and_moves_values():
    signal, classes = _frame()
    first = null_signal(signal, "asset_block", seed=5, asset_class=classes)
    second = null_signal(signal, "asset_block", seed=5, asset_class=classes)
    other = null_signal(signal, "asset_block", seed=6, asset_class=classes)

    pd.testing.assert_frame_equal(first, second)
    assert not first.equals(other)
    assert first["F"].iloc[:100].isna().all()
    assert (first.iloc[:60].to_numpy() != signal.iloc[:60].to_numpy()).any()


def test_asset_block_null_never_mixes_classes():
    signal, _ = _frame()
    classes = {"A": "x", "B": "x", "C": "x", "D": "y", "E": "y", "F": "y"}
    out = null_signal(signal.fillna(0.0), "asset_block", seed=5, asset_class=classes)
    for row in range(0, 600, 60):
        assert set(np.round(out.iloc[row][["A", "B", "C"]], 9)) == set(np.round(signal.fillna(0.0).iloc[row][["A", "B", "C"]], 9))


def test_time_shift_null_shifts_by_at_least_a_year():
    signal, classes = _frame()
    out = null_signal(signal, "time_shift", seed=5, asset_class=classes)
    shift = next(s for s in range(252, 349) if np.allclose(np.roll(signal["A"].to_numpy(), s), out["A"].to_numpy()))
    assert 252 <= shift <= 348


def test_time_shift_null_refuses_a_series_too_short():
    signal, classes = _frame()
    with pytest.raises(ValueError, match="too short"):
        null_signal(signal.iloc[:300], "time_shift", seed=5, asset_class=classes)


def test_sign_block_reverses_directions_and_swaps_long_flat():
    signal, classes = _frame()
    out = null_signal(signal.fillna(1.0), "sign_block", seed=5, asset_class=classes)
    assert set(np.round(np.abs(out.iloc[0].to_numpy() / signal.fillna(1.0).iloc[0].to_numpy()), 9)) == {1.0}
    flat = pd.DataFrame(1.0, index=signal.index, columns=signal.columns)
    swapped = null_signal(flat, "sign_block", seed=5, asset_class=classes)
    assert set(np.unique(swapped.to_numpy())) == {0.0, 1.0}


def test_unknown_null_mode_is_refused():
    signal, classes = _frame()
    with pytest.raises(ValueError, match="unknown placebo mode"):
        null_signal(signal, "nonsense", seed=5, asset_class=classes)


def test_combination_is_causal_and_within_caps():
    panel = _panel()
    sleeves = {
        spec.id: signal_to_weights(sleeve_signal(spec, panel), panel, kind=spec.kind, rebalance_every=spec.rebalance_every)
        for spec in SPECS if spec.id in ("lowvol", "fx_mom", "bond_ts")
    }
    combined = combine_sleeves(sleeves, panel, method="inverse_vol")
    cut = list(panel.known.index)[500]
    early = combine_sleeves({name: {d: r for d, r in rows.items() if d <= cut} for name, rows in sleeves.items()}, panel.truncated(cut), method="inverse_vol")

    assert combined
    for date in [d for d in early if d <= cut][-5:]:
        assert early[date] == pytest.approx(combined[date])
    for row in combined.values():
        assert sum(abs(value) for value in row.values()) <= 1.4 + 1e-9


def test_combination_by_hierarchical_risk_parity_runs():
    panel = _panel()
    sleeves = {
        spec.id: signal_to_weights(sleeve_signal(spec, panel), panel, kind=spec.kind, rebalance_every=spec.rebalance_every)
        for spec in SPECS if spec.id in ("lowvol", "fx_mom", "bond_ts")
    }
    assert combine_sleeves(sleeves, panel, method="hrp")
