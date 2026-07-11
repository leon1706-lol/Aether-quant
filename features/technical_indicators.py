"""Shared, pure technical-indicator implementations (Phase 6) - imported by
BOTH train.py::engineer_features() (offline, full history via a Python
loop) and main.py::_build_model_input() (runtime, one bar at a time from a
rolling deque) so both sides compute every indicator identically by
construction, not by hand-matched duplicated formulas (the train/runtime
parity convention this codebase already uses for every other feature, see
development/Changelog.md).

Each function takes a plain list of trailing values (already sliced to the
right window by the caller) and returns a single scalar float, matching
how train.py::engineer_features()'s existing loop already computes
close_to_close_return_5d/rolling_volatility_20d/etc one row at a time from
Python lists, not vectorized pandas. Every function returns a documented
neutral default when there isn't enough history yet, so nothing ever
raises and no extra dropna is needed - the same "adaptive lookback"
contract every existing base feature already has.

Chosen to fit main.py's existing self.symbol_windows (deque(maxlen=25), up
to 24 trailing bars - see train.py::CROSS_SECTIONAL_WINDOW_BARS) except
macd_histogram_normalized()/distance_from_52w_high(), which need a longer
history and are read from a separate, longer buffer (main.py's
self.symbol_long_windows, deque(maxlen=260)) - main.py:264-268 explicitly
forbids resizing symbol_windows itself, so a second buffer is the only
option for indicators needing more than ~24 bars.
"""

from __future__ import annotations

RSI_NEUTRAL = 50.0
BOLLINGER_PCTB_NEUTRAL = 0.5
VOLUME_ZSCORE_NEUTRAL = 0.0
MACD_HISTOGRAM_NEUTRAL = 0.0
DIST_52W_HIGH_NEUTRAL = 0.0
CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL = 0.5


def relative_strength_index(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI over the trailing `period` closes (needs period+1
    closes for period price changes) - a bounded [0, 100] mean-reversion
    state, a genuinely different signal shape from any existing
    return/volatility feature (bounded and non-linear, vs. an unbounded
    return). Returns RSI_NEUTRAL (50.0, "neither overbought nor oversold")
    when fewer than period+1 closes are available."""
    if len(closes) < period + 1:
        return RSI_NEUTRAL
    window = closes[-(period + 1):]
    gains = []
    losses = []
    for index in range(1, len(window)):
        change = window[index] - window[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else RSI_NEUTRAL
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def average_true_range_pct(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """ATR (Wilder's simple-average variant) as a % of the latest close -
    a gap-aware volatility measure distinct from rolling_volatility_20d's
    close-to-close-only stddev (a true range captures overnight
    gaps/intraday extremes a close-only measure misses entirely). Needs
    period+1 bars (period true-range values, each needing a previous
    close). Returns 0.0 when insufficient history or the latest close is
    zero."""
    if len(closes) < period + 1:
        return 0.0
    true_ranges = []
    for index in range(len(closes) - period, len(closes)):
        high = highs[index]
        low = lows[index]
        previous_close = closes[index - 1]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr = sum(true_ranges) / period
    latest_close = closes[-1]
    return atr / latest_close if latest_close else 0.0


def bollinger_pctb(closes: list[float], period: int = 20, num_std: float = 2.0) -> float:
    """%B: where the latest close sits within its trailing `period`-bar
    Bollinger Band, normalized so 0.0 = lower band, 1.0 = upper band, 0.5 =
    the middle (SMA) - a bounded, self-normalizing measure of price
    extension, distinct from the raw high_low_range_pct/rolling_volatility
    features already in this codebase. Returns BOLLINGER_PCTB_NEUTRAL
    (0.5) when fewer than `period` closes exist yet, or the band has zero
    width (constant price - degenerate either way, not a real signal)."""
    if len(closes) < period:
        return BOLLINGER_PCTB_NEUTRAL
    window = closes[-period:]
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / period
    std = variance ** 0.5
    if std == 0:
        return BOLLINGER_PCTB_NEUTRAL
    upper = mean + num_std * std
    lower = mean - num_std * std
    return (closes[-1] - lower) / (upper - lower)


def volume_zscore(volumes: list[float], period: int = 20) -> float:
    """Latest volume's z-score against its own trailing `period`-bar
    mean/std - a self-normalizing participation measure. Robust to the
    exact class of raw-volume-unit discontinuity that broke
    volume_change_1d before its clamp fix (see development/Problems.md):
    a z-score compresses a single extreme outlier's effect on the bar it
    occurs on relative to a raw ratio, though a persisting outlier would
    still distort the trailing window's own mean/std for subsequent bars,
    same as any rolling statistic. Returns VOLUME_ZSCORE_NEUTRAL (0.0) when
    fewer than `period` volumes exist yet, or the trailing window has zero
    variance (a flat volume series)."""
    if len(volumes) < period:
        return VOLUME_ZSCORE_NEUTRAL
    window = volumes[-period:]
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / period
    std = variance ** 0.5
    return (volumes[-1] - mean) / std if std else VOLUME_ZSCORE_NEUTRAL


def cross_sectional_momentum_rank(momentum_by_symbol: dict[str, float], symbol: str) -> float:
    """Per-date percentile rank ([0, 1], ties averaged - matches pandas'
    .rank(pct=True) convention, same as
    build_cross_sectional_rank_targets()'s target-side ranking) of
    `symbol`'s own momentum_20d among every symbol present in
    `momentum_by_symbol` - the best-documented daily cross-sectional
    anomaly (12-1 month momentum), reusing the exact percentile-rank
    convention already established for the ranking targets. Returns
    CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL (0.5, the exact middle) when
    `symbol` has fewer than 2 total entries to rank against (undefined
    otherwise, e.g. a single-asset universe or a thin trading day)."""
    if len(momentum_by_symbol) < 2 or symbol not in momentum_by_symbol:
        return CROSS_SECTIONAL_MOMENTUM_RANK_NEUTRAL
    own_value = momentum_by_symbol[symbol]
    values = list(momentum_by_symbol.values())
    count_less = sum(1 for value in values if value < own_value)
    count_equal = sum(1 for value in values if value == own_value)
    return (count_less + (count_equal + 1) / 2.0) / len(values)


def macd_histogram_normalized(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> float:
    """MACD histogram (MACD line - its own signal line), normalized by the
    latest close so its scale is comparable across assets at very
    different price levels (a raw MACD histogram is in the asset's own
    raw price units). Both EMAs are recomputed fresh from the trailing
    window passed in each call (an approximation of a true "since
    inception" EMA, which never fully forgets old data) - a deliberate
    simplification so this is exactly reproducible from a bounded window
    on both the offline (full history slice) and runtime
    (self.symbol_long_windows, maxlen=260) sides, with no persistent EMA
    state to keep in sync between them. Needs at least `slow + signal`
    closes; returns MACD_HISTOGRAM_NEUTRAL (0.0) otherwise, or when the
    latest close is zero."""
    if len(closes) < slow + signal or closes[-1] == 0:
        return MACD_HISTOGRAM_NEUTRAL

    def _ema_series(values: list[float], period: int) -> list[float]:
        multiplier = 2.0 / (period + 1)
        ema_values = [values[0]]
        for value in values[1:]:
            ema_values.append((value - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values

    fast_ema = _ema_series(closes, fast)
    slow_ema = _ema_series(closes, slow)
    macd_line = [fast_value - slow_value for fast_value, slow_value in zip(fast_ema, slow_ema)]
    signal_line = _ema_series(macd_line, signal)
    histogram = macd_line[-1] - signal_line[-1]
    return histogram / closes[-1]


def distance_from_52w_high(closes: list[float], window: int = 252) -> float:
    """close / trailing-`window`-bar max close - 1: how far the latest
    close sits below its own trailing high (0.0 = at the high, negative
    otherwise) - a genuine anchoring-effect measure distinct from
    everything else in this codebase (every existing return/momentum
    feature is relative to a bar N periods ago, not to a rolling extreme).
    Returns DIST_52W_HIGH_NEUTRAL (0.0) when fewer than 2 closes exist yet,
    or the trailing high is zero."""
    if len(closes) < 2:
        return DIST_52W_HIGH_NEUTRAL
    trailing_high = max(closes[-window:])
    return closes[-1] / trailing_high - 1.0 if trailing_high else DIST_52W_HIGH_NEUTRAL
