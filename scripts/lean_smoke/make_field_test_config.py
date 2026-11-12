"""The configs of the field test (V6.6.5, #351): Lean's launcher config for main.py under `live-paper` with a FakeDataQueue
(the live-plumbing one), and a project config that trades two coins at minute resolution in paper mode with the field-test
plan on. Both are written outside the repo; lean.json and config.json are read, never changed.

    python scripts/lean_smoke/make_field_test_config.py --lean-json lean.json --out launcher.json --project-config <project>/config.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_live_plumbing_config import launcher_config  # noqa: E402

COINS = ("BTCUSD", "ETHUSD")
PLAN = {
    "enabled": True,
    "order_after_bars": 3,
    "target_weights": {"BTCUSD": 0.30, "ETHUSD": 0.20},
    "drift_after_bars": 8,
    "drift_symbol": "BTCUSD",
    "drift_weight": 0.20,
    "shock_after_bars": 14,
    "drawdown_shock_pct": 0.05,
}


def project_config(config: dict, coins: tuple[str, ...] = COINS) -> dict:
    """Two coins (crypto trades on a Sunday), one-minute bars, paper mode on Lean's paper brokerage, the plan on."""
    config = copy.deepcopy(config)
    universe = config["phase1"]["universe"]
    universe["assets"] = [asset for asset in universe["assets"] if asset["ticker"] in coins]
    universe["resolution"] = "Minute"
    config.setdefault("runtime", {})["warmup_bars"] = 1
    phase_v2 = config["phase_v2"]
    # paper orders need allow_live_orders; they go to Lean's simulated PaperBrokerage, never a venue
    phase_v2["runtime"] = {"mode": "paper", "allow_live_orders": True}
    paper = phase_v2.setdefault("paper_trading", {})
    paper.update({"brokerage": "lean_paper_brokerage", "live_data_provider_configured": True, "manual_review_confirmed": True})
    target = phase_v2.setdefault("target_weights", {})
    target["enabled"] = True
    target["live_reload"] = False
    target["min_trade_usd"] = 1.0
    kill = phase_v2.setdefault("risk", {}).setdefault("kill_switch", {})
    kill.update({"enabled": True, "max_drawdown_velocity_pct_per_bar": 0.02, "trip_confirm_bars": 1, "action": "trade_lock"})
    reconciliation = phase_v2.setdefault("reconciliation", {})
    reconciliation.update({"enabled": True, "trips_kill_switch": False, "max_tolerated_drift": 0.05})
    phase_v2.setdefault("diagnostics", {})["field_test"] = dict(PLAN)
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lean-json", default="lean.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-config", required=True, help="the copy of config.json inside the temp project; rewritten in place")
    args = parser.parse_args()
    lean = json.loads(Path(args.lean_json).read_text(encoding="utf-8"))
    Path(args.out).write_text(json.dumps(launcher_config(lean), indent=1), encoding="utf-8", newline="\n")
    project = Path(args.project_config)
    project.write_text(json.dumps(project_config(json.loads(project.read_text(encoding="utf-8"))), indent=1), encoding="utf-8", newline="\n")
    print(f"wrote {args.out} and the field-test project config {args.project_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
