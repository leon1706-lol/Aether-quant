"""scripts/v664_register_observers.py: the observers are chosen by the pre-registered rule alone, and their universe is stated and built from public data (V6.6.4)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v664_register_observers as observers  # noqa: E402

SCORES = {"x01": {"sharpe": 0.57}, "x03": {"sharpe": 0.90}, "x09": {"sharpe": 0.88}, "x10": {"sharpe": 0.82}, "x12": {"sharpe": 0.65}, "x13": {"sharpe": 0.95}, "x14": {"sharpe": 0.80}, "c1": {"sharpe": 2.0}, "x02": {"sharpe": None}}


def test_the_three_highest_that_a_live_feed_can_compute_are_chosen_and_a_tie_goes_to_the_lower_number():
    assert observers.select_observers(SCORES) == ["x10", "x14", "x12"], "x03, x09, x13 need volume, funding or a fitted model; c1 is not an x-trial; a missing Sharpe is skipped"
    assert observers.select_observers({"x05": {"sharpe": 0.5}, "x02": {"sharpe": 0.5}, "x01": {"sharpe": 0.5}, "x07": {"sharpe": 0.4}}) == ["x01", "x02", "x05"]


def test_every_signal_the_feed_computes_is_in_the_closed_builder_set_and_the_others_say_why():
    from portfolio.crypto_signals import FORWARD_BUILDERS

    def builders(spec):
        return [spec["builder"]] if "builder" in spec else [name for part in spec["rank_mean"] for name in builders(part)]

    for trial, (_, _, signal, _) in observers.SIGNALS.items():
        assert set(builders(signal)) <= set(FORWARD_BUILDERS), trial
    assert set(observers.NOT_FROM_MARKS) == {"x03", "x04", "x09", "x13"} and not set(observers.NOT_FROM_MARKS) & set(observers.SIGNALS)


def test_the_universe_is_the_most_traded_online_usd_coins_with_a_full_history():
    products = [
        {"id": "BTC-USD", "quote_currency": "USD", "status": "online"}, {"id": "ETH-USD", "quote_currency": "USD", "status": "online"},
        {"id": "NEW-USD", "quote_currency": "USD", "status": "online"}, {"id": "OLD-USD", "quote_currency": "USD", "status": "delisted"},
        {"id": "HALT-USD", "quote_currency": "USD", "status": "online", "trading_disabled": True}, {"id": "BTC-EUR", "quote_currency": "EUR", "status": "online"},
    ]
    volume = {"BTC-USD": 9e9, "ETH-USD": 5e9, "NEW-USD": 8e9, "OLD-USD": 7e9, "HALT-USD": 6e9}
    bars = {"BTC-USD": 300, "ETH-USD": 300, "NEW-USD": 40, "OLD-USD": 300, "HALT-USD": 300}
    assert observers.rank_coins(products, volume, bars) == ["BTCUSD", "ETHUSD"]
    assert observers.rank_coins(products, volume, bars, size=1) == ["BTCUSD"]


def test_a_stablecoin_is_left_out_by_name_or_by_a_price_pinned_to_one_dollar():
    assert observers.looks_like_a_stablecoin("USDT-USD", [1.0, 1.001]) and observers.looks_like_a_stablecoin("NEWSTABLE-USD", [1.0, 1.002, 0.999, 1.001])
    assert not observers.looks_like_a_stablecoin("BTC-USD", [60000.0, 61000.0]) and not observers.looks_like_a_stablecoin("ODD-USD", [0.9, 1.1, 1.0, 1.05])
    products = [{"id": "USDT-USD", "quote_currency": "USD", "status": "online"}, {"id": "BTC-USD", "quote_currency": "USD", "status": "online"}]
    assert observers.rank_coins(products, {"USDT-USD": 9e12, "BTC-USD": 1e9}, {"USDT-USD": 300, "BTC-USD": 300}, stable={"USDT-USD"}) == ["BTCUSD"]


def test_a_definition_is_a_crypto_signal_with_a_runnable_shape():
    from evaluation.generation_ledger import decide_generation
    from portfolio.premia_signals import ResearchPanel

    import numpy as np
    import pandas as pd

    tickers = [f"C{i:02d}USD" for i in range(12)]
    definition = observers.build_definition("x14", tickers, "2026-11-06")
    assert definition["family"] == "crypto_signal" and definition["params"]["top_k"] == 10 and definition["rebalance_every"] == 20
    days = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-01", periods=300)]
    rng = np.random.default_rng(2)
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.03, (300, 12)), axis=0)), index=days, columns=tickers)
    known["BTCUSD"] = known["C00USD"]
    panel = ResearchPanel(known, {name: "crypto" for name in known.columns}, {}, {})
    weights = decide_generation(definition, panel, days[-1])
    assert all(weight >= 0.0 for weight in weights.values()) and sum(abs(weight) for weight in weights.values()) <= 0.15 + 1e-9


def test_k09_needs_a_host_and_the_definition_hash_is_stable():
    from evaluation.forward_ledger import definition_sha256

    first, second = observers.k09_definition("2026-11-06"), observers.k09_definition("2026-11-06")
    assert definition_sha256(first) == definition_sha256(second) and first["params"]["table"] == "k09" and not first["tickers"]


def test_the_real_rule_file_names_the_same_selection():
    import json

    text = json.loads((ROOT / "ml" / "evaluation" / "v664" / "observers.json").read_text(encoding="utf-8")) if (ROOT / "ml" / "evaluation" / "v664" / "observers.json").exists() else None
    if text is None:
        pytest.skip("the observers rule is not in this checkout")
    assert "highest pooled Sharpe" in text["rule"] and "tier none" in text["rule"]
