"""portfolio/crypto_signals.py: hand-computed cases, and the rule that a changed future bar changes no earlier row (V6.6.4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio import crypto_signals as cs

DAYS = [day.strftime("%Y-%m-%d") for day in pd.date_range("2021-01-01", periods=420)]
COINS = ["BTCUSD", "ETHUSD", "AAAUSD", "BBBUSD", "CCCUSD", "DDDUSD"]


def _panel(seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0005, 0.03, (len(DAYS), len(COINS))) * np.linspace(0.6, 1.6, len(COINS))
    return pd.DataFrame(100.0 * np.exp(np.cumsum(steps, axis=0)), index=DAYS, columns=COINS)


def _volume(seed: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(np.exp(rng.normal(15.0, 0.5, (len(DAYS), len(COINS)))), index=DAYS, columns=COINS)


def _funding(seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(0.0003, 0.0004, (len(DAYS), len(COINS))), index=DAYS, columns=COINS)


def _liquid(known: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(True, index=known.index, columns=known.columns)


KNOWN, VOLUME, FUNDING = _panel(), _volume(), _funding()

CASES = {
    "low_vol": lambda k, v, f: cs.low_vol(k),
    "lottery_max": lambda k, v, f: cs.lottery_max(k),
    "amihud": lambda k, v, f: cs.amihud(k, v),
    "volume_trend": lambda k, v, f: cs.volume_trend(v),
    "high_proximity": lambda k, v, f: cs.high_proximity(k),
    "short_reversal": lambda k, v, f: cs.short_reversal(k),
    "low_beta": lambda k, v, f: cs.low_beta(k),
    "idio_vol": lambda k, v, f: cs.idio_vol(k),
    "trend_votes": lambda k, v, f: cs.trend_votes(k),
    "funding_filtered_trend": lambda k, v, f: cs.funding_filtered_trend(k, f),
    "breadth_timing": lambda k, v, f: cs.breadth_timing(k, _liquid(k)),
    "core_constant": lambda k, v, f: cs.core_constant(k),
    "regime_gate": lambda k, v, f: cs.regime_gate(cs.low_vol(k), k),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_changed_future_bar_changes_no_earlier_row(name):
    cut = 300
    changed_known, changed_volume, changed_funding = KNOWN.copy(), VOLUME.copy(), FUNDING.copy()
    changed_known.iloc[cut:] *= 3.7
    changed_volume.iloc[cut:] *= 0.2
    changed_funding.iloc[cut:] += 0.01
    before = CASES[name](KNOWN, VOLUME, FUNDING).iloc[:cut]
    after = CASES[name](changed_known, changed_volume, changed_funding).iloc[:cut]
    pd.testing.assert_frame_equal(before, after)


@pytest.mark.parametrize("name", sorted(CASES))
def test_no_infinity_and_a_window_not_yet_full_is_nan(name):
    table = CASES[name](KNOWN, VOLUME, FUNDING)
    assert not np.isinf(table.to_numpy(dtype=float)).any()
    assert table.shape == KNOWN.shape
    if name != "core_constant":  # a constant hold needs only a price
        assert table.iloc[:5].isna().all().all(), "no signal may exist before its window has any history"


def test_nan_and_inf_inputs_never_become_numbers():
    known = KNOWN.copy()
    known.iloc[100:110, 2] = np.nan
    known.iloc[200, 3] = np.inf
    volume = VOLUME.copy()
    volume.iloc[:, 4] = 0.0
    for name, build in CASES.items():
        table = build(known, volume, FUNDING)
        assert not np.isinf(table.to_numpy(dtype=float)).any(), name
    assert cs.amihud(known, volume)["CCCUSD"].isna().all(), "a coin with no volume has no illiquidity figure"
    assert cs.low_vol(known).iloc[105, 2] != cs.low_vol(known).iloc[105, 2], "a gap in the prices leaves the window short, so NaN"


def test_empty_input_returns_an_empty_table():
    empty = pd.DataFrame(columns=COINS, dtype=float)
    assert cs.low_vol(empty).empty and cs.high_proximity(empty).empty


def test_low_vol_ranks_the_calmer_coin_higher():
    index = DAYS[:80]
    calm = 100.0 * 1.001 ** np.arange(80)
    wild = 100.0 * np.exp(np.cumsum(np.tile([0.05, -0.05], 40)))
    table = cs.low_vol(pd.DataFrame({"CALM": calm, "WILD": wild}, index=index))
    assert table.iloc[-1]["CALM"] > table.iloc[-1]["WILD"]
    assert abs(table.iloc[-1]["CALM"]) < 1e-12


def test_lottery_max_punishes_the_single_best_day():
    index = DAYS[:60]
    base = 100.0 * 1.001 ** np.arange(60)
    jumpy = base.copy()
    jumpy[40:] *= 1.5
    table = cs.lottery_max(pd.DataFrame({"BASE": base, "JUMPY": jumpy}, index=index), window=30)
    assert table.iloc[-1]["BASE"] > table.iloc[-1]["JUMPY"]
    assert table.iloc[-1]["JUMPY"] == pytest.approx(-(1.5 * 1.001 - 1.0), abs=1e-9)


def test_short_reversal_and_high_proximity_by_hand():
    known = pd.DataFrame({"X": [100.0, 110.0, 121.0, 100.0]}, index=DAYS[:4])
    assert cs.short_reversal(known, 2).iloc[2]["X"] == pytest.approx(-0.21)
    assert cs.short_reversal(known, 2).iloc[3]["X"] == pytest.approx(-(100.0 / 110.0 - 1.0))
    top = cs.high_proximity(known, window=4, min_periods=2)
    assert top.iloc[2]["X"] == 1.0 and top.iloc[3]["X"] == pytest.approx(100.0 / 121.0)


def test_trend_votes_count_the_lookbacks_that_are_positive():
    rising = pd.DataFrame({"UP": 100.0 * 1.01 ** np.arange(200), "DOWN": 100.0 * 0.99 ** np.arange(200)}, index=[f"d{i:03d}" for i in range(200)])
    votes = cs.trend_votes(rising)
    assert votes["UP"].iloc[:120].isna().all() and votes["UP"].iloc[-1] == 1.0 and votes["DOWN"].iloc[-1] == 0.0
    path = np.full(181, 100.0)
    path[:61] = 200.0
    path[170:] = 150.0  # up on the 20- and 60-row lookbacks, down on the 120-row one
    mixed = pd.DataFrame({"M": path}, index=[f"d{i:03d}" for i in range(181)])
    assert cs.trend_votes(mixed, (20, 60, 120))["M"].iloc[-1] == pytest.approx(2.0 / 3.0)


def test_funding_filter_flattens_a_crowded_coin_and_missing_funding_changes_nothing():
    index = [f"d{i:03d}" for i in range(400)]
    known = pd.DataFrame({"HOT": 100.0 * 1.003 ** np.arange(400), "COOL": 100.0 * 1.003 ** np.arange(400)}, index=index)
    funding = pd.DataFrame({"HOT": np.r_[np.full(390, 0.0001), np.full(10, 0.01)], "COOL": np.full(400, 0.0001)}, index=index)
    out = cs.funding_filtered_trend(known, funding)
    assert out["HOT"].iloc[-1] == 0.0 and out["COOL"].iloc[-1] == 1.0
    pd.testing.assert_frame_equal(cs.funding_filtered_trend(known, None), cs.trend_votes(known))
    pd.testing.assert_frame_equal(cs.funding_filtered_trend(known, pd.DataFrame()), cs.trend_votes(known))


def test_breadth_timing_follows_the_liquid_coins():
    index = [f"d{i:03d}" for i in range(120)]
    up = pd.DataFrame({name: 100.0 * 1.01 ** np.arange(120) for name in [f"C{i}USD" for i in range(12)] + ["BTCUSD", "ETHUSD"]}, index=index)
    assert cs.breadth_timing(up, _liquid(up)).iloc[-1][["BTCUSD", "ETHUSD"]].eq(1.0).all()
    down = up.iloc[::-1].reset_index(drop=True).set_index(pd.Index(index))
    table = cs.breadth_timing(down, _liquid(down))
    assert table.iloc[-1][["BTCUSD", "ETHUSD"]].eq(0.0).all() and table.drop(columns=["BTCUSD", "ETHUSD"]).isna().all().all()


def test_regime_gate_leaves_no_signal_when_btc_is_below_its_average_and_the_book_goes_flat():
    index = [f"d{i:03d}" for i in range(300)]
    btc = np.r_[100.0 * 1.005 ** np.arange(200), 100.0 * 1.005 ** 199 * 0.97 ** np.arange(100)]
    known = pd.DataFrame({"BTCUSD": btc, "AAAUSD": btc, "BBBUSD": btc[::-1]}, index=index)
    table = pd.DataFrame(1.0, index=index, columns=known.columns)
    gated = cs.regime_gate(table, known, window=100)
    assert gated.iloc[150].eq(1.0).all() and gated.iloc[-1].isna().all() and gated.iloc[:99].isna().all().all()

    from portfolio.premia_signals import XS, ResearchPanel, WeightSettings, signal_to_weights

    panel = ResearchPanel(known, {name: "crypto" for name in known.columns}, {}, {})
    weights = signal_to_weights(gated, panel, kind=XS, rebalance_every=5, settings=WeightSettings(), start=index[100], end=index[-1])
    assert weights[index[-1] if index[-1] in weights else max(weights)] == {}, "an empty signal row is a flat book"


# --- the forward feed: round 4C's trials from marks alone ----------------------------------------------------------------------

def test_forward_table_builds_a_single_signal_a_composite_and_a_gated_one_from_marks_alone():
    single = cs.forward_table({"builder": "low_vol", "params": {"window": 30}}, KNOWN)
    pd.testing.assert_frame_equal(single, cs.low_vol(KNOWN, 30))
    composite = cs.forward_table({"rank_mean": [{"builder": "low_vol"}, {"builder": "lottery_max"}, {"builder": "high_proximity"}], "minimum": 3, "gate": "regime"}, KNOWN)
    assert composite.shape == KNOWN.shape and composite.notna().any().any() and composite.isna().all(axis=1).any(), "the gate switches whole rows off"
    wide = pd.concat([KNOWN, _panel(9).rename(columns=lambda name: f"X{name}")], axis=1)  # breadth needs ten coins to read
    breadth = cs.forward_table({"builder": "breadth_timing", "params": {"window": 50}}, wide)
    assert set(breadth.columns[breadth.notna().any()]) == {"BTCUSD", "ETHUSD"}
    assert cs.forward_table({"builder": "breadth_timing"}, KNOWN).isna().all().all(), "six coins are too few to read breadth"


def test_forward_table_refuses_a_builder_outside_the_closed_set():
    import pytest

    with pytest.raises(KeyError):
        cs.forward_table({"builder": "os.system"}, KNOWN)
    with pytest.raises(KeyError):
        cs.forward_table({"builder": "amihud"}, KNOWN)  # needs volume, which the forward feed does not hold


def test_a_changed_future_mark_changes_no_earlier_forward_table_row():
    spec = {"rank_mean": [{"builder": "low_vol"}, {"builder": "high_proximity"}], "minimum": 2, "gate": "regime"}
    changed = KNOWN.copy()
    changed.iloc[300:] *= 3.1
    pd.testing.assert_frame_equal(cs.forward_table(spec, KNOWN).iloc[:300], cs.forward_table(spec, changed).iloc[:300])


def test_a_crypto_signal_generation_decides_through_the_ledger_and_other_families_are_untouched():
    from evaluation.generation_ledger import decide_generation
    from portfolio.premia_signals import ResearchPanel

    definition = {
        "id": "obs", "kind": "time_series", "family": "crypto_signal", "universe": ["crypto"], "rebalance_every": 5, "settings": {},
        "params": {"signal": {"builder": "breadth_timing", "params": {"window": 50, "floor": 0.5}}},
    }
    wide = pd.concat([KNOWN, _panel(9).rename(columns=lambda name: f"X{name}")], axis=1)
    classes = {coin: "crypto" for coin in wide.columns}
    panel = ResearchPanel(wide, classes, {}, {})
    day = wide.index[-1]
    weights = decide_generation(definition, panel, day)
    assert set(weights) <= {"BTCUSD", "ETHUSD"} and all(0.0 <= weight <= 0.05 + 1e-9 for weight in weights.values())
    assert decide_generation(definition, panel, day) == weights, "the same marks decide the same weights"
