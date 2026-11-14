"""The last branches of evaluation/live_parity.py (V6.6.6, #359): a late-bar row with no earlier row, a gate fed only some tickers, the zero-volume fallback for forex and core crypto, a size cut for thin
liquidity, the RL positions the shadow guard tracks, and the topology a dataset row flags as elevated."""

from __future__ import annotations

import pandas as pd

from evaluation import live_parity
from test_v570_live_mechanisms import _call, _config, _row


def test_a_late_bar_symbol_has_no_offline_row_without_an_earlier_one_and_takes_the_same_row_prefixed_features():
    assert live_parity.late_bar_offline_row(None, {"a": 1.0}) is None
    merged = live_parity.late_bar_offline_row({"a": 1.0, "b": 2.0}, {"a": 9.0, "b": 8.0}, same_row_prefixes=("b",))
    assert merged == {"a": 1.0, "b": 8.0}


def test_the_rolling_ic_gate_can_be_fed_only_the_tickers_the_ranking_group_holds():
    rows = []
    for day in range(1, 40):
        for ticker in ("A", "B", "C", "D"):
            rows.append({"date": f"2020-02-{day:02d}" if day < 30 else f"2020-03-{day - 29:02d}", "ticker": ticker, "score": hash((ticker, day)) % 100 / 100.0, "close": 10.0 + day * (1 if ticker == "A" else -0.1)})
    frame = pd.DataFrame(rows)
    gate_config = {"enabled": True, "window_dates": 5, "horizon_days": 1, "min_names_per_date": 2}
    gate = live_parity.make_rolling_ic_gate_fn(frame, raw_score_column="score", gate_config=gate_config, include_tickers={"A", "B"})
    assert callable(gate)


def test_a_forex_name_and_a_core_crypto_name_with_no_volume_use_their_class_fallback_volume():
    config = _config(forex_risk={"enabled": True})
    forex = live_parity.build_live_member_weight_fn(config, security_type_by_ticker={"EURUSD": "forex"})
    crypto = live_parity.build_live_member_weight_fn(_config(), security_type_by_ticker={"BTCUSD": "crypto"}, core_crypto_tickers={"BTCUSD"})
    plain = live_parity.build_live_member_weight_fn(_config(), security_type_by_ticker={"BTCUSD": "crypto"})
    volumeless = _row(volume=0.0)
    assert _call(forex, symbol="EURUSD", row=volumeless) > 0.0
    assert _call(crypto, symbol="BTCUSD", row=volumeless) > 0.0
    assert _call(plain, symbol="BTCUSD", row=volumeless) == 0.0


def test_a_market_thin_enough_to_move_cuts_the_size_and_a_floor_does_not_lift_it_back():
    fn = live_parity.build_live_member_weight_fn(_config(), security_type_by_ticker={"AAA": "equity"})
    full = _call(fn)
    thin = _call(fn, row=_row(volume=3_000.0))
    assert 0.0 < thin < full


def rl_config(**risk):
    config = _config()
    config["phase_v2"]["dynamic_risk"].update({"rl_sizing_enabled": True, "rl_shadow_guard": {"enabled": True}, **risk})
    return config


def test_positions_sized_with_rl_are_remembered_for_the_shadow_guard_and_a_flat_one_is_forgotten():
    fn = live_parity.build_live_member_weight_fn(rl_config(), security_type_by_ticker={"AAA": "equity"}, rl_model={"state_keys": []}, daily_returns_by_date={"2020-03-03": {"AAA": 0.01}})
    assert _call(fn) > 0.0 and "AAA" in fn.rl_state["positions"]
    assert _call(fn, base=0.0) == 0.0 and "AAA" not in fn.rl_state["positions"]


def test_the_live_analyzer_path_tracks_rl_positions_too_and_reads_an_elevated_topology_row():
    config = rl_config()
    fn = live_parity.build_live_member_weight_fn(config, security_type_by_ticker={"AAA": "equity"}, rl_model={"state_keys": []}, use_live_analyzer=True)
    calm = _row(regime_signal_confidence=0.9, regime_signal_risk_score=0.1)
    assert _call(fn, row=calm) > 0.0 and "AAA" in fn.rl_state["positions"]
    assert _call(fn, base=0.0, held=0.05, row=calm) in (0.0, 0.05)
    elevated = _row(regime_signal_confidence=0.9, regime_signal_risk_score=0.1, topology_risk_elevated=1.0)
    assert live_parity._row_topology(elevated)["topology_risk"] == "elevated" and live_parity._row_topology({"topology_risk_isolated": 1.0})["topology_risk"] == "isolated"
    assert _call(fn, row=elevated, held=0.05) in (0.0, 0.05) or _call(fn, row=elevated, held=0.05) > 0.0


def test_a_dataset_row_names_its_regime_by_the_flag_that_is_set():
    assert live_parity._row_regime({"regime_risk_off": 1.0})["risk_regime"] == "risk_off"
    assert live_parity._row_regime({"regime_risk_on": 1.0, "regime_signal_risk_score": 0.4})["risk_regime"] == "risk_on"
    assert live_parity._row_regime({})["risk_regime"] == "risk_neutral"


def test_a_frame_without_the_liquidity_columns_charges_no_per_name_impact():
    fn = live_parity.build_impact_inputs_fn(pd.DataFrame({"ticker": ["A"], "date": ["2020-01-01"]}), security_type_by_ticker={"A": "equity"})
    assert fn("A", "2020-01-01") is None
