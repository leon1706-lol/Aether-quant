"""A research context for one V6.6.0 cell (`evaluation/research_cells.py`): the market, features and signals a sleeve may read there.

A cell's panel holds only its own names and stops at its own last date, so nothing outside it can enter a rank, a label or a covariance.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from evaluation.premia_research import ResearchContext
from evaluation.research_cells import (
    BENCHMARK_TICKERS,
    CELLS,
    SWEEP_TICKER,
    Cell,
    assert_cell_open,
    blank_stale,
    coin_side,
    membership_mask,
    names_in_cell,
    window_rows,
)
from evaluation.target_weights_engine import MarketPanel, load_market_panel
from features.wide_panel import WideBars, extended_info_features, info_features, price_features, wide_label
from portfolio.financing import load_rate_series
from portfolio.premia_signals import ResearchPanel, WeightSettings, known_closes
from portfolio.target_weights import TargetWeightsConfig, resolve_target_weights_config
from portfolio.wide_signals import crypto_tables, wide_tables

WIDE_ROOT = "data_wide"
CRYPTO_ROOT = "data_crypto_wide"
WIDE_SETTINGS = WeightSettings(target_vol=0.07, gross_cap=1.4, name_cap=0.03, class_caps={"crypto": 0.15}, name_cap_by_class={"crypto": 0.05})
PATH_OVERRIDES = {"enabled": True, "min_weight_change": 0.001, "no_bar_exit": True, "no_bar_exit_after": 2}
SECTOR_ETF_CLASS, BOND_ETF_CLASS, BENCHMARK_CLASS = "sector_etf", "bond_etf", "benchmark"
SECTOR_ETFS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLC", "XLRE")
SECTORS = (
    "communication_services", "consumer_discretionary", "consumer_staples", "energy", "financials", "health_care", "industrials", "information_technology",
    "materials", "real_estate", "utilities",
)


@dataclass
class WideCell:
    cell: Cell
    context: ResearchContext
    bars: WideBars | None = None
    member: pd.DataFrame | None = None
    sectors: dict[str, str] = field(default_factory=dict)
    features: dict[str, pd.DataFrame] = field(default_factory=dict)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    label: pd.DataFrame | None = None


def path_config(base: dict) -> TargetWeightsConfig:
    return resolve_target_weights_config({**(base["phase_v2"].get("target_weights") or {}), **PATH_OVERRIDES})


def slice_market(market: MarketPanel, rows: list[str]) -> MarketPanel:
    """The panel on exactly these dates, and the sessions among them. Positions are found by date, so a hole is impossible."""
    position = {date: i for i, date in enumerate(market.dates)}
    keep = [position[date] for date in rows if date in position]
    dates = [market.dates[i] for i in keep]
    return MarketPanel(dates, list(market.tickers), market.opens[keep], market.closes[keep], dict(market.asset_class), market.sessions & set(dates))


def calendar_rows(market: MarketPanel, cell: Cell, warmup_sessions: int) -> list[str]:
    """Every date from `warmup_sessions` equity sessions before the cell to its end. A crypto panel has calendar days between its sessions."""
    sessions = window_rows(sorted(market.sessions), cell, warmup=warmup_sessions)
    if not sessions:
        return []
    return [date for date in market.dates if sessions[0] <= date <= cell.end]


def load_ohlcv(root: Path, tickers: list[str], rows: list[str], *, data_dir: str) -> dict[str, pd.DataFrame]:
    """open/high/low/volume tables on `rows`, from the Lean zips."""
    from data_pipeline.data_audit import read_lean_daily_zip

    frames: dict[str, dict[str, pd.Series]] = {name: {} for name in ("open", "high", "low", "volume")}
    for ticker in tickers:
        path = Path(root) / data_dir / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip"
        if not path.exists():
            continue
        frame = read_lean_daily_zip(path, "equity")
        frame.index = frame["date"].dt.strftime("%Y-%m-%d")
        for name in frames:
            frames[name][ticker] = frame[name].astype(float)
    return {name: pd.DataFrame(series).reindex(index=rows, columns=tickers) for name, series in frames.items()}


def load_raw_closes(root: Path, tickers: list[str], rows: list[str], *, data_dir: str) -> pd.DataFrame:
    series = {}
    for ticker in tickers:
        path = Path(root) / data_dir / "reference" / "raw_closes" / f"{ticker.lower()}.json"
        if path.exists():
            series[ticker] = pd.Series(json.loads(path.read_text(encoding="utf-8")), dtype=float)
    return pd.DataFrame(series).reindex(index=rows, columns=tickers)


def read_info(root: Path, *, data_dir: str) -> dict[str, pd.DataFrame | None]:
    """What `scripts/build_wide_info.py` wrote; an absent part reads as None, and its trials report an empty book."""
    from data_pipeline.edgar_facts import read_fundamentals

    reference = Path(root) / data_dir / "reference"

    def optional(name: str, reader):
        path = reference / name
        return reader(path) if path.exists() else None

    return {
        "fundamentals": optional("edgar_fundamentals.csv.gz", read_fundamentals),
        "eps": optional("edgar_eps.csv.gz", lambda path: pd.read_csv(path, dtype={"ticker": str, "period_start": str, "period_end": str, "filed": str})),
        "splits": optional("equity_splits.csv", lambda path: pd.read_csv(path, dtype={"ticker": str, "date": str})),
        "insiders": optional("insider_trades.csv.gz", lambda path: pd.read_csv(path, dtype=str).assign(value=lambda frame: pd.to_numeric(frame["value"]))),
        "short": optional("short_ratio.parquet", pd.read_parquet),
        "extended": optional("edgar_fundamentals_ext.csv.gz", read_fundamentals),
    }


def project_tickers(base: dict, security_type: str) -> list[str]:
    return [str(asset["ticker"]) for asset in base["phase1"]["universe"]["assets"] if asset["security_type"] == security_type]


def _context(market: MarketPanel, panel: ResearchPanel, base: dict, root: Path, *, data_dir: str, settings: WeightSettings) -> ResearchContext:
    rf_dates, rf_rates = load_rate_series(Path(root) / data_dir / "alternative" / "interest-rate" / "usa" / "interest-rate.csv")
    return ResearchContext(
        market, panel, path_config(base), base["phase_v2"]["cash_sweep"], rf_dates, rf_rates, lambda ticker, date: 0.0, lambda ticker, date: True, settings,
    )


def wide_config_for(base: dict, root: Path, tickers: set[str], *, data_dir: str = WIDE_ROOT) -> dict:
    import sys

    sys.path.insert(0, str(Path(root) / "scripts"))
    from build_wide_root import wide_config

    manifest = json.loads((Path(root) / data_dir / "wide_manifest.json").read_text(encoding="utf-8"))
    return wide_config(base, manifest, tickers=tickers, keep_project_crypto=False)


def equity_cell(
    root: Path, base: dict, cell_name: str, *, freeze_path: Path | None = None, freeze_digest: str | None = None, data_dir: str = WIDE_ROOT,
    settings: WeightSettings = WIDE_SETTINGS, with_features: bool = True, with_info: bool = True,
) -> WideCell:
    """The cell's context, features and w-tables. Sectors come from SEC; a name with none is never ranked."""
    from data_pipeline.sp500_membership import load_membership

    cell = assert_cell_open(cell_name, freeze_path, freeze_digest)
    if cell.universe != "equity":
        raise ValueError(f"cell {cell_name} is a {cell.universe} cell")
    root = Path(root)
    manifest = json.loads((root / data_dir / "wide_manifest.json").read_text(encoding="utf-8"))
    project = project_tickers(base, "equity")
    bonds = [str(asset["ticker"]) for asset in base["phase1"]["universe"]["assets"] if asset.get("asset_class") == "bond"]
    # ETFs are the E trials' own universe; neither they nor a project name is ever held-out evidence.
    names = names_in_cell(cell, manifest["tickers"], [*project, *SECTOR_ETFS])
    keep = {ticker for ticker in names if ticker != SWEEP_TICKER} | set(BENCHMARK_TICKERS)
    full = load_market_panel(root, wide_config_for(base, root, keep, data_dir=data_dir), data_dir=data_dir)
    market = slice_market(full, calendar_rows(full, cell, warmup_sessions=300))
    known = known_closes(market.dates, market.tickers, market.closes, market.asset_class, market.sessions)
    closes = pd.DataFrame(market.closes, index=market.dates, columns=market.tickers)
    known = blank_stale(known, closes)
    sectors_path = root / data_dir / "reference" / "sectors.json"
    sectors: dict[str, str] = json.loads(sectors_path.read_text(encoding="utf-8")) if sectors_path.exists() else {}
    labels = {}
    for ticker in market.tickers:
        if ticker in BENCHMARK_TICKERS:
            labels[ticker] = BENCHMARK_CLASS
        elif ticker in SECTOR_ETFS:
            labels[ticker] = SECTOR_ETF_CLASS
        elif ticker in bonds:
            labels[ticker] = BOND_ETF_CLASS
        elif ticker == SWEEP_TICKER:
            labels[ticker] = "sweep"
        else:
            labels[ticker] = sectors.get(ticker, "unknown")
    sessions = list(known.index)
    table = load_membership(root / data_dir / "reference" / "sp500_ticker_start_end.csv")
    member = membership_mask(table, sessions, list(known.columns))
    panel = ResearchPanel(known, labels, {}, {})
    context = _context(market, panel, base, root, data_dir=data_dir, settings=settings)
    out = WideCell(cell, context, member=member, sectors=labels)
    if not with_features:
        return out
    tickers = list(known.columns)
    ohlcv = load_ohlcv(root, tickers, sessions, data_dir=data_dir)
    raw_close = load_raw_closes(root, tickers, sessions, data_dir=data_dir)
    bars = WideBars(known, ohlcv["open"], ohlcv["high"], ohlcv["low"], ohlcv["volume"], raw_close)
    out.bars = bars
    out.features = price_features(bars)
    if with_info:
        info = read_info(root, data_dir=data_dir)
        if info["fundamentals"] is not None:
            splits = info["splits"] if info["splits"] is not None else pd.DataFrame(columns=["ticker", "date", "ratio"], dtype=object)
            out.features.update(info_features(
                sessions, tickers, fundamentals=info["fundamentals"], splits=splits, raw_close=raw_close, eps=info["eps"],
                insider_trades=info["insiders"], short_ratios=info["short"],
            ))
            if info.get("extended") is not None:
                out.features.update(extended_info_features(sessions, tickers, extended=info["extended"], fundamentals=info["fundamentals"]))
    out.tables = wide_tables(out.features, member)
    out.label = wide_label(bars, labels)
    panel.extras = dict(out.tables)
    return out


def crypto_cell(
    root: Path, base: dict, cell_name: str, *, freeze_path: Path | None = None, freeze_digest: str | None = None, data_dir: str = CRYPTO_ROOT,
    settings: WeightSettings = WIDE_SETTINGS, side: str | None = None,
) -> WideCell:
    """Binance's coins under the Coinbase cost model. Side A coins enter a later cell only from 2023-01, so the part selection read stays out.
    `side` restricts the cell to one side's coins, for R-CRYPTO1."""
    from data_pipeline.binance_archive import liquid_universe

    cell = assert_cell_open(cell_name, freeze_path, freeze_digest)
    if cell.universe != "crypto":
        raise ValueError(f"cell {cell_name} is not a crypto cell")
    root = Path(root)
    manifest = json.loads((root / data_dir / "crypto_wide_manifest.json").read_text(encoding="utf-8"))
    project = project_tickers(base, "crypto")
    every = sorted(entry["ticker"] for entry in manifest["coins"].values())
    coins = names_in_cell(cell, every, project)
    if side is not None:
        coins = [coin for coin in coins if coin_side(coin, project) == side]
    if "BTCUSD" not in coins and "BTCUSD" in every:
        coins = sorted({*coins, "BTCUSD"})  # the market a residual is taken against; never a holding unless its side allows it
    assets = [
        {"ticker": coin, "security_type": "crypto", "market": "coinbase", "data_path": f"data/crypto/coinbase/daily/{coin.lower()}_trade.zip"}
        for coin in coins
    ] + [
        {"ticker": ticker, "security_type": "equity", "market": "usa", "data_path": f"data/equity/usa/daily/{ticker.lower()}.zip"}
        for ticker in BENCHMARK_TICKERS
    ]
    config = {"phase1": {"universe": {"assets": assets}}}
    full = load_market_panel(root, config, data_dir=data_dir)
    market = slice_market(full, calendar_rows(full, cell, warmup_sessions=300))
    known = known_closes(market.dates, market.tickers, market.closes, market.asset_class, market.sessions)
    closes = pd.DataFrame(market.closes, index=market.dates, columns=market.tickers)
    late_closes = closes.shift(1).reindex(known.index)
    known = blank_stale(known, late_closes)
    labels = {ticker: ("crypto" if ticker in coins else BENCHMARK_CLASS) for ticker in market.tickers}
    panel = ResearchPanel(known, labels, {}, {})
    context = _context(market, panel, base, root, data_dir=data_dir, settings=settings)
    volume = pd.read_parquet(root / data_dir / "reference" / "quote_volume.parquet").sort_index()
    volume = volume.reindex(columns=[coin for coin in coins if coin in volume.columns])
    liquid = liquid_universe(volume).astype(float).reindex(volume.index.union(known.index)).ffill().reindex(known.index).fillna(0.0) > 0.5
    liquid = liquid.reindex(columns=known.columns, fill_value=False)
    allowed = liquid_mask_for_cell(liquid, cell, project)
    if side is not None:
        for coin in allowed.columns:
            if coin_side(coin, project) != side:
                allowed[coin] = False
    funding_path = root / data_dir / "reference" / "funding.parquet"
    funding = pd.read_parquet(funding_path).sort_index() if funding_path.exists() else None
    tables = crypto_tables(known, funding, allowed)
    panel.extras = dict(tables)
    return WideCell(cell, context, member=allowed, sectors=labels, tables=tables)


def liquid_mask_for_cell(liquid: pd.DataFrame, cell: Cell, project: list[str]) -> pd.DataFrame:
    """In the holdout cell, side A coins count only after the window selection read."""
    if cell.name != "CV":
        return liquid
    mask = liquid.copy()
    read_until = CELLS["CS"].end
    for coin in mask.columns:
        if coin_side(coin, project) == "A":
            mask.loc[mask.index <= read_until, coin] = False
    return mask


def signal_ic_t(table: pd.DataFrame, label: pd.DataFrame, *, start: str, end: str, horizon: int = 20, min_names: int = 20) -> dict:
    """The signal's rank IC with the label, with the t on non-overlapping dates (a 20-session label overlaps itself)."""
    from evaluation.research_harness import daily_rank_ic, ic_summary

    dates = [date for date in table.index if start <= date <= end]
    score = table.loc[dates].stack(future_stack=True).rename("score")
    target = label.reindex(index=dates, columns=table.columns).stack(future_stack=True).rename("target")
    frame = pd.concat([score, target], axis=1).dropna().rename_axis(["date", "ticker"]).reset_index()
    ic = daily_rank_ic(frame, score_column="score", target_column="target", date_column="date", min_names_per_date=min_names)
    summary = ic_summary(ic, horizon=horizon, bootstrap_draws=200)
    return {key: summary.get(key) for key in ("num_dates", "mean_ic", "nonoverlap_t", "num_nonoverlap_dates", "hac_t", "ic_by_year")}


def daily_returns_for(context: ResearchContext, weights: Mapping, *, start: str, end: str) -> pd.Series:
    return context.simulate(weights, start, end)["strategy_excess"]


def sharpe_at_sessions(series: pd.Series, sessions) -> float | None:
    from evaluation.premia_research import annual_sharpe

    return annual_sharpe(series, sessions=sessions)


__all__ = [
    "BENCHMARK_CLASS", "BOND_ETF_CLASS", "CRYPTO_ROOT", "SECTOR_ETF_CLASS", "SECTOR_ETFS", "SECTORS", "WIDE_ROOT", "WIDE_SETTINGS", "WideCell", "crypto_cell",
    "daily_returns_for", "equity_cell", "liquid_mask_for_cell", "path_config", "sharpe_at_sessions", "signal_ic_t", "slice_market",
]
