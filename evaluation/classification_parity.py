"""Lean-vs-offline classification parity (V6.4.0, lead L11, rule R-L11).

A Lean run's book history logs the head probability behind each book call (`member_probabilities`). The same head scored
offline (`evaluation.model_predictions.predict_head`) on the same (date, ticker) rows must agree: this module scores both
on the identical population of calls and compares them to a pre-registered tolerance. Pure: no I/O, numpy only.
"""

from __future__ import annotations

import math

import numpy as np

TOLERANCE = {"accuracy": 0.01, "neg_log_loss": 0.01, "median_abs_probability_gap": 0.005}


def _scores(truth: np.ndarray, probability: np.ndarray) -> dict:
    """Accuracy of the head's own call (p >= 0.5) and the negative log-loss against the 20-bar forward direction."""
    clipped = np.clip(probability, 1e-15, 1.0 - 1e-15)
    return {
        "accuracy": float(((probability >= 0.5).astype(int) == truth).mean()),
        "neg_log_loss": float(np.mean(truth * np.log(clipped) + (1 - truth) * np.log(1.0 - clipped))),
    }


def lean_vs_offline_classification(calls: dict, offline_probability: dict[tuple[str, str], float]) -> dict:
    """`calls` = `evaluation.backtest_statistics.lean_book_calls(...)` (truth, probability, dates, tickers);
    `offline_probability` = {(date, TICKER): the head's probability of "up"} for the same rows (late-bar names lagged as
    live is). Rows lacking either probability are dropped and counted; the verdict needs at least one matched row."""
    truth, lean_p, offline_p = [], [], []
    missing_lean = missing_offline = 0
    for index, label in enumerate(calls.get("truth", [])):
        lean_value = calls["probability"][index]
        offline_value = offline_probability.get((calls["dates"][index], calls["tickers"][index]))
        if lean_value is None:
            missing_lean += 1
            continue
        if offline_value is None or not math.isfinite(offline_value):
            missing_offline += 1
            continue
        truth.append(label)
        lean_p.append(lean_value)
        offline_p.append(float(offline_value))
    result = {
        "n_calls": len(calls.get("truth", [])), "n_matched": len(truth),
        "missing_lean_probability": missing_lean, "missing_offline_probability": missing_offline,
        "tolerance": dict(TOLERANCE),
    }
    if not truth:
        return {**result, "lean": None, "offline": None, "deltas": None, "within_tolerance": None,
                "reason": "no call has both a logged and an offline probability"}
    truth_array = np.asarray(truth, dtype=int)
    lean_array, offline_array = np.asarray(lean_p, dtype=float), np.asarray(offline_p, dtype=float)
    lean, offline = _scores(truth_array, lean_array), _scores(truth_array, offline_array)
    gap = np.abs(lean_array - offline_array)
    deltas = {
        "accuracy": lean["accuracy"] - offline["accuracy"],
        "neg_log_loss": lean["neg_log_loss"] - offline["neg_log_loss"],
        "median_abs_probability_gap": float(np.median(gap)),
        "max_abs_probability_gap": float(gap.max()),
    }
    checks = {
        "accuracy": abs(deltas["accuracy"]) <= TOLERANCE["accuracy"],
        "neg_log_loss": abs(deltas["neg_log_loss"]) <= TOLERANCE["neg_log_loss"],
        "median_abs_probability_gap": deltas["median_abs_probability_gap"] <= TOLERANCE["median_abs_probability_gap"],
    }
    return {**result, "lean": lean, "offline": offline, "deltas": deltas, "checks": checks,
            "within_tolerance": all(checks.values()), "reason": None}


def offline_probability_map(frame, probability_column: str, date_column: str = "date", ticker_column: str = "ticker") -> dict:
    """{(YYYY-MM-DD, TICKER): finite probability} from a scored frame (the harness's lagged frame for late-bar names)."""
    dates = frame[date_column].astype(str).str[:10].tolist()
    tickers = frame[ticker_column].astype(str).str.upper().tolist()
    values = frame[probability_column].tolist()
    return {(day, ticker): float(value) for day, ticker, value in zip(dates, tickers, values) if isinstance(value, (int, float)) and math.isfinite(value)}


def classification_parity_for_run_dir(run_dir, config: dict, root, *, dataset_path=None, ml_dir=None, source: str | None = None) -> dict:
    """`aq evaluate --classification-parity`: a Lean run's logged book-call probabilities against the same head scored
    offline on the same rows. Needs a run whose book history carries `member_probabilities` (V6.4.0 diagnostics) and the
    dataset rows of those dates; late-bar names use the previous row's prediction, as live's stale-bar convention does."""
    import json
    from pathlib import Path

    import pandas as pd

    from evaluation.backtest_statistics import LEAN_PROBABILITY_SOURCE, lean_book_calls
    from evaluation.lean_attribution import closes_for_universe, find_book_history_for_run
    from evaluation.live_parity import LATE_BAR_ASSET_CLASSES, lag_predictions_for_tickers
    from evaluation.model_predictions import predict_head

    root = Path(root)
    source = source or LEAN_PROBABILITY_SOURCE
    model_kind = {"direction_prob_multitask": "multitask", "direction_prob_sequence": "sequence"}.get(source)
    if model_kind is None:
        return {"status": "unsupported_source", "source": source, "within_tolerance": None}
    history_path = find_book_history_for_run(Path(run_dir), root / "visualization" / "book_history")
    if history_path is None:
        return {"status": "no_book_history", "source": source, "within_tolerance": None}
    history = [json.loads(line) for line in Path(history_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    tickers = {str(ticker).upper() for record in history for ticker in (record.get("allocations") or {})}
    closes = closes_for_universe(config, root, tickers)
    sorted_closes = {ticker: sorted(series) for ticker, series in closes.items()}
    calls = lean_book_calls(history, closes, sorted_closes, source=source)
    if not any(value is not None for value in calls["probability"]):
        return {"status": "no_logged_probabilities", "source": source, "n_calls": len(calls["truth"]), "within_tolerance": None,
                "reason": "the run's book history has no member_probabilities (diagnostics.book_history.include_probabilities)"}

    ml_dir = Path(ml_dir) if ml_dir else root / "ml"
    model_filename, schema_filename = {"multitask": ("multitask_model.json", "multitask_feature_schema.json"),
                                       "sequence": ("sequence_model.json", "sequence_feature_schema.json")}[model_kind]
    model_export = json.loads((ml_dir / model_filename).read_text(encoding="utf-8"))
    schema = json.loads((ml_dir / schema_filename).read_text(encoding="utf-8"))
    dataset_path = Path(dataset_path) if dataset_path else ml_dir / "datasets" / "full_dataset.csv"
    first = (pd.Timestamp(min(calls["dates"])) - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    parts = []
    for chunk in pd.read_csv(dataset_path, chunksize=40_000):
        chunk = chunk[chunk["ticker"].astype(str).str.upper().isin(tickers)]
        parts.append(chunk[chunk["date"].astype(str).str[:10] >= first])
    frame = pd.concat(parts, ignore_index=True)
    window = int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30))
    frame["direction_probability"] = predict_head(
        frame, model_export, schema["model_input_names"], "direction_20d", model_kind=model_kind,
        sequence_feature_schema=schema if model_kind == "sequence" else None, configured_window_size=window,
    )
    asset_class = {str(asset["ticker"]).upper(): str(asset.get("security_type", "")) for asset in config["phase1"]["universe"]["assets"]}
    late = {ticker for ticker, kind in asset_class.items() if kind in LATE_BAR_ASSET_CLASSES}
    frame = lag_predictions_for_tickers(frame.assign(ticker=frame["ticker"].astype(str).str.upper()),
                                        prediction_column="direction_probability", tickers=late)
    result = lean_vs_offline_classification(calls, offline_probability_map(frame, "direction_probability"))
    return {"status": "ok", "source": source, "head": "direction_20d", "model": model_kind, "book_history": str(history_path), **result}
