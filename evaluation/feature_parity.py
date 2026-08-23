"""V5.3.6 Workstream A - the train-vs-live feature-parity audit's pure core.

Background (development/Problems.md #91/#98/#100 lineage): XOM is the one
tracked ticker whose live-vs-offline book-selection mismatch never resolved,
and two prior root causes WERE feature-computation drifts between the
offline training pipeline and the live Lean path (the bond duration-beta's
rolling-vs-full-history drift, V5.2.5; missing split/dividend factor files,
#100). This module is the systematic version of those one-off checks: for
every model-input feature family that can be recomputed from data already
on disk, it re-derives the RAW value and pushes it through the shipped
scaler artifact (`ml/scaler_stats.json`) in the forward direction -
`clip((raw - mean) / scale, +-clip_sigma)` - comparing against the scaled
column actually stored in `ml/datasets/full_dataset.csv`.

Three layers are covered here:
1. **Scaler-artifact consistency** - does `scaler_stats.json` still describe
   the dataset it is supposed to scale? (A stale artifact after a dataset
   rebuild would mis-scale live inference systemically - an XOM-class bug.)
2. **Formula parity** - the per-ticker OHLCV-recomputable families (10 base
   technicals + 6 shared indicators + 2 liquidity) re-derived row-faithfully
   from `train.py::engineer_features()` / `add_liquidity_features()`.
3. **Cross-sectional + macro families** - cs_momentum_rank_20 and the three
   macro proxies, rebuilt from a close-price pivot using the same shared
   functions both sides import.

Families deliberately NOT recomputable offline (regime payload chain, alt-
data FRED inputs, cross-asset sensitivity regressions' driver series, bond
treasury inputs, topology/peer correlation graphs) get structured verdicts
from the driver instead: "SHARED_FUNCTION_CALLSITE" where both sides call
one `features/*.py` function (verified by inspection), so the residual risk
is call-site parameters only.

Pure: no I/O, no torch, no Lean imports - mirrors the repo's established
"pure core + thin CLI driver" convention (see feature_reconciliation.py).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from features.macro_features import (
    credit_spread_proxy,
    crypto_risk_appetite_proxy,
    yield_curve_slope_proxy,
)
from features.technical_indicators import (
    average_true_range_pct,
    bollinger_pctb,
    cross_sectional_momentum_rank,
    distance_from_52w_high,
    macd_histogram_normalized,
    relative_strength_index,
    volume_zscore,
)
from liquidity.market_liquidity import estimate_high_low_spread

DEFAULT_LONG_LOOKBACK_WINDOW_BARS = 260
DEFAULT_CROSS_SECTIONAL_WINDOW_BARS = 25

BASE_TECHNICAL_FEATURES = [
    "close_to_close_return_1d",
    "close_to_close_return_5d",
    "close_to_close_return_20d",
    "rolling_volatility_5d",
    "rolling_volatility_20d",
    "momentum_5d",
    "momentum_20d",
    "high_low_range_pct",
    "open_close_range_pct",
    "volume_change_1d",
]
INDICATOR_FEATURES = [
    "rsi_14",
    "atr_pct_14",
    "bollinger_pctb_20",
    "volume_zscore_20",
    "macd_histogram_norm",
    "dist_52w_high",
]
LIQUIDITY_FEATURES = ["liquidity_log_dollar_volume", "liquidity_spread_proxy"]
MACRO_PROXIES_BY_KEY = {
    "long_duration": ("macro_yield_curve_slope_proxy", yield_curve_slope_proxy),
    "high_yield": ("macro_credit_spread_proxy", credit_spread_proxy),
    "crypto": ("macro_crypto_risk_appetite_proxy", crypto_risk_appetite_proxy),
}
DEFAULT_MACRO_REFERENCE_TICKERS = {
    "long_duration": "TLT",
    "short_duration": "SHY",
    "high_yield": "HYG",
    "investment_grade": "LQD",
    "crypto": "BTCUSD",
}


def load_scaler_mapping(scaler_stats: dict[str, Any]) -> tuple[dict[str, tuple[float, float, float]], list[str]]:
    """Maps `ml/scaler_stats.json` into {feature_name: (mean, scale, clip)}
    and reports which schema names it does NOT cover (by design: the binary
    regime/topology/asset-class one-hots skip StandardScaler entirely)."""
    names = list(scaler_stats["feature_names"])
    means = scaler_stats["mean"]
    scales = scaler_stats["scale"]
    clip = float(scaler_stats.get("clip_sigma", 10.0))
    mapping = {name: (float(means[i]), float(scales[i]), clip) for i, name in enumerate(names)}
    return mapping, []


def forward_scale(raw_values: np.ndarray, mean: float, scale: float, clip: float) -> np.ndarray:
    """The exact live/offline transform: clip((raw - mean) / scale, +-clip)."""
    return np.clip((np.asarray(raw_values, dtype=float) - mean) / scale, -clip, clip)


def compute_base_technicals_replica(frame: pd.DataFrame, *, long_window_bars: int = DEFAULT_LONG_LOOKBACK_WINDOW_BARS) -> dict[str, np.ndarray]:
    """Row-faithful replica of train.py::engineer_features()'s inline base
    technicals + Phase-6 indicator block (train.py:656-748), which itself is
    line-mirrored by main.py::_build_model_input() (both files carry explicit
    cross-reference comments asserting parity). First row is NaN exactly like
    train's `[np.nan]` seed convention; volatility degrades to 0.0 under two
    observations exactly like train's guard."""
    closes = frame["close"].tolist()
    opens = frame["open"].tolist()
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    volumes = frame["volume"].tolist()
    n = len(frame)

    columns: dict[str, list[float]] = {
        **{name: [np.nan] for name in BASE_TECHNICAL_FEATURES},
        **{name: [np.nan] for name in INDICATOR_FEATURES},
    }

    for index in range(1, n):
        previous_close = closes[index - 1]
        previous_volume = volumes[index - 1]
        current_close = closes[index]
        current_open = opens[index]

        close_5 = closes[max(0, index - 5)]
        close_20 = closes[max(0, index - 20)]

        all_recent_returns = [
            closes[position] / closes[position - 1] - 1.0
            for position in range(1, index + 1)
            if closes[position - 1] != 0
        ]
        recent_returns_5 = all_recent_returns[-5:]
        recent_returns_20 = all_recent_returns[-20:]

        def _sample_std(values: list[float]) -> float:
            if len(values) < 2:
                return 0.0
            mean_value = sum(values) / len(values)
            variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
            return float(np.sqrt(max(variance, 0.0)))

        columns["close_to_close_return_1d"].append(current_close / previous_close - 1.0 if previous_close else 0.0)
        columns["close_to_close_return_5d"].append(current_close / close_5 - 1.0 if close_5 else 0.0)
        columns["close_to_close_return_20d"].append(current_close / close_20 - 1.0 if close_20 else 0.0)
        columns["rolling_volatility_5d"].append(_sample_std(recent_returns_5))
        columns["rolling_volatility_20d"].append(_sample_std(recent_returns_20))
        columns["momentum_5d"].append(current_close / close_5 - 1.0 if close_5 else 0.0)
        columns["momentum_20d"].append(current_close / close_20 - 1.0 if close_20 else 0.0)
        columns["high_low_range_pct"].append((highs[index] - lows[index]) / current_close if current_close else 0.0)
        columns["open_close_range_pct"].append((current_close - current_open) / current_open if current_open else 0.0)
        raw_volume_change = 0.0 if previous_volume == 0 else volumes[index] / previous_volume - 1.0
        columns["volume_change_1d"].append(max(-1.0, min(20.0, raw_volume_change)))

        trailing_closes = closes[: index + 1]
        columns["rsi_14"].append(relative_strength_index(trailing_closes, period=14))
        columns["atr_pct_14"].append(
            average_true_range_pct(highs[: index + 1], lows[: index + 1], trailing_closes, period=14)
        )
        columns["bollinger_pctb_20"].append(bollinger_pctb(trailing_closes, period=20))
        columns["volume_zscore_20"].append(volume_zscore(volumes[: index + 1], period=20))

        long_window_start = max(0, index + 1 - long_window_bars)
        long_trailing_closes = closes[long_window_start : index + 1]
        columns["macd_histogram_norm"].append(macd_histogram_normalized(long_trailing_closes))
        columns["dist_52w_high"].append(distance_from_52w_high(long_trailing_closes, window=long_window_bars))

    return {name: np.asarray(values, dtype=float) for name, values in columns.items()}


def compute_liquidity_replica(
    frame: pd.DataFrame,
    *,
    security_type: str = "equity",
    cross_sectional_window_bars: int = DEFAULT_CROSS_SECTIONAL_WINDOW_BARS,
    typical_spread_by_type: dict[str, float] | None = None,
) -> dict[str, np.ndarray]:
    """Row-faithful replica of train.py::add_liquidity_features()
    (train.py:946-988): log1p dollar volume plus the Corwin-Schultz spread
    proxy over a trailing window, static-spread fallback below two bars."""
    from liquidity.market_liquidity import TYPICAL_SPREAD_BY_TYPE

    spreads = typical_spread_by_type or TYPICAL_SPREAD_BY_TYPE
    fallback = float(spreads.get(str(security_type), 0.001))
    closes = frame["close"].tolist()
    volumes = frame["volume"].tolist()
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()

    log_dollar_volume: list[float] = []
    spread_proxy: list[float] = []
    for index in range(len(frame)):
        log_dollar_volume.append(float(np.log1p(max(closes[index] * volumes[index], 0.0))))
        window_start = max(0, index + 1 - cross_sectional_window_bars)
        window_highs = highs[window_start : index + 1]
        window_lows = lows[window_start : index + 1]
        estimated = estimate_high_low_spread(window_highs, window_lows) if len(window_highs) >= 2 else None
        spread_proxy.append(float(estimated) if estimated is not None else fallback)

    return {
        "liquidity_log_dollar_volume": np.asarray(log_dollar_volume, dtype=float),
        "liquidity_spread_proxy": np.asarray(spread_proxy, dtype=float),
    }


def compute_momentum_long(dataset: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker momentum_20d computed on EACH TICKER'S OWN trading rows -
    position-shift(20) within that ticker's sorted history, exactly how
    engineer_features() consumed each asset's raw frame. Deliberately NOT a
    union-calendar pivot shift: cross-asset calendars differ (crypto trades
    weekends, bonds don't), so a pivot-row shift spans different numbers of
    each ticker's REAL bars - measured drift up to 0.16 absolute on TLT."""
    def _momentum(closes: pd.Series) -> pd.Series:
        return closes / closes.shift(20) - 1.0

    out = dataset[["date", "ticker"]].copy()
    out["momentum_20d"] = dataset.groupby("ticker", sort=False)["close"].transform(_momentum)
    return out


def compute_macro_proxies_replica(
    all_dates: list[str],
    momentum_long: pd.DataFrame,
    *,
    reference_tickers: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Replica of train.py::build_macro_features_by_date()
    (train.py:1126-1189): per-date AS-OF (last value at-or-before the date)
    momentum_20d of five fixed reference tickers fed through the three
    shared macro proxy functions; missing references degrade to each
    function's neutral default. As-of uses each reference ticker's OWN date
    series - never a union calendar."""
    references = {**DEFAULT_MACRO_REFERENCE_TICKERS, **(reference_tickers or {})}

    def _asof_values(ticker: str) -> list[float | None]:
        rows = momentum_long[momentum_long["ticker"] == ticker]
        if rows.empty:
            return [None] * len(all_dates)
        series = pd.Series(
            rows["momentum_20d"].to_numpy(dtype=float),
            index=pd.Index(rows["date"], name="date"),
        ).sort_index()
        filled = series.reindex(all_dates).ffill()
        return [None if pd.isna(value) else float(value) for value in filled]

    long_value = _asof_values(references["long_duration"])
    short_value = _asof_values(references["short_duration"])
    high_yield_value = _asof_values(references["high_yield"])
    investment_grade_value = _asof_values(references["investment_grade"])
    crypto_value = _asof_values(references["crypto"])

    result = pd.DataFrame({"date": all_dates})
    result["macro_yield_curve_slope_proxy"] = [
        yield_curve_slope_proxy(long_v, short_v) for long_v, short_v in zip(long_value, short_value)
    ]
    result["macro_credit_spread_proxy"] = [
        credit_spread_proxy(hy, ig) for hy, ig in zip(high_yield_value, investment_grade_value)
    ]
    result["macro_crypto_risk_appetite_proxy"] = [
        crypto_risk_appetite_proxy(c) for c in crypto_value
    ]
    return result


def compute_cs_momentum_rank_replica(momentum_long: pd.DataFrame) -> pd.DataFrame:
    """EXACT replica of build_cross_sectional_momentum_rank_features()
    (train.py:2118-2153): per-date dict over every ticker WITH A ROW that
    date - values may be NaN for young series; a NaN counts in the shared
    function's len() DENOMINATOR while never satisfying its </== comparisons
    - and thin dates (<2 entries) return the 0.5 neutral."""
    records: list[tuple[str, str, float]] = []
    for date, group in momentum_long.groupby("date", sort=True):
        momentum_by_symbol = dict(zip(group["ticker"], group["momentum_20d"]))
        for ticker in momentum_by_symbol:
            rank = cross_sectional_momentum_rank(momentum_by_symbol, ticker)
            records.append((date, ticker, rank))
    return pd.DataFrame(records, columns=["date", "ticker", "cs_momentum_rank_recomputed"])


def summarize_comparison(
    stored_scaled: np.ndarray,
    recomputed_raw: np.ndarray,
    mean: float,
    scale: float,
    clip: float,
    warmup_excluded: int = 0,
) -> dict[str, Any]:
    """Forward-direction comparison for ONE feature over ONE ticker slice:
    recomputed raw -> scaler artifact -> stored column. Warmup rows (where a
    replica legitimately cannot see pre-dataset history) are excluded from
    the head of each ticker's series by the caller before this runs."""
    valid = ~(np.isnan(stored_scaled) | np.isnan(recomputed_raw))
    stored_valid = stored_scaled[valid]
    expected = forward_scale(recomputed_raw[valid], mean, scale, clip)
    delta = np.abs(expected - stored_valid)
    saturated = int(np.sum(np.abs(stored_valid) >= clip - 1e-9))
    mismatches = int(np.sum(delta > 1e-9))
    return {
        "n_compared": int(valid.sum()),
        "warmup_excluded_per_ticker": warmup_excluded,
        "max_abs_delta": float(delta.max()) if delta.size else None,
        "mean_abs_delta": float(delta.mean()) if delta.size else None,
        "n_mismatch_gt_1e-9": mismatches,
        "n_saturated_at_clip": saturated,
        "verdict": "PASS" if mismatches == 0 else "FAIL",
    }
