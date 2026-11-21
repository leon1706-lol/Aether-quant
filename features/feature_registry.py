"""The features the lab can build from a dates x tickers close table, by name (`aq features list`).

Each builder reads closes up to its own date only (a trailing window), so a table built on a prefix of the dates equals
the same rows of a table built on all of them. Technical indicators reuse `features/technical_indicators.py` over a
rolling window. The production dataset's frame-level features (macro, bonds, options, alt data) need inputs a close
table does not have; they are listed as production-only groups and are not buildable here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from features import technical_indicators as ti


@dataclass(frozen=True)
class FeatureSpec:
    """One registered feature: its builder, the inputs it reads, its lookback, its group and what it measures."""
    name: str
    group: str
    lookback: int
    description: str
    builder: Callable[[pd.DataFrame], pd.DataFrame] = field(repr=False, compare=False)


def _returns(closes: pd.DataFrame) -> pd.DataFrame:
    return closes.astype(float).where(lambda frame: frame > 0).pct_change(fill_method=None)


def _ret(window: int) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def build(closes: pd.DataFrame) -> pd.DataFrame:
        clean = closes.astype(float).where(lambda frame: frame > 0)
        return clean / clean.shift(window) - 1.0

    return build


def _vol(window: int) -> Callable[[pd.DataFrame], pd.DataFrame]:
    return lambda closes: _returns(closes).rolling(window, min_periods=window).std()


def _mom_12_1(closes: pd.DataFrame) -> pd.DataFrame:
    clean = closes.astype(float).where(lambda frame: frame > 0)
    return clean.shift(21) / clean.shift(252) - 1.0


def _dist_high(window: int) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def build(closes: pd.DataFrame) -> pd.DataFrame:
        clean = closes.astype(float).where(lambda frame: frame > 0)
        return clean / clean.rolling(window, min_periods=window).max() - 1.0

    return build


def _rolling_indicator(window: int, indicator: Callable[[list[float]], float]) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def build(closes: pd.DataFrame) -> pd.DataFrame:
        return closes.astype(float).rolling(window, min_periods=window).apply(lambda values: indicator(list(values)), raw=True)

    return build


def _reversal_5(closes: pd.DataFrame) -> pd.DataFrame:
    return -_ret(5)(closes)


def _skew_60(closes: pd.DataFrame) -> pd.DataFrame:
    return _returns(closes).rolling(60, min_periods=60).skew()


def _vol_ratio(closes: pd.DataFrame) -> pd.DataFrame:
    returns = _returns(closes)
    long = returns.rolling(60, min_periods=60).std()
    return returns.rolling(20, min_periods=20).std() / long.where(long > 0)


FEATURES: dict[str, FeatureSpec] = {spec.name: spec for spec in (
    FeatureSpec("ret_1", "momentum", 1, "1-session return", _ret(1)),
    FeatureSpec("ret_5", "momentum", 5, "5-session return", _ret(5)),
    FeatureSpec("ret_20", "momentum", 20, "20-session return", _ret(20)),
    FeatureSpec("ret_60", "momentum", 60, "60-session return", _ret(60)),
    FeatureSpec("ret_120", "momentum", 120, "120-session return", _ret(120)),
    FeatureSpec("mom_12_1", "momentum", 252, "12-month return skipping the last month", _mom_12_1),
    FeatureSpec("rev_5", "reversal", 5, "minus the 5-session return (short-term reversal)", _reversal_5),
    FeatureSpec("vol_20", "volatility", 20, "20-session standard deviation of daily returns", _vol(20)),
    FeatureSpec("vol_60", "volatility", 60, "60-session standard deviation of daily returns", _vol(60)),
    FeatureSpec("vol_ratio_20_60", "volatility", 60, "20- over 60-session volatility", _vol_ratio),
    FeatureSpec("skew_60", "volatility", 60, "60-session skew of daily returns", _skew_60),
    FeatureSpec("dist_high_252", "trend", 252, "distance below the 252-session high", _dist_high(252)),
    FeatureSpec("dist_high_60", "trend", 60, "distance below the 60-session high", _dist_high(60)),
    FeatureSpec("rsi_14", "technical", 15, "14-session relative strength index (technical_indicators.relative_strength_index)",
                _rolling_indicator(15, ti.relative_strength_index)),
    FeatureSpec("bollinger_20", "technical", 20, "Bollinger %B over 20 sessions (technical_indicators.bollinger_pctb)", _rolling_indicator(20, ti.bollinger_pctb)),
    FeatureSpec("macd_hist", "technical", 60, "normalised MACD histogram 12/26/9 (technical_indicators.macd_histogram_normalized)",
                _rolling_indicator(60, ti.macd_histogram_normalized)),
)}

SETS: dict[str, tuple[str, ...]] = {
    "example": ("ret_1", "ret_5", "ret_20", "ret_60", "vol_20", "vol_60"),
    "momentum": ("ret_5", "ret_20", "ret_60", "ret_120", "mom_12_1", "rev_5"),
    "core": ("ret_1", "ret_5", "ret_20", "ret_60", "ret_120", "rev_5", "vol_20", "vol_60", "vol_ratio_20_60", "dist_high_60"),
    "all": tuple(FEATURES),
}

PRODUCTION_ONLY_GROUPS = ("macro", "bonds", "alt_data", "cross_asset_sensitivity", "derivatives_macro", "options", "fx_carry")


def resolve(names: str | Sequence[str]) -> list[str]:
    """Feature names from a set name, a comma list, or a list; unknown names raise KeyError with the closest matches."""
    import difflib

    items = [part.strip() for part in names.split(",")] if isinstance(names, str) else list(names)
    out: list[str] = []
    for item in items:
        if not item:
            continue
        if item in SETS:
            out += [name for name in SETS[item] if name not in out]
        elif item in FEATURES:
            if item not in out:
                out.append(item)
        else:
            close = difflib.get_close_matches(item, [*FEATURES, *SETS], n=3)
            raise KeyError(f"unknown feature {item!r}" + (f"; did you mean {', '.join(close)}?" if close else ""))
    return out


def build_wide(closes: pd.DataFrame, names: str | Sequence[str]) -> dict[str, pd.DataFrame]:
    """{feature: dates x tickers table} for the chosen features; inf becomes NaN."""
    return {name: FEATURES[name].builder(closes).replace([np.inf, -np.inf], np.nan) for name in resolve(names)}


def build_long(closes: pd.DataFrame, names: str | Sequence[str]) -> pd.DataFrame:
    """Long rows `date, ticker, <features>` (rows where every feature is missing are dropped)."""
    wide = build_wide(closes, names)
    long = pd.concat({name: table.stack(future_stack=True) for name, table in wide.items()}, axis=1)
    long.index.names = ["date", "ticker"]
    long = long.reset_index().astype({"date": str, "ticker": str})
    return long.dropna(how="all", subset=list(wide)).reset_index(drop=True)


def catalog() -> list[dict]:
    """Every buildable feature: name, group, lookback, description."""
    return [{"name": spec.name, "group": spec.group, "lookback": spec.lookback, "description": spec.description} for spec in FEATURES.values()]


def groups_of(names: Sequence[str]) -> Mapping[str, list[str]]:
    """{group: [features]} for `names`."""
    out: dict[str, list[str]] = {}
    for name in names:
        out.setdefault(FEATURES[name].group if name in FEATURES else "other", []).append(name)
    return out
