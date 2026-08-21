"""V5.3.5 Workstream B (development/Problems.md #91/#100) - the XOM
feature-level investigation's pure diff core.

`reconcile_feature_snapshot()` compares a single symbol's logged LIVE
feature values (the `feature_snapshot.base_features` dict main.py's
book-history diagnostic captured for that bar) against the same symbol/
date row from `ml/datasets/full_dataset.csv` - the precomputed feature
columns `train.py::engineer_features()` wrote from the same underlying
`features/technical_indicators.py` functions the live path also calls.
A divergence between the two for the same (ticker, date) is the concrete
root cause this tool exists to surface or rule out: XOM is the one tracked
ticker whose live-vs-offline book-selection mismatch never resolved across
#91/#97/#99/#100 (140 appearances across 9 real runs, 77% mismatch, the
worst of the five tracked tickers), and the existing
`book_history.jsonl` records `raw_rank_score`/`feature_ready`/
`trading_eligible` per symbol but no raw feature values - so nothing to
diff against the offline dataset until this field exists.

Pure: no I/O, no `self`, never raises on well-formed inputs - same
shaping-only convention `reconcile_book_history_date()`'s own
`_build_reconciliation_result()` already established. The CLI
(`aq evaluate --reconcile-features`) owns the dataset load, the run-
segmenting, the (ticker, date) join, and the per-date loop calling this
function; this module only computes the diff, so it is unit-testable
without a Lean backtest or a real dataset.

What this function compares and what it deliberately does NOT:
- Compares ONLY features present in the logged `base_features` snapshot
  (main.py::_build_model_input()'s output - the price/volume-derived
  technicals, regime/topology/liquidity signals, and peer-return features
  the model actually saw live). The offline dataset has MORE columns
  (expanded one-hot `regime_trend_*`/`topology_risk_*`/`bond_*`/`alt_*`/
  `sens_*`/`macro_*`/`futures_*`/`options_*` - each derived in
  `_build_regime_payload`/`_build_topology_payload` and flattened into
  separate dataset columns by `train.py::engineer_features()`); those
  appear in `features_only_in_offline` (informational, not a divergence)
  since the live path carries them as structured sub-payloads, not as
  the flat keys this function compares.
- A feature present in the snapshot but NOT in the offline row is a
  `features_only_in_logged` entry (informational - the live path computed
  something the offline pipeline didn't, e.g. a feature added after the
  dataset was built), NOT a divergence either.
- Only the INTERSECTION is diffed, with `abs_delta` and `relative_delta`
  per feature, sorted by `abs_delta` desc so the worst offender is first.
- `offline_value` is read via `.get()` - a NaN/None column in the offline
  row for that date degrades to `None`, same convention the existing
  reconciliation uses for missing raw scores.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_ABS_TOLERANCE = 1e-9
DEFAULT_REL_TOLERANCE = 1e-6
_RELATIVE_EPS = 1e-12


def _coerce_float(value: Any) -> float | None:
    """Coerce a dataset value to float, returning None for NaN/None/
    non-numeric - the offline dataset stores features as CSV strings that
    pandas reads as float64 but may carry NaN for warmup-period rows.
    Mirrors the degrade-on-missing convention every other reconciliation
    field uses, never raises."""
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if as_float != as_float:  # NaN - the only float != itself
        return None
    return as_float


def reconcile_feature_snapshot(
    logged_feature_snapshot: Mapping[str, Any],
    offline_dataset_row: Mapping[str, Any],
    *,
    abs_tolerance: float = DEFAULT_ABS_TOLERANCE,
    rel_tolerance: float = DEFAULT_REL_TOLERANCE,
) -> dict:
    """Compare one logged feature snapshot (one symbol, one date's
    `base_features` dict) against the matching offline dataset row for
    the same (ticker, date).

    Args:
        logged_feature_snapshot: the `base_features` dict main.py's
            `_build_model_input()` built for that bar, as captured in the
            `feature_snapshot` field of one `book_history.jsonl` record's
            per-symbol entry. Only the feature names present here are
            diffed - the live path is the source of truth for what the
            model actually saw.
        offline_dataset_row: the matching `full_dataset.csv` row (a
            pandas Series or dict) for the same ticker/date, keyed by
            column name. Missing/NaN columns degrade to None, not a crash.
        abs_tolerance: features whose `abs_delta` is at or below this are
            considered matched (float reconstruction noise). Default
            1e-9 - the live and offline paths both call the same pure
            `features/technical_indicators.py` functions, so a genuine
            match should be bit-identical up to float order noise; this
            default is deliberately tight so even small systematic drift
            surfaces.
        rel_tolerance: features whose `relative_delta` is at or below
            this are also considered matched (covers the case where
            abs_delta is tiny in absolute terms but the offline value is
            also tiny - a rel floor avoids noise on near-zero features).

    Returns:
        {"features_compared": int,
         "features_matched": int,
         "features_diverged": int,
         "max_abs_delta": float | None,
         "feature_deltas": list[dict], sorted by abs_delta desc, each
            {"feature", "logged_value", "offline_value", "abs_delta",
             "relative_delta", "diverged": bool},
         "features_only_in_logged": sorted list[str],
         "features_only_in_offline": sorted list[str]}

    `max_abs_delta` is None only when zero features were compared (the
    snapshot and the row share no feature names); 0.0 when all compared
    features match exactly. `features_diverged` counts features whose
    abs_delta exceeds BOTH tolerances (abs AND rel, not either - a near-
    zero offline value with a tiny abs_delta but large relative_delta is
    noise, not a real divergence).
    """
    logged_keys = set(logged_feature_snapshot.keys())
    offline_keys = set(offline_dataset_row.keys())
    common = sorted(logged_keys & offline_keys)

    feature_deltas: list[dict] = []
    max_abs_delta: float | None = None
    matched = 0
    diverged = 0

    for feature in common:
        logged_value = _coerce_float(logged_feature_snapshot.get(feature))
        offline_value = _coerce_float(offline_dataset_row.get(feature))
        # Either side missing/NaN: no comparison possible for this feature
        # - degrade to None rather than a spurious "diverged" or "matched".
        if logged_value is None or offline_value is None:
            feature_deltas.append({
                "feature": feature,
                "logged_value": logged_value,
                "offline_value": offline_value,
                "abs_delta": None,
                "relative_delta": None,
                "diverged": False,
            })
            continue

        abs_delta = abs(offline_value - logged_value)
        relative_delta = abs_delta / max(abs(offline_value), _RELATIVE_EPS)
        is_diverged = abs_delta > abs_tolerance and relative_delta > rel_tolerance

        feature_deltas.append({
            "feature": feature,
            "logged_value": logged_value,
            "offline_value": offline_value,
            "abs_delta": abs_delta,
            "relative_delta": relative_delta,
            "diverged": is_diverged,
        })
        if is_diverged:
            diverged += 1
        else:
            matched += 1
        if max_abs_delta is None or abs_delta > max_abs_delta:
            max_abs_delta = abs_delta

    feature_deltas.sort(key=lambda entry: (entry["abs_delta"] is None, -(entry["abs_delta"] or 0.0)))

    return {
        "features_compared": len(common),
        "features_matched": matched,
        "features_diverged": diverged,
        "max_abs_delta": max_abs_delta,
        "feature_deltas": feature_deltas,
        "features_only_in_logged": sorted(logged_keys - offline_keys),
        "features_only_in_offline": sorted(offline_keys - logged_keys),
    }


def summarize_feature_reconciliation(per_date_results: list[dict]) -> dict:
    """Aggregate a list of per-date `reconcile_feature_snapshot()` results
    (one per logged record for the target symbol) into a single report,
    mirroring `summarize_book_history_reconciliation()`'s shape: an empty
    list returns a defined all-zero summary, never raises.

    Surfaces WHICH specific features diverge most often and by how much -
    the XOM investigation's entire point (a per-feature root cause, not a
    single "mismatch" number). A feature that diverges on 77% of XOM's
    appearances but 0% of every other tracked ticker's is the concrete
    signal this tool exists to produce.

    Returns:
        {"num_dates": int,
         "num_dates_with_comparison": int,
         "num_features_compared_per_date": {"min": int|None, "max": int|None,
          "mean": float|None},
         "total_divergences": int,
         "dates_with_any_divergence": int,
         "features_diverged_most_often": list[{"feature", "diverged_count",
            "diverged_fraction", "max_abs_delta", "mean_abs_delta"}]
            sorted by diverged_count desc, capped at 20,
         "features_never_compared": sorted list[str] - features present in
            every logged snapshot but missing from the offline row every
            time (e.g. a feature added live after the dataset was built).}
    """
    num_dates = len(per_date_results)
    if num_dates == 0:
        return {
            "num_dates": 0,
            "num_dates_with_comparison": 0,
            "num_features_compared_per_date": {"min": None, "max": None, "mean": None},
            "total_divergences": 0,
            "dates_with_any_divergence": 0,
            "features_diverged_most_often": [],
            "features_never_compared": [],
        }

    compared_counts: list[int] = []
    dates_with_any_divergence = 0
    total_divergences = 0
    feature_divergence_counts: dict[str, list[float]] = {}
    feature_presence_in_logged: dict[str, int] = {}
    feature_compared_count: dict[str, int] = {}
    only_in_logged_accumulator: dict[str, int] = {}

    for result in per_date_results:
        compared = result.get("features_compared", 0)
        compared_counts.append(compared)
        diverged = result.get("features_diverged", 0)
        total_divergences += diverged
        if diverged > 0:
            dates_with_any_divergence += 1
        for entry in result.get("feature_deltas", []):
            feature = entry["feature"]
            feature_compared_count[feature] = feature_compared_count.get(feature, 0) + 1
            if entry.get("diverged"):
                feature_divergence_counts.setdefault(feature, []).append(entry["abs_delta"])
        for feature in result.get("features_only_in_logged", []):
            only_in_logged_accumulator[feature] = only_in_logged_accumulator.get(feature, 0) + 1
        # Only count a feature as "present in logged snapshot" if it was in
        # that snapshot at all (common or only_in_logged), so
        # features_never_compared doesn't penalize a feature that simply
        # wasn't logged for a given date (e.g. a warmup-bar snapshot with
        # fewer keys).
        for entry in result.get("feature_deltas", []):
            feature = entry["feature"]
            feature_presence_in_logged[feature] = feature_presence_in_logged.get(feature, 0) + 1
        for feature in result.get("features_only_in_logged", []):
            feature_presence_in_logged[feature] = feature_presence_in_logged.get(feature, 0) + 1

    features_diverged_most_often = [
        {
            "feature": feature,
            "diverged_count": len(deltas),
            "diverged_fraction": len(deltas) / num_dates,
            "max_abs_delta": max(deltas),
            "mean_abs_delta": sum(deltas) / len(deltas),
        }
        for feature, deltas in feature_divergence_counts.items()
    ]
    features_diverged_most_often.sort(key=lambda item: item["diverged_count"], reverse=True)
    features_diverged_most_often = features_diverged_most_often[:20]

    features_never_compared = sorted(
        feature for feature, present in feature_presence_in_logged.items()
        if present == num_dates and feature_compared_count.get(feature, 0) == 0
    )

    return {
        "num_dates": num_dates,
        "num_dates_with_comparison": sum(1 for count in compared_counts if count > 0),
        "num_features_compared_per_date": {
            "min": min(compared_counts) if compared_counts else None,
            "max": max(compared_counts) if compared_counts else None,
            "mean": (sum(compared_counts) / len(compared_counts)) if compared_counts else None,
        },
        "total_divergences": total_divergences,
        "dates_with_any_divergence": dates_with_any_divergence,
        "features_diverged_most_often": features_diverged_most_often,
        "features_never_compared": features_never_compared,
    }
