"""Cross-symbol book neutralization (V5.1 Phase 0/1, item 6 of the V5.1
roadmap - development/Problems.md).

Every existing weight computation in this codebase (risk/position_sizing.py,
main.py:1723-1726's inline book-role formula) is per-symbol: it never looks
at what any other symbol in the same bar's book is doing. This module is the
one deliberate cross-symbol pass, applied once per rebalance bar AFTER every
symbol's raw book weight is known - it never changes a symbol's role (long/
short), only rescales magnitudes so the book as a whole is dollar-neutral,
sector-neutral, and gross-capped.

Deliberately its own module, not folded into portfolio/book_construction.py:
build_rank_based_book() decides WHICH symbols and WHICH side (a per-bar,
whole-universe decision already); this module decides HOW MUCH, given that
selection is already final - same separation-of-concerns split
book_construction.py's own docstring draws between itself and
risk/position_sizing.py.
"""

from __future__ import annotations


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def apply_book_neutrality(
    raw_weights_by_symbol: dict[str, float],
    *,
    sector_by_symbol: dict[str, str],
    dollar_neutral: bool,
    sector_neutral: bool,
    gross_exposure_cap: float,
    max_weight_per_name: float,
    sector_max_net_weight: float,
) -> tuple[dict[str, float], dict]:
    """Deterministic 4-step pipeline over an already-selected book's raw
    per-symbol weights (main.py's today-formula:
    min(max_position_weight, 0.10 + 0.15*confidence) * book_role_multiplier,
    one entry per book-selected symbol only - not the whole universe).

    Steps, always in this order:
      1. Per-name cap: clip every weight to [-max_weight_per_name, +max_weight_per_name].
      2. Sector neutrality (if sector_neutral): within each sector bucket,
         subtract the bucket's mean signed weight (makes the bucket's raw
         net exactly zero), then re-clip to the per-name cap. Re-clipping
         can reintroduce a nonzero net - any bucket whose |net| still
         exceeds sector_max_net_weight after that is SHRUNK (never
         amplified) by a uniform per-bucket factor so its net lands exactly
         at the cap.
      3. Dollar neutrality (if dollar_neutral): scale the LARGER leg down
         so sum(long) == sum(|short|). Scale-down only, never up - this can
         never increase gross exposure. A one-sided book (no shorts, or no
         longs) has nothing to balance against; that step is skipped for
         that bar rather than zeroing the book out, and the skip is
         recorded in diagnostics.
      4. Gross cap: scale everything by min(1, gross_exposure_cap / gross).

    Returns (weights, diagnostics) where diagnostics is JSON-serializable
    (state.json's state["book_neutrality"]):
      {"pre_gross", "post_gross", "net_before", "net_after",
       "per_sector_net": {sector: net_weight, ...}, "steps_applied": [...]}

    Never raises. An empty input returns ({}, diagnostics-with-zeros). Pure
    dict-in/dict-out - result does not depend on input dict iteration order
    (every step is a symmetric sum/mean over the group, not a positional
    operation)."""
    steps_applied: list[str] = []

    if not raw_weights_by_symbol:
        return {}, {
            "pre_gross": 0.0,
            "post_gross": 0.0,
            "net_before": 0.0,
            "net_after": 0.0,
            "per_sector_net": {},
            "steps_applied": ["empty_book_no_op"],
        }

    net_before = sum(raw_weights_by_symbol.values())

    # Step 1: per-name cap.
    weights = {
        symbol: _clip(weight, -max_weight_per_name, max_weight_per_name)
        for symbol, weight in raw_weights_by_symbol.items()
    }
    steps_applied.append("per_name_cap")

    # Step 2: sector neutrality.
    if sector_neutral:
        symbols_by_sector: dict[str, list[str]] = {}
        for symbol in weights:
            sector = sector_by_symbol.get(symbol, "Unknown")
            symbols_by_sector.setdefault(sector, []).append(symbol)

        for sector, members in symbols_by_sector.items():
            if len(members) < 2:
                # A single-member bucket has no within-bucket peer to
                # demean against - demeaning it would just zero the one
                # symbol out, which is a much larger behavior change than
                # "neutralize this sector" implies. Left untouched, same
                # convention as build_rank_based_book()'s thin-pool guards.
                continue
            bucket_mean = sum(weights[symbol] for symbol in members) / len(members)
            for symbol in members:
                weights[symbol] = _clip(
                    weights[symbol] - bucket_mean, -max_weight_per_name, max_weight_per_name
                )

            bucket_net = sum(weights[symbol] for symbol in members)
            if abs(bucket_net) > sector_max_net_weight and abs(bucket_net) > 0.0:
                shrink_factor = sector_max_net_weight / abs(bucket_net)
                for symbol in members:
                    weights[symbol] *= shrink_factor
        steps_applied.append("sector_neutral")

    # Step 3: dollar neutrality - scale the larger leg down only.
    if dollar_neutral:
        long_sum = sum(weight for weight in weights.values() if weight > 0.0)
        short_sum = sum(-weight for weight in weights.values() if weight < 0.0)
        if long_sum > 0.0 and short_sum > 0.0:
            if long_sum > short_sum:
                factor = short_sum / long_sum
                weights = {
                    symbol: (weight * factor if weight > 0.0 else weight) for symbol, weight in weights.items()
                }
            elif short_sum > long_sum:
                factor = long_sum / short_sum
                weights = {
                    symbol: (weight * factor if weight < 0.0 else weight) for symbol, weight in weights.items()
                }
            steps_applied.append("dollar_neutral")
        else:
            steps_applied.append("dollar_neutral_skipped_one_sided_book")

    # Step 4: gross exposure cap.
    gross = sum(abs(weight) for weight in weights.values())
    if gross > gross_exposure_cap and gross > 0.0:
        factor = gross_exposure_cap / gross
        weights = {symbol: weight * factor for symbol, weight in weights.items()}
        steps_applied.append("gross_cap")

    per_sector_net: dict[str, float] = {}
    for symbol, weight in weights.items():
        sector = sector_by_symbol.get(symbol, "Unknown")
        per_sector_net[sector] = per_sector_net.get(sector, 0.0) + weight

    post_gross = sum(abs(weight) for weight in weights.values())
    net_after = sum(weights.values())

    diagnostics = {
        "pre_gross": sum(abs(weight) for weight in raw_weights_by_symbol.values()),
        "post_gross": post_gross,
        "net_before": net_before,
        "net_after": net_after,
        "per_sector_net": per_sector_net,
        "steps_applied": steps_applied,
    }
    return weights, diagnostics
