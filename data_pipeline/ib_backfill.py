"""Interactive Brokers historical-data backfill for futures/options -
mirrors yfinance_backfill.py's shape (pure helpers + one deferred-import
boundary + orchestration), using `ib_insync` (add to requirements/dev.txt
only, never requirements.txt - same "dev-only dependency" convention as
yfinance).

This module is ONLY for the offline historical-bars-to-local-Lean-zip step.
It does NOT touch live/paper trading, which stays entirely on Lean's own
InteractiveBrokersBrokerage (lean.json's ib-account/ib-user-name/
ib-password/ib-trading-mode fields and the environments.live-interactive
block - both untouched by this module). Lean's backtesting environment
(environments.backtesting in lean.json) is hardcoded to FileSystemDataFeed +
SubscriptionDataReaderHistoryProvider - it never talks to IB no matter what
lean.json's ib-* fields hold - so historical futures/options bars still
need a separate, offline data-prep step to land as local Lean-format zip
files before any backtest can use them. That is this module's entire job.

Connects to the same local TWS/IB Gateway process using
config.json's phase_v2.ib.host/port/client_id (a second, independent
client-id socket connection alongside whatever Lean's own brokerage uses
when live-deployed - standard IB API pattern, Gateway supports multiple
simultaneous API clients). "IB ready" requires BOTH:
  1. config.json's phase_v2.ib.enabled == true (Aether's own app-level
     feature flag), AND
  2. lean.json's ib-account/ib-user-name are both non-empty (Lean's own
     credential fields - untouched, read-only from this module's
     perspective).
Every public function below raises IBNotConfiguredError, never a raw
traceback, when either check fails - see aq_cli.py::cmd_fetch()/cmd_ib()
for how that's surfaced to the user.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
LEAN_CONFIG_PATH = ROOT / "lean.json"
CONTRACT_SPECS_PATH = ROOT / "data" / "reference" / "futures_contract_specs.json"


class IBNotConfiguredError(Exception):
    """Raised by every public function in this module when
    phase_v2.ib.enabled is false in config.json, or lean.json's
    ib-account/ib-user-name are missing - never a raw ConnectionError, so
    callers (fetch.py's ASSET_CLASS_CONFIG dispatch, aq fetch's CLI) can
    catch one specific, documented exception type and print a clear
    message instead of a traceback."""


def ib_enabled(config: dict, lean_config: dict) -> bool:
    """Pure, no I/O. True only when config.json's phase_v2.ib.enabled is
    truthy AND lean.json's ib-account/ib-user-name are both non-empty -
    the toggle and the credentials live in two different, purpose-
    appropriate files, cross-checked here."""
    ib_config = config.get("phase_v2", {}).get("ib", {})
    if not ib_config.get("enabled", False):
        return False
    return bool(lean_config.get("ib-account")) and bool(lean_config.get("ib-user-name"))


def ib_readiness_status(config: dict, lean_config: dict) -> str:
    """One of "disabled" / "enabled_but_lean_credentials_missing" /
    "ready" - the three states aq_cli.py::cmd_ib() reports (a real
    connect/disconnect round-trip is a separate, heavier check layered on
    top of this pure classification, see attempt_connection() below)."""
    ib_config = config.get("phase_v2", {}).get("ib", {})
    if not ib_config.get("enabled", False):
        return "disabled"
    if not (lean_config.get("ib-account") and lean_config.get("ib-user-name")):
        return "enabled_but_lean_credentials_missing"
    return "ready"


def load_futures_contract_specs(path: Path = CONTRACT_SPECS_PATH) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("load_futures_contract_specs(%s): unreadable — %s", path, exc)
        return {}
    return {key: value for key, value in data.items() if not key.startswith("_")}


# ---------------------------------------------------------------------------
# The only functions that import ib_insync - deferred, mirrors
# yfinance_backfill.fetch_yahoo_ohlcv()'s deferred `import yfinance`.
# ---------------------------------------------------------------------------


def connect_ib(config: dict, lean_config: dict) -> Any:
    """Raises IBNotConfiguredError if not ib_enabled(config, lean_config).
    Never called at import time - this module must stay importable with
    ib_insync absent when IB is disabled, same convention as
    yfinance_backfill.py."""
    if not ib_enabled(config, lean_config):
        raise IBNotConfiguredError(
            "IB is not configured: run 'aq config set phase_v2.ib.enabled true' and fill in "
            "lean.json's ib-account/ib-user-name first (see 'aq ib status')."
        )

    from ib_insync import IB  # deferred - dev-only dependency, never in requirements.txt

    ib_config = config["phase_v2"]["ib"]
    ib = IB()
    ib.connect(
        str(ib_config.get("host", "127.0.0.1")),
        int(ib_config.get("port", 7497)),
        clientId=int(ib_config.get("client_id", 7)),
        timeout=float(ib_config.get("connect_timeout_seconds", 10)),
        readonly=True,
    )
    return ib


def disconnect_ib(ib: Any) -> None:
    ib.disconnect()


def attempt_connection(config: dict, lean_config: dict) -> tuple[bool, str]:
    """Best-effort connect/disconnect round-trip for aq_cli.py::cmd_ib()'s
    "reachable" tri-state check. Returns (True, "reachable") or
    (False, <reason>) - never raises (any connection failure is caught and
    reported, since this is a diagnostic command, not a data operation)."""
    try:
        ib = connect_ib(config, lean_config)
    except IBNotConfiguredError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover - real-network failure paths, not unit tested
        return False, f"connection failed — {exc}"
    else:
        disconnect_ib(ib)
        return True, "reachable"


def _bar_rows_from_ib(bars: list) -> list[dict]:
    """Normalizes ib_insync's BarData objects (each with .date/.open/.high/
    .low/.close/.volume) into the same row shape fetch_yahoo_ohlcv()
    returns, so they slot into scale_for_lean()/write_lean_zip() unchanged."""
    rows = []
    for bar in bars:
        bar_date = bar.date.date() if hasattr(bar.date, "date") else bar.date
        rows.append(
            {
                "date": bar_date,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )
    return rows


def fetch_future_historical_bars(
    ib: Any,
    ticker: str,
    contract_spec: dict,
    start: str,
    end: str,
) -> list[dict]:
    """Historical daily bars for ticker's continuous front-month future via
    ib_insync's ContFuture + reqHistoricalData. Returns [] (never raises)
    on any IB-side failure or empty response, matching
    fetch_yahoo_ohlcv()'s "one bad symbol never aborts a multi-asset run"
    convention."""
    from ib_insync import ContFuture, util

    try:
        contract = ContFuture(ticker, exchange=contract_spec.get("exchange", "CME"), currency="USD")
        ib.qualifyContracts(contract)
        duration_days = max((util.parseIBDatetime(end) - util.parseIBDatetime(start)).days, 1)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end,
            durationStr=f"{duration_days} D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
    except Exception as exc:
        logger.warning("fetch_future_historical_bars(%s): fetch failed — %s", ticker, exc)
        return []

    return _bar_rows_from_ib(bars or [])


def fetch_option_chain_snapshot(ib: Any, underlying_ticker: str, expiry: str) -> list[dict]:
    """One row per (strike, right) for underlying_ticker's chain at expiry
    - {strike, right, expiry, bid, ask, last, volume, open_interest} -
    the raw chain snapshot features/options_greeks.py's compute_greeks()
    consumes to attach delta/gamma/theta/vega/iv before
    portfolio/options_strategy.py selects a contract. Returns [] on any
    failure - never raises."""
    from ib_insync import Option, Stock

    try:
        underlying = Stock(underlying_ticker, "SMART", "USD")
        ib.qualifyContracts(underlying)
        chain_params = ib.reqSecDefOptParams(underlying.symbol, "", underlying.secType, underlying.conId)
        strikes: set[float] = set()
        for param in chain_params:
            if expiry in param.expirations:
                strikes.update(param.strikes)

        rows: list[dict] = []
        for strike in sorted(strikes):
            for right in ("C", "P"):
                option = Option(underlying_ticker, expiry, float(strike), right, "SMART")
                ib.qualifyContracts(option)
                ticker_data = ib.reqMktData(option, "", False, False)
                ib.sleep(0.2)
                rows.append(
                    {
                        "strike": float(strike),
                        "right": "call" if right == "C" else "put",
                        "expiry": expiry,
                        "bid": float(ticker_data.bid) if ticker_data.bid == ticker_data.bid else None,
                        "ask": float(ticker_data.ask) if ticker_data.ask == ticker_data.ask else None,
                        "last": float(ticker_data.last) if ticker_data.last == ticker_data.last else None,
                        "volume": float(ticker_data.volume) if ticker_data.volume == ticker_data.volume else None,
                        "open_interest": None,
                    }
                )
        return rows
    except Exception as exc:
        logger.warning("fetch_option_chain_snapshot(%s, %s): fetch failed — %s", underlying_ticker, expiry, exc)
        return []


def fetch_option_historical_bars(
    ib: Any,
    underlying_ticker: str,
    expiry: str,
    strike: float,
    right: str,
    start: str,
    end: str,
) -> list[dict]:
    """Historical daily bars for one specific option contract. Same
    OHLCV row shape as futures/equities. Returns [] on any failure -
    never raises."""
    from ib_insync import Option, util

    try:
        ib_right = "C" if right.lower() == "call" else "P"
        contract = Option(underlying_ticker, expiry, float(strike), ib_right, "SMART")
        ib.qualifyContracts(contract)
        duration_days = max((util.parseIBDatetime(end) - util.parseIBDatetime(start)).days, 1)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end,
            durationStr=f"{duration_days} D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
    except Exception as exc:
        logger.warning("fetch_option_historical_bars(%s %s %s%s): fetch failed — %s", underlying_ticker, expiry, strike, right, exc)
        return []

    return _bar_rows_from_ib(bars or [])
