"""Multi-asset-class (IB/futures/options/FRED) readiness report.

Pure, read-only report builder shared by two consumers so the readiness
logic is defined exactly once: `aq_cli.py::cmd_assets()` (prints it to the
terminal) and `monitoring/api_server.py`'s `/api/assets-status` endpoint
(serves it to the webui). Computed live on every call - matches
`monitoring/neural_network_state.py::build_neural_network_state()`'s
"compute on read" precedent rather than the paper-readiness/retraining-
status pattern of a periodic worker writing a cached JSON file, since every
input here (config.json, lean.json, the local FRED cache file, the static
futures contract specs file) is a cheap local read, not a heavy computation
worth caching.
"""

from __future__ import annotations

from pathlib import Path

from data_pipeline.fred_backfill import load_cached_fred_series
from data_pipeline.ib_backfill import ib_readiness_status, load_futures_contract_specs
from risk.forex_risk import load_forex_pair_specs

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"
LEAN_JSON_PATH = ROOT_DIR / "lean.json"


def build_assets_status(config: dict, lean_config: dict) -> dict:
    """Returns the same facts `aq assets status` prints, as a JSON-safe
    dict: IB readiness tri-state, futures/options feature flags, futures
    contract specs loaded, FRED yield-curve cache freshness, and how many
    futures/options assets are configured in the universe."""
    phase_v2 = config.get("phase_v2", {})
    specs = load_futures_contract_specs()
    forex_specs = load_forex_pair_specs()
    fred_series = load_cached_fred_series()
    all_dates = [row["date"] for rows in fred_series.values() for row in rows]
    assets = config.get("phase1", {}).get("universe", {}).get("assets", [])

    return {
        "ib_status": ib_readiness_status(config, lean_config),
        "futures_risk_enabled": bool(phase_v2.get("futures_risk", {}).get("enabled", False)),
        "options_risk_enabled": bool(phase_v2.get("options_risk", {}).get("enabled", False)),
        # V4.6 - Forex/FX, same reporting shape as futures above.
        "forex_risk_enabled": bool(phase_v2.get("forex_risk", {}).get("enabled", False)),
        "futures_contract_specs_loaded": len(specs),
        "futures_contract_specs_tickers": sorted(specs),
        "forex_pair_specs_loaded": len(forex_specs),
        "forex_pair_specs_tickers": sorted(forex_specs),
        "fred_cache_series_count": len(fred_series),
        "fred_cache_most_recent_date": max(all_dates).isoformat() if all_dates else None,
        "configured_futures_assets": sum(
            1 for asset in assets if (asset.get("asset_class") or asset.get("security_type")) == "future"
        ),
        "configured_options_assets": sum(
            1 for asset in assets if (asset.get("asset_class") or asset.get("security_type")) == "option"
        ),
        "configured_forex_assets": sum(
            1 for asset in assets if (asset.get("asset_class") or asset.get("security_type")) == "forex"
        ),
    }


def build_assets_status_from_disk() -> dict:
    """Convenience wrapper reading config.json/lean.json from their
    canonical repo-root paths - used by callers (the API server) that don't
    already have both loaded, mirroring aq_cli.py::cmd_assets()'s own
    CONFIG_PATH/LEAN_JSON_PATH read pattern.

    lean.json is deliberately excluded from the published Docker image
    itself (development/Problems.md #42) and only reaches a running
    container via an explicit volume mount (docker-compose.yml's `engine`
    service) - a misconfigured or stripped-down deployment could still be
    missing it, so a missing file degrades to an empty lean_config (every
    ib_readiness_status() field it drives already has a graceful
    "not configured" reading for that case) rather than a 500.
    """
    import json

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    try:
        lean_config = json.loads(LEAN_JSON_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        lean_config = {}
    return build_assets_status(config, lean_config)
