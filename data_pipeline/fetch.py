"""Ad-hoc historical OHLCV fetch for tickers not (yet) in config.json.

Distinct responsibility from yfinance_backfill.py: that module fills gaps in
already-configured assets via a config.json "backfill" block, and
deliberately never touches config.json (widening an *existing*, already
-trained asset's date range is a decision a human should make explicitly).
This module fetches an explicit date range for *any* ticker, including ones
with no config.json entry at all, and — on --apply — *does* add a new asset
block to config.json, because adding a brand-new ticker to the universe is
this module's entire purpose, not an accidental side effect.

Reuses yfinance_backfill.py's config.json-independent pure functions
(fetch_yahoo_ohlcv, scale_for_lean, write_lean_zip) - no duplicated logic.

Never runs `train.py` itself - preparing a ticker for training (fetching
its data, formatting it for Lean, wiring it into config.json's universe) is
this module's job; actually training on it stays a deliberate, separate
step (`python train.py`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from data_pipeline.yfinance_backfill import fetch_yahoo_ohlcv, scale_for_lean, write_lean_zip

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"


def _crypto_yahoo_symbol(ticker: str) -> str:
    """BTCUSD -> BTC-USD, DOGEUSD -> DOGE-USD: strip a trailing USD and join
    with a hyphen, matching Yahoo Finance's crypto pair naming convention."""
    base = ticker[:-3] if ticker.upper().endswith("USD") else ticker
    return f"{base}-USD"


# One entry per asset class - V3's "futures"/"options" entries below prove
# the docstring's original claim (adding a class is one new dict entry, not
# a redesign): both route through data_pipeline/ib_backfill.py instead of
# Yahoo Finance (yahoo_symbol_fn stays identity - not a real Yahoo symbol
# for these two, just this dict's "instrument identifier passed to
# fetch_fn" slot, reused as-is rather than renamed) and carry an
# extra_asset_fields block (asset_class/data_source) merged into the
# config.json asset entry fetch_adhoc_asset() writes on --apply, since IB-
# backed assets need to be identified by the feature/risk layer
# (risk/asset_class_router.py) independently of Lean's own security_type.
ASSET_CLASS_CONFIG = {
    "crypto": {
        "security_type": "crypto",
        "market": "coinbase",
        "data_path_fn": lambda ticker: ROOT / "data" / "crypto" / "coinbase" / "daily" / f"{ticker.lower()}_trade.zip",
        "yahoo_symbol_fn": _crypto_yahoo_symbol,
    },
    "stock": {
        "security_type": "equity",
        "market": "usa",
        "data_path_fn": lambda ticker: ROOT / "data" / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip",
        "yahoo_symbol_fn": lambda ticker: ticker,
    },
    "futures": {
        "security_type": "future",
        "market": "cme",
        "data_path_fn": lambda ticker: ROOT / "data" / "future" / "cme" / "daily" / f"{ticker.lower()}.zip",
        "yahoo_symbol_fn": lambda ticker: ticker,
        "extra_asset_fields": {"asset_class": "future", "data_source": "ib"},
    },
    "options": {
        "security_type": "option",
        "market": "usa",
        "data_path_fn": lambda ticker: ROOT / "data" / "option" / "usa" / "daily" / f"{ticker.lower()}.zip",
        "yahoo_symbol_fn": lambda ticker: ticker,
        "extra_asset_fields": {"asset_class": "option", "data_source": "ib"},
    },
}
ASSET_CLASSES = tuple(ASSET_CLASS_CONFIG.keys())


def add_asset_to_config(config_path: Path, asset_block: dict) -> str:
    """Appends asset_block to config.json's phase1.universe.assets[] unless
    a block with the same ticker already exists there. Returns "added" or
    "already_exists". Preserves the file's existing exact formatting
    (4-space indent, trailing newline)."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assets = config["phase1"]["universe"]["assets"]

    if any(existing["ticker"] == asset_block["ticker"] for existing in assets):
        return "already_exists"

    assets.append(asset_block)
    config_path.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")
    return "added"


def fetch_adhoc_asset(
    asset_class: str,
    ticker: str,
    start: str,
    end: str,
    *,
    apply: bool,
    fetch_fn: Callable = fetch_yahoo_ohlcv,
    config_path: Path = CONFIG_PATH,
) -> dict:
    """apply=False (default): dry run - fetches but writes nothing (no zip,
    no config.json edit). apply=True: writes the Lean zip via
    write_lean_zip(), then adds a new config.json asset block if this
    ticker isn't already configured. fetch_fn is the injection point for
    tests (never real yfinance in tests), matching
    yfinance_backfill.run_backfill()'s exact convention."""
    ticker = ticker.upper()
    class_config = ASSET_CLASS_CONFIG[asset_class]
    yahoo_symbol = class_config["yahoo_symbol_fn"](ticker)
    output_zip = class_config["data_path_fn"](ticker)
    security_type = class_config["security_type"]

    rows = fetch_fn(yahoo_symbol, start, end)
    scaled_rows = scale_for_lean(rows, security_type)

    dates = [row["date"] for row in rows]
    suggested_from = min(dates) if dates else None
    suggested_to = max(dates) if dates else None

    config_status = "not_attempted"
    if not scaled_rows:
        action = "no_data_returned"
    elif apply:
        write_lean_zip(output_zip, ticker, scaled_rows, merge_with_existing=True)
        action = "written"
        config_status = add_asset_to_config(
            config_path,
            {
                "ticker": ticker,
                "security_type": security_type,
                "market": class_config["market"],
                "data_path": output_zip.relative_to(ROOT).as_posix(),
                "available_from": suggested_from.isoformat(),
                "available_to": suggested_to.isoformat(),
                **class_config.get("extra_asset_fields", {}),
            },
        )
    else:
        action = "dry_run"

    return {
        "ticker": ticker,
        "asset_class": asset_class,
        "yahoo_symbol": yahoo_symbol,
        "data_path": str(output_zip),
        "action": action,
        "rows_fetched": len(rows),
        "suggested_available_from": suggested_from.isoformat() if suggested_from else None,
        "suggested_available_to": suggested_to.isoformat() if suggested_to else None,
        "config_status": config_status,
    }
