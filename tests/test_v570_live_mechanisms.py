"""V5.7.0 offline/live parity mechanisms: the simulator's kill switch, member-weight hook, HRP weights hook, per-name
impact and minimum-commission top-up, plus the live_parity builders that wire them from the live config. Synthetic frames;
every mechanism must leave the default run byte-identical."""

import numpy as np
import pandas as pd
import pytest

from evaluation.live_parity import (
    build_as_live_kwargs,
    build_hrp_raw_weights_fn,
    build_impact_inputs_fn,
    build_live_member_weight_fn,
    build_live_mechanisms,
)
from evaluation.rank_book_simulator import simulate_rank_book
from portfolio.book_construction import BookAllocation

NUM_TICKERS = 30
NUM_DATES = 90


def _frame(seed=11, signal_strength=0.01) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [str(d.date()) for d in pd.bdate_range("2020-01-01", periods=NUM_DATES)]
    rows = []
    for date_index, date in enumerate(dates):
        for ticker_index in range(NUM_TICKERS):
            score = float(rng.normal())
            rows.append(
                {
                    "date": date,
                    "ticker": f"T{ticker_index:02d}",
                    "pred": score,
                    "target_return_1d": score * signal_strength + float(rng.normal(0, 0.005)),
                    "close": 100.0 + ticker_index + 0.1 * date_index,
                    "volume": 1_000_000.0,
                    "rolling_volatility_20d": 0.015,
                    "liquidity_log_dollar_volume": float(np.log1p(5e7)),
                    "liquidity_spread_proxy": 0.0005,
                    "regime_risk_off": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _kwargs(**overrides) -> dict:
    kwargs = dict(
        prediction_column="pred", top_n=5, bottom_n=5, rebalance_every_bars=10, cost_bps_per_side=0.0, commission_bps=0.0,
        gross_exposure=1.0, dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.12, min_universe_size=20,
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------- defaults are untouched


def test_every_new_argument_defaults_to_the_previous_behaviour():
    frame = _frame()
    baseline = simulate_rank_book(frame, **_kwargs())
    explicit = simulate_rank_book(
        frame,
        **_kwargs(
            kill_switch_config=None, kill_switch_sticky=False, member_weight_fn=None, raw_weights_fn=None,
            impact_inputs_fn=None, min_commission_usd_by_ticker=None, hysteresis_anchor_on_formed_book=None,
        ),
    )
    assert baseline.per_date_net_return == explicit.per_date_net_return
    assert baseline.num_kill_switch_locked_dates == 0 and baseline.num_kill_switch_frozen_decisions == 0


# ---------------------------------------------------------------- kill switch


ALWAYS_TRIPPED = {"enabled": True, "evaluation_bars": 2, "min_rolling_sharpe": 1e9, "min_return_std_for_sharpe": 0.0}


def test_a_tripped_kill_switch_freezes_members_after_the_first_rebalance():
    frame = _frame()
    free = simulate_rank_book(frame, **_kwargs(entry_lag_bars=1))
    locked = simulate_rank_book(frame, **_kwargs(entry_lag_bars=1, kill_switch_config=ALWAYS_TRIPPED))
    assert locked.num_kill_switch_locked_dates > 0
    assert locked.num_kill_switch_frozen_decisions > 0
    # the first rebalance happens before any return history exists; every later one is frozen -> far less turnover
    assert locked.annualized_turnover < free.annualized_turnover
    # exits still pass (names the new book dropped are sold) but nothing new is bought: the book only shrinks
    assert 0.0 < locked.mean_names_long < free.mean_names_long


def test_a_disabled_or_never_tripping_kill_switch_changes_nothing():
    frame = _frame(signal_strength=0.05)
    baseline = simulate_rank_book(frame, **_kwargs(entry_lag_bars=1))
    disabled = simulate_rank_book(frame, **_kwargs(entry_lag_bars=1, kill_switch_config=dict(ALWAYS_TRIPPED, enabled=False)))
    lenient = simulate_rank_book(
        frame, **_kwargs(entry_lag_bars=1, kill_switch_config=dict(ALWAYS_TRIPPED, min_rolling_sharpe=-1e9))
    )
    assert baseline.per_date_net_return == disabled.per_date_net_return == lenient.per_date_net_return
    assert lenient.num_kill_switch_locked_dates == 0


def test_a_sticky_kill_switch_stays_locked_after_a_single_trip():
    frame = _frame()
    one_shot = {"enabled": True, "evaluation_bars": 5, "min_rolling_sharpe": -1e9, "max_consecutive_losses": 1,
                "min_return_std_for_sharpe": 0.0}
    sticky = simulate_rank_book(frame, **_kwargs(entry_lag_bars=1, kill_switch_config=one_shot, kill_switch_sticky=True))
    bypass = simulate_rank_book(frame, **_kwargs(entry_lag_bars=1, kill_switch_config=one_shot, kill_switch_sticky=False))
    assert sticky.num_kill_switch_locked_dates >= bypass.num_kill_switch_locked_dates


# ---------------------------------------------------------------- member weight hook


def test_member_weight_hook_scales_weights_without_changing_selection():
    frame = _frame()
    baseline = simulate_rank_book(frame, **_kwargs())
    half = simulate_rank_book(frame, **_kwargs(member_weight_fn=lambda **kw: kw["base_weight"] * 0.5))
    assert np.allclose(np.asarray(half.per_date_net_return) * 2.0, baseline.per_date_net_return, atol=1e-12)
    assert half.mean_names_long == baseline.mean_names_long


def test_member_weight_hook_zero_blocks_entries_and_returning_the_held_weight_holds():
    frame = _frame()
    seen = []

    def block_all(**kw):
        seen.append(kw["symbol"])
        return 0.0

    blocked = simulate_rank_book(frame, **_kwargs(member_weight_fn=block_all))
    assert seen and blocked.mean_names_long == 0.0

    def hold(**kw):
        return kw["held_weight"] if kw["held_weight"] != 0.0 else kw["base_weight"]

    held = simulate_rank_book(frame, **_kwargs(member_weight_fn=hold))
    assert held.annualized_turnover < simulate_rank_book(frame, **_kwargs()).annualized_turnover


def test_member_weight_hook_receives_the_row_and_the_percentile_rank():
    frame = _frame()
    captured = {}

    def capture(**kw):
        captured.setdefault("row", kw["row"])
        captured.setdefault("rank", kw["predicted_rank"])
        return kw["base_weight"]

    simulate_rank_book(frame, **_kwargs(member_weight_fn=capture, normalize_to_percentile=True))
    assert "rolling_volatility_20d" in captured["row"] and 0.0 <= captured["rank"] <= 1.0


def test_raw_weights_fn_replaces_the_book_raw_weights():
    frame = _frame()
    seen = []

    def equal_weights(allocations, date):
        seen.append(date)
        return {symbol: (0.05 if allocation.role == "long" else -0.05) for symbol, allocation in allocations.items()}

    result = simulate_rank_book(frame, **_kwargs(raw_weights_fn=equal_weights, gross_exposure=1.0))
    assert seen and result.mean_names_long == 5.0


# ---------------------------------------------------------------- costs


IMPACT = {"enabled": True, "eta": 0.5}


def test_per_name_impact_scales_with_participation_and_vanishes_for_deep_liquidity():
    frame = _frame()
    base = simulate_rank_book(frame, **_kwargs())
    thin = simulate_rank_book(frame, **_kwargs(impact_model_config=IMPACT, impact_inputs_fn=lambda s, d: (0.02, 1e5)))
    deep = simulate_rank_book(frame, **_kwargs(impact_model_config=IMPACT, impact_inputs_fn=lambda s, d: (0.02, 1e13)))
    assert thin.cost_drag_annual_bps > deep.cost_drag_annual_bps > base.cost_drag_annual_bps - 1e-9
    assert deep.cost_drag_annual_bps < 1.0
    unknown = simulate_rank_book(frame, **_kwargs(impact_model_config=IMPACT, impact_inputs_fn=lambda s, d: None))
    assert unknown.cost_drag_annual_bps == pytest.approx(base.cost_drag_annual_bps)


def test_legacy_impact_is_a_rate_on_traded_notional_with_the_assumed_nav():
    frame = _frame()
    config = {"enabled": True, "eta": 0.5, "daily_volatility": 0.02, "avg_daily_dollar_volume": 5e7}
    base = simulate_rank_book(frame, **_kwargs()).cost_drag_annual_bps
    default = simulate_rank_book(frame, **_kwargs(impact_model_config=config)).cost_drag_annual_bps - base
    deep = simulate_rank_book(
        frame, **_kwargs(impact_model_config=dict(config, avg_daily_dollar_volume=5e9))
    ).cost_drag_annual_bps - base
    bigger_nav = simulate_rank_book(frame, **_kwargs(impact_model_config=config, assumed_portfolio_value_usd=1e7)).cost_drag_annual_bps - base
    assert default > 0.0
    assert default / deep == pytest.approx(10.0, rel=1e-6)  # sqrt(100x participation): the rate falls 10x
    assert bigger_nav / default == pytest.approx(10.0, rel=1e-6)  # NAV 100x (100k default -> 10M): the rate rises 10x

def test_minimum_commission_top_up_only_applies_to_small_orders():
    frame = _frame()
    floors = {f"T{i:02d}": 10.0 for i in range(NUM_TICKERS)}
    base = simulate_rank_book(frame, **_kwargs(commission_bps=5.0))
    floored = simulate_rank_book(frame, **_kwargs(commission_bps=5.0, min_commission_usd_by_ticker=floors))
    huge_nav = simulate_rank_book(
        frame, **_kwargs(commission_bps=5.0, min_commission_usd_by_ticker=floors, assumed_portfolio_value_usd=1e9)
    )
    assert floored.cost_drag_annual_bps > base.cost_drag_annual_bps
    assert huge_nav.cost_drag_annual_bps == pytest.approx(base.cost_drag_annual_bps, abs=1e-9)  # rate leg exceeds the floor

# ---------------------------------------------------------------- live member weight builder


def _config(**overrides):
    config = {
        "phase6": {"risk": {"max_position_weight": 0.12, "min_confidence_to_trade": 0.0968}},
        "phase_v2": {
            "dynamic_risk": {"target_daily_volatility": 0.015, "use_predicted_volatility": False},
            "portfolio_book": {"sizing_floor_fraction": 0.5, "rank_sizing_applies_to_members": False},
            "costs": {},
            "liquidity": {"max_spread_proxy_by_type": {"equity": 0.001}, "max_round_trip_cost_fraction": 0.0025},
            "forex_risk": {"enabled": False},
        },
    }
    for key, value in overrides.items():
        config["phase_v2"][key] = value
    return config


def _row(**overrides):
    row = {"close": 100.0, "volume": 5_000_000.0, "rolling_volatility_20d": 0.015, "liquidity_spread_proxy": 0.0005, "regime_risk_off": 0.0}
    row.update(overrides)
    return row


def _call(fn, *, base=0.08, held=0.0, rank=0.97, row=None, symbol="AAA"):
    return fn(symbol=symbol, date="2020-03-02", base_weight=base, held_weight=held, predicted_rank=rank, row=row or _row())


def test_member_weight_follows_the_live_sizing_chain_and_the_book_floor():
    fn = build_live_member_weight_fn(_config(), security_type_by_ticker={"AAA": "equity"})
    calm = _call(fn)
    assert calm == pytest.approx(0.08 * 1.0 * (0.5 + 0.5 * 0.94), rel=1e-9)  # volatility multiplier 1.0, confidence 0.94
    volatile = _call(fn, row=_row(rolling_volatility_20d=0.2))
    assert volatile == pytest.approx(0.04)  # 0.35 x ... shrinks below the 0.5 floor, which holds it at half the base weight
    assert _call(fn, base=-0.08, rank=0.03) == pytest.approx(-calm)


def test_member_weight_blocks_new_entries_but_holds_existing_positions_on_a_liquidity_block():
    fn = build_live_member_weight_fn(_config(), security_type_by_ticker={"AAA": "equity"})
    no_volume = _row(volume=0.0)
    assert _call(fn, row=no_volume) == 0.0
    assert _call(fn, row=no_volume, held=0.05) == 0.05
    thin = _row(volume=10.0)  # daily dollar volume below the floor
    assert _call(fn, row=thin, held=0.06) == 0.06


def test_member_weight_net_edge_gate_vetoes_a_new_entry_only():
    costs = {"enabled": True, "edge_bps_per_rank_unit": 10.0, "min_net_edge_bps": 5.0, "commission_bps_per_side": 5.0,
             "min_commission_usd": 0.0, "holding_bars": 10, "horizon_days": 20}
    fn = build_live_member_weight_fn(_config(costs=costs), security_type_by_ticker={"AAA": "equity"})
    assert _call(fn) == 0.0
    assert _call(fn, held=0.05) > 0.0


def test_member_weight_regime_risk_off_freezes_the_position_and_low_confidence_trades_nothing():
    fn = build_live_member_weight_fn(_config(), security_type_by_ticker={"AAA": "equity"})
    assert _call(fn, row=_row(regime_risk_off=1.0), held=0.05) == 0.05
    assert _call(fn, rank=0.52, held=0.05) == 0.05  # confidence 0.04 < 0.0968
    assert _call(fn, rank=float("nan"), held=0.05) == 0.05


def test_member_weight_skips_forex_when_the_class_is_disabled():
    fn = build_live_member_weight_fn(_config(), security_type_by_ticker={"EURUSD": "forex"})
    assert _call(fn, symbol="EURUSD", held=0.03) == 0.03


# ---------------------------------------------------------------- hrp + impact inputs + wiring


def test_hrp_raw_weights_cover_the_book_and_fall_back_to_the_rank_formula_without_history():
    frame = _frame()
    fn = build_hrp_raw_weights_fn(frame, window_bars=25)
    allocations = {
        "T00": BookAllocation(role="long", predicted_rank_20d=0.99, book_role_multiplier=1.0, book_reason="test"),
        "T01": BookAllocation(role="long", predicted_rank_20d=0.97, book_role_multiplier=1.0, book_reason="test"),
        "T02": BookAllocation(role="short", predicted_rank_20d=0.02, book_role_multiplier=1.0, book_reason="test"),
        "T03": BookAllocation(role="short", predicted_rank_20d=0.04, book_role_multiplier=1.0, book_reason="test"),
    }
    weights = fn(allocations, frame["date"].iloc[-1])
    assert set(weights) == set(allocations)
    assert sum(w for w in weights.values() if w > 0) == pytest.approx(0.5, abs=1e-6)
    assert sum(w for w in weights.values() if w < 0) == pytest.approx(-0.5, abs=1e-6)
    early = fn(allocations, "1999-01-01")  # no closes yet -> equal weight inside each leg or the rank formula
    assert set(early) == set(allocations)


def test_impact_inputs_use_the_dataset_columns_and_the_class_fallback_for_volumeless_names():
    frame = _frame().head(4).copy()
    frame.loc[frame.index[0], "liquidity_log_dollar_volume"] = 0.0
    fn = build_impact_inputs_fn(frame, security_type_by_ticker={"T00": "forex", "T01": "equity"})
    volatility, adv = fn("T00", frame["date"].iloc[0])
    assert volatility == pytest.approx(0.015) and adv == pytest.approx(5e9)  # forex fallback ADV
    assert fn("T01", frame["date"].iloc[0])[1] == pytest.approx(5e7, rel=1e-6)
    assert fn("ZZZ", "2020-01-01") is None


def test_build_live_mechanisms_reads_the_config_and_include_switches_off_pieces():
    config = _config()
    config["phase_v2"]["risk"] = {"kill_switch": {"enabled": True, "min_rolling_sharpe": -1.0}}
    config["phase_v2"]["backtest"] = {"bypass_sticky_trade_lock": True}
    config["phase1"] = {"universe": {"assets": [{"ticker": "T00", "security_type": "equity"}]}}
    frame = _frame()
    mechanisms = build_live_mechanisms(config, frame)
    assert mechanisms["kill_switch_config"]["enabled"] is True and mechanisms["kill_switch_sticky"] is False
    assert callable(mechanisms["member_weight_fn"]) and callable(mechanisms["impact_inputs_fn"])
    assert "raw_weights_fn" not in mechanisms  # allocation_method defaults to rank
    config["phase_v2"]["portfolio_book"]["allocation_method"] = "hrp"
    assert callable(build_live_mechanisms(config, frame, include=("hrp",))["raw_weights_fn"])
    assert build_live_mechanisms(config, frame, include=()) == {}
    config["phase_v2"]["backtest"] = {}
    assert build_live_mechanisms(config, frame, include=("kill_switch",))["kill_switch_sticky"] is True


def test_as_live_kwargs_hold_on_veto_follows_the_config_and_forwards_the_mechanisms():
    base = _kwargs()
    marker = object()
    on = build_as_live_kwargs(
        base, book_config={"hold_owned_positions_on_veto": True}, exits_config={}, max_position_weight=0.12,
        candidate_metadata={}, member_weight_fn=marker, kill_switch_config={"enabled": True}, kill_switch_sticky=True,
    )
    off = build_as_live_kwargs(
        base, book_config={"hold_owned_positions_on_veto": False}, exits_config={}, max_position_weight=0.12, candidate_metadata={}
    )
    assert on["hold_positions_on_veto"] is True and off["hold_positions_on_veto"] is False
    assert on["member_weight_fn"] is marker and on["kill_switch_sticky"] is True and on["kill_switch_config"]["enabled"]
    assert off["hysteresis_anchor_on_formed_book"] is True and off["member_weight_fn"] is None




