"""Features of the wide universe (V6.6.0), each a session x ticker table known at that session's close.

Every function looks backward only: `tests/test_wide_signals.py` cuts the data at D and requires the same row D. Valuation uses
Yahoo's closes without dividends, since an adjusted close embeds later dividends (`data_pipeline.edgar_facts.market_cap_table`).
The label uses SPY for its market, never a market built from the panel's names, so side B can't enter side A's labels.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

PRICE_FEATURES = (
    "ret_1", "ret_5", "ret_20", "ret_60", "ret_120", "ret_252", "mom_12_1", "resmom_60", "resmom_252", "resrev_5", "vol_20", "vol_60", "beta_252",
    "idio_vol_60", "dist_52w_high", "amihud_20", "log_dollar_volume_20", "volume_z_20", "overnight_ret_20", "overnight_ret_252", "intraday_ret_20",
    "max_ret_20", "range_20",
)
INFO_FEATURES = (
    "gp_assets", "roe", "cfo_assets", "accruals", "asset_growth", "net_issuance", "leverage", "book_to_market", "earnings_yield", "sue",
    "days_since_filing", "insider_net_180", "short_ratio_20",
)
MARKET = "SPY"
RESIDUAL_WINDOW = 60


@dataclass
class WideBars:
    """Session x ticker. `close`, `open`, `high` and `low` are adjusted (the data a run trades on); `raw_close` is split-adjusted without
    dividends; `volume` is split-adjusted."""

    close: pd.DataFrame
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    raw_close: pd.DataFrame


def residual_daily(close: pd.DataFrame, market: str = MARKET, window: int = RESIDUAL_WINDOW) -> pd.DataFrame:
    """Daily return less a trailing beta (known a row earlier) times the market's."""
    daily = close.pct_change(fill_method=None)
    bench = daily[market]
    covariance = daily.rolling(window, min_periods=window).cov(bench)
    variance = bench.rolling(window, min_periods=window).var()
    beta = covariance.div(variance, axis=0).shift(1)
    return daily.sub(beta.mul(bench, axis=0))


def price_features(bars: WideBars, market: str = MARKET) -> dict[str, pd.DataFrame]:
    """The wide panel's price features (returns, residual returns, volatility, momentum and more) as date x ticker tables."""
    close = bars.close
    daily = close.pct_change(fill_method=None)
    bench = daily[market]
    residual = residual_daily(close, market)
    log_overnight = np.log(bars.open / close.shift(1))
    log_intraday = np.log(close / bars.open)
    dollar_volume = bars.raw_close * bars.volume
    average_dollar_volume = dollar_volume.rolling(20, min_periods=10).mean()
    volume_mean = bars.volume.rolling(20, min_periods=20).mean()
    volume_std = bars.volume.rolling(20, min_periods=20).std()
    features = {f"ret_{window}": close / close.shift(window) - 1.0 for window in (1, 5, 20, 60, 120, 252)}
    features.update({
        "mom_12_1": close.shift(21) / close.shift(252) - 1.0,
        "resmom_60": residual.rolling(60, min_periods=60).sum(),
        "resmom_252": residual.shift(21).rolling(231, min_periods=231).sum(),
        "resrev_5": -residual.rolling(5, min_periods=5).sum(),
        "vol_20": daily.rolling(20, min_periods=20).std(),
        "vol_60": daily.rolling(60, min_periods=60).std(),
        "beta_252": daily.rolling(252, min_periods=252).cov(bench).div(bench.rolling(252, min_periods=252).var(), axis=0),
        "idio_vol_60": residual.rolling(60, min_periods=60).std(),
        "dist_52w_high": close / close.rolling(252, min_periods=252).max() - 1.0,
        "amihud_20": (daily.abs() / dollar_volume.where(dollar_volume > 0.0)).rolling(20, min_periods=10).mean(),
        "log_dollar_volume_20": np.log(average_dollar_volume.where(average_dollar_volume > 0.0)),
        "volume_z_20": (bars.volume - volume_mean) / volume_std.where(volume_std > 0.0),
        "overnight_ret_20": log_overnight.rolling(20, min_periods=20).sum(),
        "overnight_ret_252": log_overnight.rolling(252, min_periods=252).sum(),
        "intraday_ret_20": log_intraday.rolling(20, min_periods=20).sum(),
        "max_ret_20": daily.rolling(20, min_periods=20).max(),
        "range_20": ((bars.high - bars.low) / close).rolling(20, min_periods=20).mean(),
    })
    return features


def _ratio(numerator: pd.DataFrame, denominator: pd.DataFrame) -> pd.DataFrame:
    return numerator / denominator.where(denominator.abs() > 0.0)


def growth_rows(rows: pd.DataFrame, field: str, name: str, splits: pd.DataFrame | None = None) -> pd.DataFrame:
    """A new field: each fiscal year's value against the year before it, published with the newer filing. Share counts compare on one
    basis: each is restated by the splits after its own filing, so a split isn't read as issuance."""
    from data_pipeline.edgar_facts import split_factor_after

    pieces = []
    for ticker, group in rows[rows["field"] == field].groupby("ticker"):
        ordered = group.sort_values("period_end").copy()
        values = ordered["value"].astype(float)
        if splits is not None:
            values = values * [split_factor_after(splits, ticker, filed) for filed in ordered["filed"]]
        ordered["value"] = values / values.shift(1).where(values.shift(1) > 0.0) - 1.0
        ordered["field"] = name
        pieces.append(ordered.iloc[1:].dropna(subset=["value"]))
    return pd.concat(pieces, ignore_index=True) if pieces else rows.iloc[0:0].copy()


def days_since_filing(rows: pd.DataFrame, sessions: list[str], columns: list[str]) -> pd.DataFrame:
    """Calendar days since the latest filing that was already public, a session late as every other field is."""
    stamps = pd.to_datetime(pd.Index(sessions))
    table = pd.DataFrame(np.nan, index=sessions, columns=columns, dtype=float)
    positions = pd.Index(sessions)
    for ticker, group in rows.groupby("ticker"):
        if ticker not in table.columns:
            continue
        filed = sorted(group["filed"].unique())
        location = positions.searchsorted(np.asarray(filed), side="left") + 1
        keep = location < len(sessions)
        series = pd.Series(pd.NaT, index=range(len(sessions)), dtype="datetime64[ns]")
        series.iloc[location[keep]] = pd.to_datetime(np.asarray(filed)[keep])
        last = series.ffill()
        table[ticker] = ((pd.Series(stamps) - last).dt.days).to_numpy(dtype=float)
    return table


def info_features(
    sessions: list[str], columns: list[str], *, fundamentals: pd.DataFrame, splits: pd.DataFrame, raw_close: pd.DataFrame, eps: pd.DataFrame | None = None,
    insider_trades: pd.DataFrame | None = None, short_ratios: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Fundamental, earnings, insider and short-volume tables. A filing shows from the session after its date."""
    from data_pipeline.edgar_facts import fundamentals_table, market_cap_table, split_adjusted_eps, surprise_table
    from data_pipeline.finra_short_volume import short_ratio_table
    from data_pipeline.sec_form345 import insider_net_table, opportunistic

    def field(name: str) -> pd.DataFrame:
        return fundamentals_table(fundamentals, sessions, columns, name)

    assets, equity, net_income, cash_flow, debt = field("assets"), field("equity"), field("net_income"), field("operating_cash_flow"), field("long_term_debt")
    gross_profit = field("gross_profit").combine_first(field("revenue") - field("cost_of_revenue"))
    derived = pd.concat([growth_rows(fundamentals, "assets", "asset_growth"), growth_rows(fundamentals, "shares_outstanding", "net_issuance", splits)], ignore_index=True)
    market_cap = market_cap_table(raw_close.reindex(index=sessions, columns=columns), fundamentals, splits)
    features = {
        "gp_assets": _ratio(gross_profit, assets),
        "roe": _ratio(net_income, equity),
        "cfo_assets": _ratio(cash_flow, assets),
        "accruals": _ratio(net_income - cash_flow, assets),
        "asset_growth": fundamentals_table(derived, sessions, columns, "asset_growth"),
        "net_issuance": fundamentals_table(derived, sessions, columns, "net_issuance"),
        "leverage": _ratio(debt, assets),
        "book_to_market": _ratio(equity, market_cap),
        "earnings_yield": _ratio(net_income, market_cap),
        "days_since_filing": days_since_filing(fundamentals, sessions, columns),
        "market_cap": market_cap,
    }
    if eps is not None and not eps.empty:
        features["sue"] = surprise_table(split_adjusted_eps(eps, splits), sessions, columns, hold_sessions=60)
    else:
        features["sue"] = pd.DataFrame(np.nan, index=sessions, columns=columns, dtype=float)
    if insider_trades is not None and not insider_trades.empty:
        flow = insider_net_table(opportunistic(insider_trades), sessions, columns, window_days=180)
        features["insider_net_180"] = _ratio(flow, market_cap)
    else:
        features["insider_net_180"] = pd.DataFrame(np.nan, index=sessions, columns=columns, dtype=float)
    if short_ratios is not None and not short_ratios.empty:
        features["short_ratio_20"] = short_ratio_table(short_ratios, sessions, columns, window=20)
    else:
        features["short_ratio_20"] = pd.DataFrame(np.nan, index=sessions, columns=columns, dtype=float)
    return features


def extended_info_features(sessions: list[str], columns: list[str], *, extended: pd.DataFrame, fundamentals: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """V6.6.1: accruals on trailing twelve months, net operating assets (Hirshleifer et al. 2004) and capex growth. A filing shows a session
    after its date. Missing short-term debt counts as none, since many filers report no such line; missing cash leaves the ratio unknown."""
    from data_pipeline.edgar_facts import fundamentals_table

    def ext(name: str) -> pd.DataFrame:
        return fundamentals_table(extended, sessions, columns, name)

    def base(name: str) -> pd.DataFrame:
        return fundamentals_table(fundamentals, sessions, columns, name)

    operating = base("equity") + base("long_term_debt").fillna(0.0) + ext("short_term_debt").fillna(0.0) - ext("cash")
    return {
        "accruals_ttm": _ratio(ext("ttm_net_income") - ext("ttm_operating_cash_flow"), ext("assets_q")),
        "noa": _ratio(operating, base("assets")),
        "capex_growth": fundamentals_table(growth_rows(extended, "capex", "capex_growth"), sessions, columns, "capex_growth"),
    }


def wide_label(bars: WideBars, sector: Mapping[str, str], *, horizon: int = 21, market: str = MARKET) -> pd.DataFrame:
    """Return from the next open to the close `horizon` sessions on, less the market's over the same span, then a percentile rank per
    (date, sector) centred at zero, so knowing a name's group earns nothing (Problems.md #259). NaN where the span runs past the data."""
    entry = bars.open.shift(-1)
    exit_price = bars.close.shift(-horizon)
    forward = exit_price / entry - 1.0
    residual = forward.sub(forward[market], axis=0)
    labels = pd.Series({ticker: sector.get(ticker) for ticker in residual.columns})
    pieces = []
    for name in sorted({value for value in labels.dropna().unique() if value != "unknown"}):
        members = labels.index[labels == name]
        group = residual[members]
        count = group.notna().sum(axis=1)
        pieces.append(group.rank(axis=1, pct=True).sub((count + 1.0) / (2.0 * count).where(count > 0), axis=0))
    if not pieces:
        return pd.DataFrame(np.nan, index=residual.index, columns=residual.columns, dtype=float)
    return pd.concat(pieces, axis=1).reindex(columns=residual.columns)


def long_frame(features: Mapping[str, pd.DataFrame], label: pd.DataFrame, sector: Mapping[str, str], member: pd.DataFrame, *, label_name: str = "target_wide_20d") -> pd.DataFrame:
    """One row per (member session, ticker) with a known sector, float32, for the model track."""
    mask = member.reindex(index=label.index, columns=label.columns, fill_value=False).to_numpy(dtype=bool)
    known_sector = np.array([sector.get(ticker, "unknown") != "unknown" for ticker in label.columns])
    rows, columns = np.nonzero(mask & known_sector)
    frame = {
        "date": np.asarray(label.index)[rows], "ticker": np.asarray(label.columns)[columns],
        "sector": [sector[ticker] for ticker in np.asarray(label.columns)[columns]],
        label_name: label.to_numpy(dtype="float32")[rows, columns],
    }
    for name, table in features.items():
        frame[name] = table.reindex(index=label.index, columns=label.columns).to_numpy(dtype="float32")[rows, columns]
    return pd.DataFrame(frame)
