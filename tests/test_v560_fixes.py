"""V5.6.0 round file: cross-module regressions committed together with their fixes (AGENTS.md).

Pure-function coverage lives next to each module (test_cost_model.py, test_cross_asset_timing.py, ...); this file pins
the wiring a unit test cannot reach because main.py only runs inside Lean.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")


def test_crypto_gets_leans_coinbase_fee_model_only_when_the_config_asks_for_it():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    crypto_fee = config["phase_v2"]["costs"]["fee_by_type"]["crypto"]
    assert crypto_fee["model"] == "coinbase" and crypto_fee["fee_bps"] >= 0.0 and crypto_fee["min_usd"] == 0.0
    assert "CoinbaseFeeModel()" in MAIN_SOURCE
    block = MAIN_SOURCE[MAIN_SOURCE.index("fee_by_type") - 400 : MAIN_SOURCE.index("CoinbaseFeeModel()") + 80]
    assert '"coinbase"' in block, "the fee model must stay behind the config switch"


def test_the_live_net_edge_gate_is_told_the_security_type_so_crypto_pays_its_exchange_fee():
    tree = ast.parse(MAIN_SOURCE)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "build_net_edge_decision"
    ]
    assert calls and all(any(keyword.arg == "security_type" for keyword in call.keywords) for call in calls)


def test_every_offline_simulator_entry_point_receives_the_same_per_class_fees():
    for relative in ("aq_cli.py", "train.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "commission_bps_by_ticker" in source, f"{relative} builds simulator kwargs without the per-class fee"


def test_main_builds_cross_asset_inputs_from_the_shared_function():
    assert "cross_asset_inputs(" in MAIN_SOURCE
    assert "def _build_topology_payload" in MAIN_SOURCE
    body = MAIN_SOURCE[MAIN_SOURCE.index("def _build_topology_payload") : MAIN_SOURCE.index("def _build_macro_payload")]
    assert "returns_by_symbol, momentum_by_symbol = cross_asset_inputs(" in body, "live and offline must share one window/return/momentum construction"


def test_forex_trading_is_off_and_the_cross_asset_inputs_it_feeds_stay_on():
    """Two consecutive Lean runs lost money on forex after fees (-$425 and -$507 on ~$0 gross: IB's $2 minimum on ~$2k
    positions is ~8 bps a fill). The flag only zeroes forex SIZING and liquidates forex positions; forex bars still
    flow into the cross-asset windows the topology/peer/macro features read, so no feature changes."""
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assert config["phase_v2"]["forex_risk"]["enabled"] is False
    assert any(asset["security_type"] == "forex" for asset in config["phase1"]["universe"]["assets"])
    assert config["phase_v2"]["costs"]["fee_by_type"]["forex"]["min_usd"] == 2.0


def test_live_book_candidates_and_offline_metadata_share_the_asset_class_gate():
    """Forex trading is off, so forex pairs must not occupy book slots live OR in the as-live simulation."""
    from aq_cli import _universe_asset_metadata

    assert "book_candidate_trading_eligible(" in MAIN_SOURCE
    config = {
        "phase1": {"universe": {"assets": [
            {"ticker": "ZZEQ", "security_type": "equity"}, {"ticker": "ZZFX", "security_type": "forex"},
        ]}},
        "phase_v2": {"forex_risk": {"enabled": False}},
    }
    _classes, eligible = _universe_asset_metadata(config)
    assert eligible["ZZEQ"] is True and eligible["ZZFX"] is False
    config["phase_v2"]["forex_risk"]["enabled"] = True
    assert _universe_asset_metadata(config)[1]["ZZFX"] is True
