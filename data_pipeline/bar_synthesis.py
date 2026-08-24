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
    )


def pad_sequence_history(history: list[list[float]], window_size: int) -> list[list[float]]:
    """Left-pads a rolling per-symbol feature-history buffer with zero
    vectors up to window_size (main.py::_pad_sequence_history verbatim).
    Pure, no side effects."""
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
