"""V6.2.0 config decisions, each pinned with the decision that made it (development/Changelog.md "V6.2.0")."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
V2 = CONFIG["phase_v2"]


def test_the_t_bill_sweep_and_the_365_day_basis_ship_on_the_owners_conditional_approval():
    # D1 / D2 (2026-10-17): on if the Lean runs confirm them - BT1 / BT3 / BT2: carry +$10.7k (prediction +$10.1k),
    # Lean Sharpe +0.082, drawdown 4.30%, no buying-power rejection (Problems.md #199, #200)
    assert V2["cash_sweep"]["enabled"] is True and V2["cash_sweep"]["ticker"] == "BIL"
    assert V2["cash_sweep"]["exclude_from_risk_controls"] is True
    assert CONFIG["runtime"]["trading_days_per_year"] == 365
    assert CONFIG["runtime"]["lean_window_override"] is None  # reset after the runs


def test_the_rules_that_adopted_nothing_leave_the_v61_behaviour():
    assert V2["rolling_ic_gate"]["late_bar_event_count"] == "per_tick"  # R-DEDUPE: backtest -0.090 < +0.10 (#201)
    assert V2["model_ensemble"]["enabled"] is False  # R-MODEL10: nothing beats the yardstick (#203)
    assert V2["retraining"]["multitask_training"]["label_noise_std"] == 0.0
    assert V2["retraining"]["sequence_training"]["label_noise_std"] == 0.0
    assert "tranches" not in V2["portfolio_book"]  # R-STAGGER: no tranche book, the live path is not built (#202)
    assert V2["legacy_sleeve"]["max_gross_exposure"] == 0.05  # L2 declined by the owner


def test_the_sweep_ticker_is_never_a_universe_asset():
    tickers = {asset["ticker"] for asset in CONFIG["phase1"]["universe"]["assets"]}
    assert V2["cash_sweep"]["ticker"] not in tickers
