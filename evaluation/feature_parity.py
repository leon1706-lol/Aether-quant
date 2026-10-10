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


_MIDNIGHT_SECURITY_TYPES = ("crypto", "forex")


def forex_calendar_momentum_rows(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """(date, ticker, momentum_20d) for one forex pair on Lean's fill-forward calendar (flat bars on open days without
    a row, features/cross_asset_timing.py), INCLUDING the filler rows: live's forex pool holds Sunday's flat-bar
    momentum at Monday's equity tick, which no dataset row carries. `frame` needs `date` and `close`."""
    from features.cross_asset_timing import day_ordinal, fill_forward_open_forex_days

    ordered = frame.sort_values("date")
    ordinals, closes = fill_forward_open_forex_days([day_ordinal(stamp) for stamp in ordered["date"]], ordered["close"].tolist())
    momentum = [float("nan")] + [
        closes[i] / closes[max(0, i - 20)] - 1.0 if closes[max(0, i - 20)] else float("nan") for i in range(1, len(closes))
    ]
    return pd.DataFrame({"date": [pd.Timestamp.fromordinal(o) for o in ordinals], "ticker": ticker, "momentum_20d": momentum})


def build_momentum_pool(dataset: pd.DataFrame, security_types: dict[str, str] | None) -> pd.DataFrame:
    """(date, ticker, momentum_20d) for the cross-asset replicas: each ticker's stored momentum_20d, except forex pairs,
    whose momentum is re-derived on Lean's fill-forward calendar WITH the filler rows (forex_calendar_momentum_rows)."""
    security_types = security_types or {}
    stored = dataset[["date", "ticker", "momentum_20d"]]
    forex_tickers = {ticker for ticker, kind in security_types.items() if kind == "forex"}
    parts = [stored[~stored["ticker"].isin(forex_tickers)]]
    for ticker in forex_tickers:
        rows = dataset[dataset["ticker"] == ticker]
        if not rows.empty:
            parts.append(forex_calendar_momentum_rows(rows.assign(date=pd.to_datetime(rows["date"])), ticker))
    result = pd.concat(parts, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"])
    return result


def _momentum_arrays(momentum_long: pd.DataFrame, security_types: dict[str, str] | None) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """ticker -> (availability keys, stored momentum_20d) on each ticker's OWN rows. A daily bar is visible once its
    period closed: equity at that day's close (ordinal + 0.5), crypto/forex at the next midnight (ordinal + 1.0).
    The stored column (computed on the raw, pre-dropna history) is used rather than re-deriving momentum from the
    dataset's closes, which have holes where the label guard dropped rows."""
    security_types = security_types or {}
    arrays: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for ticker, group in momentum_long.groupby("ticker", sort=False):
        group = group.sort_values("date")
        ordinals = np.array([pd.Timestamp(stamp).toordinal() for stamp in group["date"]], dtype=float)
        offset = 1.0 if security_types.get(ticker, "equity") in _MIDNIGHT_SECURITY_TYPES else 0.5
        arrays[ticker] = (ordinals + offset, group["momentum_20d"].to_numpy(dtype=float))
    return arrays


def _momentum_before(arrays: dict[str, tuple[np.ndarray, np.ndarray]], key: float) -> dict[str, float]:
    """Each ticker's latest stored momentum among the bars visible STRICTLY before `key` - what main.py's
    latest_momentum_by_symbol holds when it builds the payload at the start of a tick (pool includes stale tickers)."""
    momentum: dict[str, float] = {}
    for ticker, (keys, values) in arrays.items():
        end = int(np.searchsorted(keys, key, side="left"))
        if end == 0:
            continue
        value = float(values[end - 1])
        if np.isfinite(value):
            momentum[ticker] = value
    return momentum


def _row_keys(momentum_long: pd.DataFrame, security_types: dict[str, str] | None) -> pd.Series:
    security_types = security_types or {}
    ordinals = np.array([pd.Timestamp(stamp).toordinal() for stamp in momentum_long["date"]], dtype=float)
    offsets = np.array([1.0 if security_types.get(ticker, "equity") in _MIDNIGHT_SECURITY_TYPES else 0.5 for ticker in momentum_long["ticker"]])
    return pd.Series(ordinals + offsets, index=momentum_long.index)


def compute_macro_proxies_replica(
    momentum_long: pd.DataFrame,
    security_types: dict[str, str] | None = None,
    *,
    reference_tickers: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Replica of train.py::build_macro_features_by_date() (Problems.md #135): the three macro proxies a row
    sees are those of the reference tickers' momentum over the bars visible STRICTLY before the row's own tick,
    fed through the shared proxy functions. `momentum_long`: (ticker, date, momentum_20d); one output row per input row."""
    references = {**DEFAULT_MACRO_REFERENCE_TICKERS, **(reference_tickers or {})}
    arrays = _momentum_arrays(momentum_long, security_types)
    keys = _row_keys(momentum_long, security_types)
    by_key: dict[float, tuple[float, float, float]] = {}
    for key in sorted(set(keys)):
        momentum = _momentum_before(arrays, key)
        by_key[key] = (
            yield_curve_slope_proxy(momentum.get(references["long_duration"]), momentum.get(references["short_duration"])),
            credit_spread_proxy(momentum.get(references["high_yield"]), momentum.get(references["investment_grade"])),
            crypto_risk_appetite_proxy(momentum.get(references["crypto"])),
        )
    result = momentum_long[["date", "ticker"]].copy()
    rows = [by_key[key] for key in keys]
    result["macro_yield_curve_slope_proxy"] = [row[0] for row in rows]
    result["macro_credit_spread_proxy"] = [row[1] for row in rows]
    result["macro_crypto_risk_appetite_proxy"] = [row[2] for row in rows]
    return result


def compute_cs_momentum_rank_replica(momentum_long: pd.DataFrame, security_types: dict[str, str] | None = None) -> pd.DataFrame:
    """Replica of train.py::build_cross_sectional_momentum_rank_features() (Problems.md #135): the shared
    cross_sectional_momentum_rank() over every ticker's momentum from the bars visible strictly before the
    row's own tick - the pool includes tickers whose latest bar is old, as main.py's windows do."""
    arrays = _momentum_arrays(momentum_long, security_types)
    keys = _row_keys(momentum_long, security_types)
    pools = {key: _momentum_before(arrays, key) for key in sorted(set(keys))}
    ranks = [cross_sectional_momentum_rank(pools[key], ticker) for key, ticker in zip(keys, momentum_long["ticker"])]
    result = momentum_long[["date", "ticker"]].copy()
    result["cs_momentum_rank_recomputed"] = ranks
    return result


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
