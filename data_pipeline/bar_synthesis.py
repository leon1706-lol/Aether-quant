"""V5.3.10 - pure functions extracted from main.py so the live-path logic
they implement becomes unit-testable outside Lean's runtime (established
pattern: evaluate_non_model_exit(), compute_incremental_order_quantity(),
etc.). Each function is a VERBATIM copy of the corresponding main.py
method body - see each function's docstring for its origin line."""

from __future__ import annotations

from types import SimpleNamespace


def midpoint_bar_from_quote_bar(quote_bar):
    """V4.6 - forex quote-bar (bid/ask) to trade-bar-shaped midpoint OHLC
    (main.py::_midpoint_bar_from_quote_bar verbatim). Volume is always
    0.0 - forex quote data carries no trade-volume concept. Returns None
    (never raises) when no quote bar exists or it's missing a bid/ask side."""
    if quote_bar is None or quote_bar.Bid is None or quote_bar.Ask is None:
        return None
    return SimpleNamespace(
        open=(float(quote_bar.Bid.Open) + float(quote_bar.Ask.Open)) / 2.0,
        high=(float(quote_bar.Bid.High) + float(quote_bar.Ask.High)) / 2.0,
        low=(float(quote_bar.Bid.Low) + float(quote_bar.Ask.Low)) / 2.0,
        close=(float(quote_bar.Bid.Close) + float(quote_bar.Ask.Close)) / 2.0,
        volume=0.0,
        # V6.0.0: Lean's fill-forward bar is a clone of the previous bar (same OHLC) flagged IsFillForward; one second
        # before its end time is the bar's own date in any time zone (the date the dataset row carries).
        is_fill_forward=bool(_first_attribute(quote_bar, ("IsFillForward", "is_fill_forward"), False)),
        end_time=_first_attribute(quote_bar, ("EndTime", "end_time"), None),
    )


def _first_attribute(source, names: tuple[str, ...], default):
    for name in names:
        try:
            value = getattr(source, name)
        except Exception:  # noqa: BLE001 - a Lean proxy may raise on a missing member
            continue
        if value is not None and not callable(value):
            return value
    return default


def flatten_fill_forward_bar(bar: dict, previous_close: float) -> dict:
    """A fill-forward bar the way the training dataset builds it (`train.fill_forward_forex_frame`): flat at the
    previous close with no volume. Lean's own fill-forward bar repeats the previous bar's range, so a trailing ATR or
    high-low spread window that contains one differs from the dataset's (V6.0.0, todo lead 4)."""
    close = float(previous_close)
    return {"open": close, "high": close, "low": close, "close": close, "volume": 0.0}


def pad_sequence_history(history: list[list[float]], window_size: int) -> list[list[float]]:
    """Left-pads a rolling per-symbol feature-history buffer with zero
    vectors up to window_size (main.py::_pad_sequence_history verbatim).
    Pure, no side effects. An empty history returns `window_size` all-zero
    vectors of the model's width when inferable, else raises a clear
    ValueError instead of IndexError (V5.4.7 #123)."""
    if not history:
        raise ValueError(
            "pad_sequence_history: empty history - feature width cannot be "
            "inferred; callers guard this before calling (main.py's own "
            "truthy filters), so reaching here means a caller contract broke."
        )
    input_width = len(history[0])
    padding_needed = window_size - len(history)
    return [[0.0] * input_width for _ in range(max(0, padding_needed))] + list(history)


def adaptive_sell_threshold(
    *,
    sell_threshold: float,
    history: list[float] | None,
    band_enabled: bool,
    min_observations: int,
    band_percentile: float,
) -> float:
    """Pure lookup + percentile over accumulated probability_up history
    (main.py::_effective_sell_threshold verbatim). Never adapts ABOVE the
    static threshold - the band only makes selling easier."""
    if not band_enabled:
        return sell_threshold
    if history is None or len(history) < min_observations:
        return sell_threshold
    sorted_history = sorted(history)
    index = max(0, min(len(sorted_history) - 1, int(band_percentile * len(sorted_history))))
    return min(sell_threshold, sorted_history[index])


def derive_signal(
    probability_up: float,
    *,
    decision_threshold: float,
    buy_threshold: float,
    effective_sell_threshold: float,
    max_position_weight: float,
    record_observation=None,
    symbol_key: str | None = None,
) -> tuple[str, float, float]:
    """Signal classification extracted from main.py::_derive_signal()
    (verbatim arithmetic). `record_observation(symbol_key, probability_up)`
    is an optional callback so callers can preserve the observation-recording
    side effect without this function needing state."""
    confidence = abs(probability_up - decision_threshold) / max(1.0 - decision_threshold, decision_threshold)
    confidence = max(0.0, min(confidence, 1.0))

    def _record():
        if record_observation is not None and symbol_key is not None:
            record_observation(symbol_key, probability_up)

    if probability_up >= buy_threshold:
        target_weight = min(max_position_weight, 0.10 + 0.15 * confidence)
        _record()
        return "buy", confidence, target_weight

    if probability_up <= effective_sell_threshold:
        target_weight = -min(max_position_weight, 0.10 + 0.15 * confidence)
        _record()
        return "sell", confidence, target_weight

    _record()
    return "hold", confidence, 0.0
