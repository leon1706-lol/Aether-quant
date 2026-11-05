"""A run config for main.py itself with one option asset on Lean's sample AAPL chain (V6.5.0, Problems.md #38, #58).

    python scripts/lean_smoke/make_option_main_config.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WINDOW = {"start": "2014-06-02", "end": "2014-06-30"}
KEEP = ("AAPL", "SPY", "TLT", "IEF", "HYG", "QQQ", "USO")


def option_main_config(base: dict) -> dict:
    config = copy.deepcopy(base)
    assets = [asset for asset in config["phase1"]["universe"]["assets"] if asset["ticker"] in KEEP]
    assets.append({"ticker": "AAPL_OPTION", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa",
                   "data_path": "data/option/usa/daily/aapl_2014_trade_american.zip", "available_from": "2014-06-02", "available_to": "2014-12-31"})
    config["phase1"]["universe"]["assets"] = assets
    config["runtime"]["lean_window_override"] = WINDOW
    risk = config["phase_v2"]["options_risk"]
    risk.update({"enabled": True, "spread_strategy": "vertical", "multi_leg_strategies_enabled": True, "max_vega_budget_pct_of_equity": 0.1})
    risk["arbitrage_detector"]["enabled"] = True
    config["phase_v2"]["cash_sweep"]["enabled"] = False
    config["phase_v2"]["bond_sleeve"]["enabled"] = False
    config["phase_v2"]["legacy_sleeve"]["enabled"] = True
    return config


def main() -> int:
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    path = ROOT / "ml" / "evaluation" / "run_configs" / "v650_smoke_option_main.json"
    path.write_text(json.dumps(option_main_config(base), indent=4), encoding="utf-8", newline="\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
