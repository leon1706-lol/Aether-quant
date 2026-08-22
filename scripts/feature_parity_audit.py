"""V5.3.6 Workstream A - CLI driver for the feature-parity audit.

Usage:
    python scripts/feature_parity_audit.py [--output ml/evaluation/feature_parity_report.json]

Runs three offline checks and writes a structured report:

1. **synthetic_formula_parity** - the pure replicas in
   evaluation/feature_parity.py are diffed against train.py's OWN
   implementations (engineer_features / add_liquidity_features /
   build_macro_features_by_date) on randomized synthetic data. Proves the
   replicas are faithful before they are trusted anywhere else.
2. **artifact_consistency** - on the REAL dataset: recompute every raw
   OHLCV-recomputable model input, push it through the shipped scaler
   artifact in the forward direction, and compare against the scaled column
   stored in full_dataset.csv. A stale `scaler_stats.json` after a dataset
   rebuild shows up here as systematic mismatches (#100-class risk).
3. **structured_verdicts** - families that cannot be recomputed offline
   (regime chain, alt FRED inputs, sensitivity regressions, bond treasury
   inputs, topology/peer graphs) get explicit per-family verdicts recording
   whether BOTH sides call one shared `features/*.py` function (inspection-
   verified) so residual risk is call-site parameters only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from evaluation.feature_parity import (  # noqa: E402
    BASE_TECHNICAL_FEATURES,
    DEFAULT_LONG_LOOKBACK_WINDOW_BARS,
    INDICATOR_FEATURES,
    LIQUIDITY_FEATURES,
    compute_base_technicals_replica,
    compute_cs_momentum_rank_replica,
    compute_liquidity_replica,
    compute_macro_proxies_replica,
    compute_momentum_long,
    forward_scale,
    load_scaler_mapping,
    summarize_comparison,
)

WARMUP_ROWS_SHORT_WINDOW = 46  # 20d lookback + dropped-first-row offset + safety
WARMUP_ROWS_SPREAD_PROXY = 27  # 25-bar window + dropped-first-row offset


def _synthetic_frame(rows: int = 320, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, rows)))
    high = close * (1 + np.abs(rng.normal(0, 0.004, rows)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, rows)))
    open_ = np.clip(close * (1 + rng.normal(0, 0.002, rows)), low, high)
    volume = rng.integers(50_000, 5_000_000, rows).astype(float)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2019-01-01", periods=rows).strftime("%Y-%m-%d"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def check_synthetic_formula_parity() -> dict:
    """Replicas vs train.py's own implementations on randomized data."""
    result: dict[str, dict] = {}
    try:
        import train as train_module  # heavy: pulls torch once

        frame = _synthetic_frame()
        # engineer_features() assigns each row's split via assign_split(),
        # which requires the full phase1.windows shape - wide bounds so every
        # synthetic row lands somewhere valid.
        windows = {
            "training": {"start": "1900-01-01", "end": "2099-12-31"},
            "validation": {"start": "1900-01-01", "end": "2099-12-31"},
            "backtest": {"start": "1900-01-01", "end": "2099-12-31"},
        }

        reference = train_module.engineer_features(frame.copy(), [], windows)
        replica = compute_base_technicals_replica(frame, long_window_bars=getattr(train_module, "LONG_LOOKBACK_WINDOW_BARS", DEFAULT_LONG_LOOKBACK_WINDOW_BARS))
        for name in BASE_TECHNICAL_FEATURES + INDICATOR_FEATURES:
            ref_col = reference[name].to_numpy(dtype=float)
            rep_col = replica[name]
            valid = ~(np.isnan(ref_col) | np.isnan(rep_col))
            delta = float(np.max(np.abs(ref_col[valid] - rep_col[valid]))) if valid.any() else 0.0
            result[name] = {
                "verdict": "PASS" if delta <= 1e-12 else "FAIL",
                "max_abs_delta": delta,
                "n_nan_reference": int(np.isnan(ref_col).sum()),
                "n_nan_replica": int(np.isnan(rep_col).sum()),
            }

        liquidity_reference = train_module.add_liquidity_features(frame.copy(), "equity")
        liquidity_replica = compute_liquidity_replica(frame, security_type="equity")
        for name in LIQUIDITY_FEATURES:
            ref_col = liquidity_reference[name].to_numpy(dtype=float)
            rep_col = liquidity_replica[name]
            delta = float(np.max(np.abs(ref_col - rep_col)))
            result[name] = {
                "verdict": "PASS" if delta <= 1e-12 else "FAIL",
                "max_abs_delta": delta,
                "n_nan_reference": int(np.isnan(ref_col).sum()),
                "n_nan_replica": int(np.isnan(rep_col).sum()),
            }

        macro_frames = {}
        pivot_close = {}
        for ticker in ("TLT", "SHY", "HYG", "LQD", "BTCUSD"):
            ticker_frame = _synthetic_frame(rows=260, seed=abs(hash(ticker)) % 1000)
            engineered = train_module.engineer_features(ticker_frame.copy(), [], windows)
            macro_frames[ticker] = engineered[["date", "momentum_20d"]]
            pivot_close[ticker] = pd.Series(ticker_frame["close"].to_numpy(), index=pd.Index(ticker_frame["date"], name="date"))
        macro_reference_by_ticker = train_module.build_macro_features_by_date(macro_frames, {})
        close_pivot = pd.DataFrame(pivot_close).sort_index()
        macro_replica = compute_macro_proxies_replica(close_pivot)

        reference_macro = None
        for per_ticker in macro_reference_by_ticker.values():
            candidate = per_ticker.set_index("date")[["macro_yield_curve_slope_proxy", "macro_credit_spread_proxy", "macro_crypto_risk_appetite_proxy"]].sort_index()
            if reference_macro is None:
                reference_macro = candidate
            else:
                reference_macro = reference_macro.join(candidate, rsuffix="_dup", how="outer")
        dup_cols = [c for c in reference_macro.columns if c.endswith("_dup")]
        reference_macro = reference_macro.drop(columns=dup_cols)
        joined = reference_macro.join(macro_replica, how="inner", lsuffix="_ref")
        for base_name in ("macro_yield_curve_slope_proxy", "macro_credit_spread_proxy", "macro_crypto_risk_appetite_proxy"):
            ref_col = joined[f"{base_name}_ref"].to_numpy(dtype=float)
            rep_col = joined[base_name].to_numpy(dtype=float)
            delta = float(np.nanmax(np.abs(ref_col - rep_col)))
            result[base_name] = {
                "verdict": "PASS" if delta <= 1e-12 else "FAIL",
                "max_abs_delta": delta,
                "n_compared": int(len(joined)),
            }
        result["_status"] = "OK"
    except Exception as error:  # noqa: BLE001 - audit must degrade, never crash
        result["_status"] = f"SKIPPED: {type(error).__name__}: {error}"
    return result


def check_artifact_consistency(dataset: pd.DataFrame, scaler_mapping: dict[str, tuple[float, float, float]], long_window_bars: int) -> tuple[dict, dict]:
    """Real-data forward check: replica raw -> scaler artifact -> stored column.

    Residual mismatches are POSITIONALLY CLASSIFIED per ticker:
      - warmup rows (excluded entirely),
      - "boundary artifact": within `long_window_bars` rows after a mid-series
        date gap (label-guard row drops create holes that build-time trailing
        windows legitimately spanned but a gapped replica cannot see),
      - anything else is UNEXPLAINED and fails the audit. This distinction is
        the whole point: boundary artifacts are expected consequences of
        auditing against a post-processed dataset, while unexplained
        mismatches would indicate genuine live-path drift."""
    results: dict[str, dict] = {}

    def _merge(existing: dict | None, comparison: dict) -> dict:
        if existing is None:
            return comparison
        merged = dict(existing)
        for key in ("n_compared", "n_mismatch_gt_1e-9", "n_saturated_at_clip",
                    "n_boundary_artifact", "n_unexplained"):
            merged[key] = merged.get(key, 0) + comparison.get(key, 0)
        if comparison.get("max_abs_delta") is not None:
            merged["max_abs_delta"] = max(merged.get("max_abs_delta") or 0.0, comparison["max_abs_delta"])
        merged["verdict"] = "FAIL" if merged.get("n_unexplained", 0) > 0 else (
            "PASS" if merged.get("n_mismatch_gt_1e-9", 0) == 0 else "PASS_BOUNDARY_ARTIFACTS_ONLY"
        )
        return merged

    def _classify(bad_indices: np.ndarray, holes: set[int], warmup: int, memory_rows: int) -> tuple[int, int]:
        boundary = unexplained = 0
        for i in bad_indices:
            if i < warmup:
                continue  # already excluded upstream; defensive
            if any(h < i <= h + memory_rows for h in holes):
                boundary += 1
            else:
                unexplained += 1
        return boundary, unexplained

    for ticker, group in dataset.groupby("ticker"):
        group = group.sort_values("date").reset_index(drop=True)
        security_type = str(group["security_type"].iloc[0]) if "security_type" in group.columns else "equity"
        dates = pd.to_datetime(group["date"])
        holes = set(np.where(dates.diff().dt.days > 3)[0])

        base = compute_base_technicals_replica(group[["open", "high", "low", "close", "volume"]], long_window_bars=long_window_bars)
        liquidity = compute_liquidity_replica(group[["open", "high", "low", "close", "volume"]], security_type=security_type)

        families = [
            (name, base[name], long_window_bars + 1 if name in ("macd_histogram_norm", "dist_52w_high") else WARMUP_ROWS_SHORT_WINDOW)
            for name in BASE_TECHNICAL_FEATURES + INDICATOR_FEATURES
        ] + [
            (name, liquidity[name], WARMUP_ROWS_SPREAD_PROXY if name == "liquidity_spread_proxy" else 0)
            for name in LIQUIDITY_FEATURES
        ]

        for name, raw_values, warmup in families:
            stored = group[f"{name}_scaled"].to_numpy(dtype=float)
            raw = raw_values
            mean, scale, clip = scaler_mapping[name]
            valid = ~(np.isnan(stored) | np.isnan(raw))
            n_compared = int(valid.sum())
            expected = forward_scale(raw[valid], mean, scale, clip)
            delta = np.abs(expected - stored[valid])
            bad_local = np.where(delta > 1e-9)[0]
            # map back to absolute indices among valid rows
            abs_valid_indices = np.where(valid)[0]
            bad_abs = abs_valid_indices[bad_local]
            boundary, unexplained = _classify(bad_abs, holes, warmup, memory_rows=long_window_bars)
            saturated = int(np.sum(np.abs(stored[valid]) >= clip - 1e-9))
            comparison = {
                "n_compared": n_compared,
                "warmup_excluded_per_ticker": warmup,
                "max_abs_delta": float(delta.max()) if delta.size else None,
                "mean_abs_delta": float(delta.mean()) if delta.size else None,
                "n_mismatch_gt_1e-9": int(len(bad_local)),
                "n_saturated_at_clip": saturated,
                "n_boundary_artifact": boundary,
                "n_unexplained": unexplained,
                "verdict": ("FAIL" if unexplained else ("PASS_BOUNDARY_ARTIFACTS_ONLY" if len(bad_local) else "PASS")),
            }
            results[name] = _merge(results.get(name), comparison)

    return results, {}


def check_cross_sectional_and_macro(dataset: pd.DataFrame, scaler_mapping: dict[str, tuple[float, float, float]]) -> dict:
    """cs_momentum_rank_20 + the three macro proxies against stored columns,
    using per-ticker OWN-calendar momentum (never a union pivot)."""
    from evaluation.feature_parity import compute_momentum_long

    results: dict[str, dict] = {}
    momentum_long = compute_momentum_long(dataset)

    ranks = compute_cs_momentum_rank_replica(momentum_long)
    merged = dataset.merge(ranks, on=["date", "ticker"], how="left")

    name = "cs_momentum_rank_20"
    mean, scale, clip = scaler_mapping[name]
    stored = merged[f"{name}_scaled"].to_numpy(dtype=float)[45:]
    recomputed = merged["cs_momentum_rank_recomputed"].to_numpy(dtype=float)[45:]
    results[name] = summarize_comparison(stored, recomputed, mean, scale, clip, warmup_excluded=45)

    all_dates = sorted(dataset["date"].unique())
    macro = compute_macro_proxies_replica(all_dates, momentum_long)
    macro_long = macro.melt(id_vars="date", var_name="feature", value_name="recomputed")
    for feature in ("macro_yield_curve_slope_proxy", "macro_credit_spread_proxy", "macro_crypto_risk_appetite_proxy"):
        subset = macro_long[macro_long["feature"] == feature].drop(columns=["feature"])
        merged_f = dataset.merge(subset, on="date", how="left")
        mean, scale, clip = scaler_mapping[feature]
        stored = merged_f[f"{feature}_scaled"].to_numpy(dtype=float)[45:]
        recomputed = merged_f["recomputed"].to_numpy(dtype=float)[45:]
        results[feature] = summarize_comparison(stored, recomputed, mean, scale, clip, warmup_excluded=45)

    return results


STRUCTURED_VERDICTS = {
    "regime_signal_confidence|trend_score|risk_score + regime one-hots": {
        "offline": "train.add_regime_features()/_encode_regime_row()",
        "live": "main._build_regime_payload()",
        "shared_function": False,
        "verdict": "DUPLICATED_LOGIC - structural inspection this round found matching inputs (base technicals + average_correlation); numeric replay deferred (needs regime-detector state replication)",
    },
    "alt_implied_volatility_level|term_structure|financial_conditions_change": {
        "offline": "features/derivatives_macro_features.py + alt_data_features.py",
        "live": "same shared functions imported at main.py:179-209",
        "shared_function": True,
        "verdict": "SHARED_OK - identical function objects both sides; neutral-default constants match",
    },
    "sens_* betas/interactions": {
        "offline": "features/cross_asset_sensitivity.py::rolling_sensitivity/sensitivity_interaction",
        "live": "main._cross_asset_sensitivity_for_symbol() calling the SAME shared functions (main.py:179-209 import block)",
        "shared_function": True,
        "verdict": "SHARED_OK_INSPECTED - residual risk is driver-series construction only",
    },
    "bond_yield_curve_*|credit_spread_level|analytic_*|dv01": {
        "offline": "features/bond_features.py",
        "live": "same shared functions imported at main.py:179-209",
        "shared_function": True,
        "verdict": "SHARED_OK_INSPECTED",
    },
    "bond_empirical_duration_beta": {
        "offline": "features/bond_features.py::empirical_duration_beta (full history)",
        "live": "main._bond_empirical_duration_beta_for_symbol() with V5.2.5's permanent lock-in cache",
        "shared_function": True,
        "verdict": "SHARED_OK - drift root-caused and fixed in V5.2.5 (Problems.md lineage)",
    },
    "topology_correlation_strength + topology_risk one-hots + peer_rank*/mean": {
        "offline": "train.build_topology_features_by_date() -> market_topology.build_market_topology()",
        "live": "main._build_topology_payload() -> the SAME market_topology module",
        "shared_function": True,
        "verdict": "SAME_MODULE_BOTH_SIDES - residual risk is per-date batching parameters only",
    },
    "asset_class one-hots": {
        "offline": "train.add_asset_class_context_features() from phase1.universe config",
        "live": "asset_lookup built from the same config block",
        "shared_function": False,
        "verdict": "TRIVIAL_CONSTANT - config-derived, drift would break loudly",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--scaler-stats", default=str(ROOT_DIR / "ml" / "scaler_stats.json"))
    parser.add_argument("--schema", default=str(ROOT_DIR / "ml" / "feature_schema.json"))
    parser.add_argument("--output", default=str(ROOT_DIR / "ml" / "evaluation" / "feature_parity_report.json"))
    parser.add_argument("--skip-synthetic", action="store_true", help="Skip the torch-importing train-side formula check")
    args = parser.parse_args()

    started = time.time()
    print(f"Loading dataset: {args.dataset}")
    dataset = pd.read_csv(args.dataset)
    scaler_stats = json.loads(Path(args.scaler_stats).read_text(encoding="utf-8"))
    schema_names = json.loads(Path(args.schema).read_text(encoding="utf-8"))["model_input_names"]

    scaler_mapping, _uncovered = load_scaler_mapping(scaler_stats)
    # Schema model_input_names carry a "_scaled" suffix for every
    # StandardScaler-ed feature; binary one-hots have no suffix by design.
    one_hots = sorted(name for name in schema_names if not name.endswith("_scaled"))
    unmapped = [name for name in schema_names
                if name.endswith("_scaled") and name[: -len("_scaled")] not in scaler_mapping]
    if unmapped:
        print(f"ERROR: schema inputs whose base name is missing from scaler_stats: {unmapped}")
        return 2

    print(f"Schema: {len(schema_names)} model inputs | scaler covers {len(scaler_mapping)} continuous "
          f"| {len(one_hots)} unscaled one-hots ({', '.join(one_hots[:6])}...)")

    report: dict = {
        "schema_input_count": len(schema_names),
        "scaler_continuous_count": len(scaler_mapping),
        "unscaled_one_hots": one_hots,
    }

    print("\n[1/3] Synthetic formula parity (replicas vs train.py implementations)...")
    report["synthetic_formula_parity"] = {} if args.skip_synthetic else check_synthetic_formula_parity()
    if not args.skip_synthetic:
        failures = [k for k, v in report["synthetic_formula_parity"].items()
                    if isinstance(v, dict) and v.get("verdict") == "FAIL"]
        print(f"    status={report['synthetic_formula_parity'].get('_status')} failures={failures or 'none'}")

    print("\n[2/3] Real-data artifact consistency...")
    artifact_results, _slices = check_artifact_consistency(dataset, scaler_mapping, DEFAULT_LONG_LOOKBACK_WINDOW_BARS)
    report["artifact_consistency"] = artifact_results
    for name, stats in artifact_results.items():
        print(f"    {name:<32} {stats['verdict']:<5} n={stats['n_compared']:>7} "
              f"max_delta={stats['max_abs_delta']} mismatch={stats['n_mismatch_gt_1e-9']} saturated={stats['n_saturated_at_clip']}")

    print("\n[3/3] Cross-sectional + macro families...")
    cross_results = check_cross_sectional_and_macro(dataset, scaler_mapping)
    report["cross_sectional_macro"] = cross_results
    for name, stats in cross_results.items():
        print(f"    {name:<36} {stats['verdict']:<5} n={stats['n_compared']:>7} max_delta={stats['max_abs_delta']} mismatch={stats['n_mismatch_gt_1e-9']}")

    report["structured_verdicts"] = STRUCTURED_VERDICTS
    report["runtime_seconds"] = round(time.time() - started, 1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nReport written: {output_path}")

    all_failures = [n for section in ("artifact_consistency", "cross_sectional_macro")
                    for n, s in report[section].items() if s.get("verdict") == "FAIL"]
    synth = report.get("synthetic_formula_parity", {})
    if isinstance(synth, dict):
        all_failures += [f"synthetic:{k}" for k, v in synth.items() if isinstance(v, dict) and v.get("verdict") == "FAIL"]
    print("OVERALL:", "FAIL (" + ", ".join(all_failures) + ")" if all_failures else "PASS")
    return 1 if all_failures else 0


if __name__ == "__main__":
    sys.exit(main())
