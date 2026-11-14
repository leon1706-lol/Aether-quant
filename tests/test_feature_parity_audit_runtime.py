"""scripts/feature_parity_audit.py's runtime (V6.6.6, #359): the synthetic formula check against train.py, the artifact consistency check with its boundary
classification, the cross-sectional and macro check, and the three modes of `main()`."""

from __future__ import annotations

import json
import sys
import types

import numpy as np
import pandas as pd
import pytest

from evaluation.feature_parity import (
    BASE_TECHNICAL_FEATURES,
    DEFAULT_LONG_LOOKBACK_WINDOW_BARS,
    INDICATOR_FEATURES,
    LIQUIDITY_FEATURES,
    compute_base_technicals_replica,
    compute_liquidity_replica,
    forward_scale,
)
from script_loader import load_script, run_script

FEATURES = BASE_TECHNICAL_FEATURES + INDICATOR_FEATURES + LIQUIDITY_FEATURES
MAPPING = {name: (0.0, 1.0, 5.0) for name in FEATURES}


@pytest.fixture(scope="module")
def audit():
    return load_script("feature_parity_audit")


def _stored(frame, security_type="equity"):
    base = compute_base_technicals_replica(frame, long_window_bars=DEFAULT_LONG_LOOKBACK_WINDOW_BARS)
    liquidity = compute_liquidity_replica(frame, security_type=security_type)
    return {f"{name}_scaled": forward_scale(values, *MAPPING[name]) for name, values in {**base, **liquidity}.items()}


def _dataset(audit, *, hole_at=None, boundary_row=None, far_row=None, warmup_row=None, tickers=("AAA",), security_type="equity"):
    parts = []
    for ticker in tickers:
        frame = audit._synthetic_frame(rows=400, seed=len(ticker) + 3)
        if hole_at is not None:
            frame = frame.drop(index=range(hole_at, hole_at + 6)).reset_index(drop=True)
        stored = _stored(frame, security_type)
        part = frame.assign(ticker=ticker, security_type=security_type, **stored)
        for row, column in ((boundary_row, "rsi_14_scaled"), (far_row, "momentum_20d_scaled"), (warmup_row, "rsi_14_scaled")):
            if row is not None and column in part.columns and ticker == tickers[0]:
                part.loc[row, column] = part.loc[row, column] + 1.0 if np.isfinite(part.loc[row, column]) else 1.0
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def test_the_synthetic_formulas_match_train_py(audit):
    result = audit.check_synthetic_formula_parity()
    assert result["_status"] == "OK" and not [name for name, entry in result.items() if isinstance(entry, dict) and entry.get("verdict") == "FAIL"]


def test_a_failing_train_import_degrades_to_a_skipped_status(audit, monkeypatch):
    broken = types.ModuleType("train")
    broken.engineer_features = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no torch"))
    monkeypatch.setitem(sys.modules, "train", broken)
    assert audit.check_synthetic_formula_parity()["_status"] == "SKIPPED: RuntimeError: no torch"


def test_a_matching_dataset_passes_every_family(audit):
    results, _ = audit.check_artifact_consistency(_dataset(audit, tickers=("AAA", "BBB")), MAPPING, DEFAULT_LONG_LOOKBACK_WINDOW_BARS)
    assert results["momentum_20d"]["verdict"] == "PASS" and all(entry["verdict"] in ("PASS", "PASS_BOUNDARY_ARTIFACTS_ONLY") for entry in results.values())
    assert results["momentum_20d"]["n_compared"] > 0


def test_a_mismatch_after_a_gap_is_a_boundary_artifact_and_one_far_from_it_is_not(audit):
    dataset = _dataset(audit, hole_at=100, boundary_row=110)
    boundary, _ = audit.check_artifact_consistency(dataset, MAPPING, DEFAULT_LONG_LOOKBACK_WINDOW_BARS)
    assert boundary["rsi_14"]["verdict"] == "PASS_BOUNDARY_ARTIFACTS_ONLY" and boundary["rsi_14"]["n_boundary_artifact"] >= 1
    unexplained, _ = audit.check_artifact_consistency(_dataset(audit, far_row=300, tickers=("AAA", "BBB")), MAPPING, DEFAULT_LONG_LOOKBACK_WINDOW_BARS)
    assert unexplained["momentum_20d"]["verdict"] == "FAIL" and unexplained["momentum_20d"]["n_unexplained"] == 1
    warm, _ = audit.check_artifact_consistency(_dataset(audit, warmup_row=3, tickers=("AAA", "BBB")), MAPPING, DEFAULT_LONG_LOOKBACK_WINDOW_BARS)
    assert warm["rsi_14"]["n_mismatch_gt_1e-9"] >= 1


def test_a_forex_pair_is_replicated_on_leans_fill_forward_calendar(audit):
    import train as train_module

    frame = audit._synthetic_frame(rows=300, seed=11)
    dates = pd.to_datetime(frame["date"])
    filled = train_module.fill_forward_forex_frame(frame[["date", "open", "high", "low", "close", "volume"]].assign(date=dates.to_numpy()))
    positions = np.flatnonzero(filled["date"].isin(set(dates)).to_numpy())
    base = compute_base_technicals_replica(filled[["open", "high", "low", "close", "volume"]], long_window_bars=DEFAULT_LONG_LOOKBACK_WINDOW_BARS)
    liquidity = compute_liquidity_replica(filled[["open", "high", "low", "close", "volume"]], security_type="forex")
    stored = {f"{name}_scaled": forward_scale(np.asarray(values)[positions], *MAPPING[name]) for name, values in {**base, **liquidity}.items()}
    dataset = frame.assign(ticker="EURUSD", security_type="forex", **stored)
    results, _ = audit.check_artifact_consistency(dataset, MAPPING, DEFAULT_LONG_LOOKBACK_WINDOW_BARS)
    assert results["momentum_20d"]["n_compared"] > 0 and results["momentum_20d"]["verdict"] in ("PASS", "PASS_BOUNDARY_ARTIFACTS_ONLY")


def _cross_world(monkeypatch, audit, tmp_path):
    import features.cross_asset_timing as timing

    monkeypatch.setattr(audit, "ROOT_DIR", tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(timing, "resolve_forex_lean_holidays", lambda config: frozenset())
    monkeypatch.setattr(audit, "build_momentum_pool", lambda dataset, security_types, holidays: dataset[["date", "ticker", "momentum_20d"]].assign(date=pd.to_datetime(dataset["date"])))
    monkeypatch.setattr(audit, "compute_cs_momentum_rank_replica", lambda pool, security_types: pool[["date", "ticker"]].assign(cs_momentum_rank_recomputed=0.5))
    monkeypatch.setattr(audit, "compute_macro_proxies_replica", lambda pool, security_types: pool[["date", "ticker"]].assign(**{name: 0.1 for name in ("macro_yield_curve_slope_proxy", "macro_credit_spread_proxy", "macro_crypto_risk_appetite_proxy")}))
    seen = []
    monkeypatch.setattr(audit, "summarize_comparison", lambda stored, recomputed, mean, scale, clip, warmup_excluded: seen.append(len(stored)) or {"verdict": "PASS", "n_compared": len(stored), "max_abs_delta": 0.0, "n_mismatch_gt_1e-9": 0})
    return seen


def _cross_dataset(with_types):
    frame = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=60).strftime("%Y-%m-%d"), "ticker": "AAA", "momentum_20d": 0.01})
    for name in ("cs_momentum_rank_20", "macro_yield_curve_slope_proxy", "macro_credit_spread_proxy", "macro_crypto_risk_appetite_proxy"):
        frame[f"{name}_scaled"] = 0.0
    if with_types:
        frame["security_type"] = "equity"
    return frame


@pytest.mark.parametrize("with_types", [True, False])
def test_the_cross_sectional_and_macro_features_are_each_compared_after_the_warmup(audit, monkeypatch, tmp_path, with_types):
    seen = _cross_world(monkeypatch, audit, tmp_path)
    mapping = {name: (0.0, 1.0, 5.0) for name in ("cs_momentum_rank_20", "macro_yield_curve_slope_proxy", "macro_credit_spread_proxy", "macro_crypto_risk_appetite_proxy")}
    results = audit.check_cross_sectional_and_macro(_cross_dataset(with_types), mapping)
    assert set(results) == set(mapping) and seen == [15, 15, 15, 15]


def _files(tmp_path, *, unmapped=False):
    names = ["rsi_14_scaled", "regime_bull"] + (["missing_feature_scaled"] if unmapped else [])
    (tmp_path / "scaler.json").write_text(json.dumps({"feature_names": ["rsi_14"], "mean": [0.0], "scale": [1.0], "clip_sigma": 5.0}), encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps({"model_input_names": names}), encoding="utf-8")
    (tmp_path / "dataset.csv").write_text("date,ticker\n2020-01-01,AAA\n", encoding="utf-8")
    return ["--dataset", str(tmp_path / "dataset.csv"), "--scaler-stats", str(tmp_path / "scaler.json"), "--schema", str(tmp_path / "schema.json"), "--output", str(tmp_path / "out" / "report.json")]


def _checks(monkeypatch, audit, *, synthetic=None, artifact=None, cross=None):
    monkeypatch.setattr(audit, "check_synthetic_formula_parity", lambda: synthetic if synthetic is not None else {"_status": "OK", "rsi_14": {"verdict": "PASS"}})
    monkeypatch.setattr(audit, "check_artifact_consistency", lambda dataset, mapping, bars: (artifact or {"rsi_14": {"verdict": "PASS", "n_compared": 3, "max_abs_delta": 0.0, "n_mismatch_gt_1e-9": 0, "n_saturated_at_clip": 0}}, {}))
    monkeypatch.setattr(audit, "check_cross_sectional_and_macro", lambda dataset, mapping: cross or {"cs": {"verdict": "PASS", "n_compared": 3, "max_abs_delta": 0.0, "n_mismatch_gt_1e-9": 0}})


def test_the_synthetic_only_mode_passes_fails_or_refuses_a_dead_check(audit, monkeypatch, tmp_path, capsys):
    out = str(tmp_path / "synthetic.json")
    _checks(monkeypatch, audit)
    assert run_script("feature_parity_audit", ["--help"], monkeypatch) == 0
    monkeypatch.setattr(sys, "argv", ["audit", "--synthetic-only", "--output", out])
    assert audit.main() == 0 and "OVERALL: PASS" in capsys.readouterr().out
    _checks(monkeypatch, audit, synthetic={"_status": "OK", "rsi_14": {"verdict": "FAIL"}})
    assert audit.main() == 1
    _checks(monkeypatch, audit, synthetic={"_status": "SKIPPED: ImportError: x"})
    assert audit.main() == 1 and "check_did_not_run" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["audit", "--synthetic-only", "--skip-synthetic"])
    with pytest.raises(SystemExit):
        audit.main()


def test_the_full_audit_writes_a_report_and_exits_on_any_failure(audit, monkeypatch, tmp_path, capsys):
    argv = _files(tmp_path)
    _checks(monkeypatch, audit)
    monkeypatch.setattr(sys, "argv", ["audit", *argv])
    assert audit.main() == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["schema_input_count"] == 2 and report["unscaled_one_hots"] == ["regime_bull"] and "structured_verdicts" in report
    _checks(monkeypatch, audit, cross={"cs": {"verdict": "FAIL", "n_compared": 1, "max_abs_delta": 1.0, "n_mismatch_gt_1e-9": 1}}, synthetic={"_status": "OK", "x": {"verdict": "FAIL"}})
    assert audit.main() == 1 and "synthetic:x" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["audit", *argv, "--skip-synthetic"])
    assert audit.main() == 1 and json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))["synthetic_formula_parity"] == {}


def test_a_schema_name_the_scaler_does_not_cover_stops_the_audit(audit, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["audit", *_files(tmp_path, unmapped=True)])
    assert audit.main() == 2 and "missing_feature_scaled" in capsys.readouterr().out
