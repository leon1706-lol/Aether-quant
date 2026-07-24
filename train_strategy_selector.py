"""Offline trainer for the learned multi-leg strategy-selector model
(V4.7, development/Problems.md #29's own framing - a model that picks
which enabled strategy to prefer per bar, replacing/augmenting
portfolio/options_strategy.py::order_enabled_strategies()'s static
risk-tier-preference reordering, once trained from real per-strategy
realized P&L).

Separate script from train.py, exact same rationale as train_topology.py:
different data source (Postgres experience_events, specifically the new
"option_strategy_outcome" event type - experience/redis_queue.py::
build_option_strategy_outcome_event()), and must be independently
best-effort/failable without ever blocking or rejecting the primary
probability-model candidate - see retraining/orchestrator.py::
train_strategy_selector(), which runs this as its own subprocess between
`train_sequence` and `validate` and treats any failure here as a warning,
not a candidate rejection.

Free to use numpy/scikit-learn, unlike inference/strategy_selector_inference.py's
pure-Python runtime scoring path: this script never runs inside the Lean
container, only as a retraining-pipeline subprocess or manual CLI call.

IMPORTANT - the central scoping fact this trainer exists to make explicit:
unlike train_topology.py (which is dormant only until enough real
Postgres experience_events VOLUME accumulates from an already-running
system), this trainer has NO data source at all until real option
positions actually trade. Confirmed during scoping research: every
options code path in this repo is "code-complete, IB-unverified" (no IB
key, zero option assets in the live universe), so the continuously-running
instance operates in observation mode, where main.py::
_emit_option_strategy_outcome_if_pending() is the ONLY thing that can ever
emit an "option_strategy_outcome" event - and it only fires for a
multi-leg option position that was actually opened AND closed in
observation mode. Until real option assets are configured and this
algorithm actually runs against them, this script's "skip, not enough
data" branch below is not a temporary/volume gate the way train_topology.py's
is - it is the ONLY reachable branch, indefinitely. Ships code-complete
and dormant, exactly as scoped.

Usage:
    python train_strategy_selector.py --version-id <uuid> [--postgres-dsn ...] [--config-path config.json]

Writes ml/versions/<version_id>/strategy_selector_model.json,
strategy_selector_training_metrics.json and
strategy_selector_feature_schema.json. Exits 0 (not an error) when there
isn't enough training data yet - "skipped" must never look like "failed"
to the caller.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from inference.strategy_selector_inference import FEATURE_KEYS
from performance.postgres_triggers import fetch_recent_events

LOGGER = logging.getLogger("aether_quant.train_strategy_selector")
ROOT = Path(__file__).resolve().parent
ML_DIR = ROOT / "ml"
CONFIG_PATH = ROOT / "config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether Quant learned strategy-selector trainer (V4.7)")
    parser.add_argument("--version-id", type=str, required=True, help="Candidate model_version_id (UUID)")
    parser.add_argument("--postgres-dsn", type=str, default="", help="Overridden by AETHER_POSTGRES_DSN env")
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    return parser.parse_args()


def load_strategy_selector_training_config(config_path: Path = CONFIG_PATH) -> dict:
    with Path(config_path).open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("strategy_selector", {}).get("training", {})


def strategy_selector_candidate_output_paths(version_id: str) -> dict[str, Path]:
    """Own local helper mirroring train.py's candidate_output_paths(), kept
    independent (not imported from train.py) so this script stays free of
    train.py's torch/pandas import weight - same rationale
    train_topology.py's own topology_candidate_output_paths() documents."""
    version_dir = ML_DIR / "versions" / version_id
    return {
        "version_dir": version_dir,
        "strategy_selector_model": version_dir / "strategy_selector_model.json",
        "strategy_selector_training_metrics": version_dir / "strategy_selector_training_metrics.json",
        "strategy_selector_feature_schema": version_dir / "strategy_selector_feature_schema.json",
    }


def build_feature_vector(event: dict) -> dict | None:
    """Pulls a FEATURE_KEYS-shaped feature vector out of one
    option_strategy_outcome event's regime/topology sub-payloads - the
    SAME bare key names main.py::_emit_option_strategy_outcome_if_pending()
    writes onto the event at push time (regime={"risk_score": ...},
    topology=self.latest_topology_payload), so this trainer and
    inference/strategy_selector_inference.py's runtime scorer read/produce
    an identical feature vocabulary by construction - train/runtime parity,
    the same discipline train_topology.py's own build_feature_vector()
    establishes for the topology model.

    Returns None only when the event carries NEITHER sub-payload at all (a
    genuinely unusable row, e.g. a malformed/foreign event that slipped
    through the event_type filter) - missing individual keys within a
    present sub-payload degrade to 0.0 instead, never raising."""
    regime = event.get("regime")
    topology = event.get("topology")
    if not isinstance(regime, dict) and not isinstance(topology, dict):
        return None
    regime = regime or {}
    topology = topology or {}
    return {
        "regime_risk_score": float(regime.get("risk_score", 0.0) or 0.0),
        "regime_trend_score": float(regime.get("trend_score", 0.0) or 0.0),
        "topology_correlation_strength": float(topology.get("correlation_strength", 0.0) or 0.0),
    }


def fit_strategy_scorers(
    features_by_strategy: dict[str, list[dict]],
    labels_by_strategy: dict[str, list[int]],
    min_events_per_strategy: int,
) -> tuple[dict, list[dict]]:
    """One independent logistic-regression classifier per strategy_name,
    predicting P(realized_pnl > 0 | features) - kept deliberately simple
    (plain sklearn LogisticRegression, no hyperparameter search): this is
    a brand-new data stream that will realistically stay below
    min_training_events for a long time (see this module's own docstring),
    not worth a more complex model until real training data exists to
    justify one. Trained directly on RAW (not z-scored) feature values, so
    inference/strategy_selector_inference.py::score_strategies()'s runtime
    dot-product needs no separate normalization step/feature_stats file.

    Skips (never raises) a strategy_name with fewer than
    min_events_per_strategy samples, or where every sample shares the same
    outcome label (LogisticRegression needs both classes present to fit).
    Returns ({strategy_name: {"weights": {...}, "bias": b}}, per_strategy_metrics)."""
    scorers: dict[str, dict] = {}
    per_strategy_metrics: list[dict] = []
    for strategy_name, vectors in features_by_strategy.items():
        labels = labels_by_strategy[strategy_name]
        win_rate = sum(labels) / len(labels) if labels else None
        if len(vectors) < min_events_per_strategy or len(set(labels)) < 2:
            per_strategy_metrics.append(
                {"strategy_name": strategy_name, "sample_count": len(vectors), "win_rate": win_rate, "scored": False}
            )
            continue

        matrix = np.array([[vector[key] for key in FEATURE_KEYS] for vector in vectors], dtype=float)
        targets = np.array(labels)
        model = LogisticRegression(max_iter=1000)
        model.fit(matrix, targets)

        scorers[strategy_name] = {
            "weights": {key: float(weight) for key, weight in zip(FEATURE_KEYS, model.coef_[0])},
            "bias": float(model.intercept_[0]),
        }
        per_strategy_metrics.append(
            {"strategy_name": strategy_name, "sample_count": len(vectors), "win_rate": win_rate, "scored": True}
        )
    return scorers, per_strategy_metrics


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()

    try:
        training_config = load_strategy_selector_training_config(Path(args.config_path))
        min_training_events = int(training_config.get("min_training_events", 300))
        lookback_days = int(training_config.get("lookback_days", 90))
        min_events_per_strategy = int(training_config.get("min_events_per_strategy", 20))

        import psycopg

        dsn = os.environ.get("AETHER_POSTGRES_DSN", args.postgres_dsn)
        conn = psycopg.connect(dsn, autocommit=False)
        try:
            since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            events = fetch_recent_events(conn, limit=max(min_training_events * 4, 5000), since=since)
        finally:
            conn.close()

        outcome_events = [event for event in events if event.get("event_type") == "option_strategy_outcome"]

        if len(outcome_events) < min_training_events:
            LOGGER.info(
                "train_strategy_selector: only %d option_strategy_outcome events (need %d) - "
                "skipping, not writing artifacts.",
                len(outcome_events),
                min_training_events,
            )
            return 0

        features_by_strategy: dict[str, list[dict]] = {}
        labels_by_strategy: dict[str, list[int]] = {}
        usable_event_count = 0
        for event in outcome_events:
            strategy_name = event.get("strategy_name")
            realized_pnl = event.get("realized_pnl")
            if not strategy_name or realized_pnl is None:
                continue
            vector = build_feature_vector(event)
            if vector is None:
                continue
            usable_event_count += 1
            features_by_strategy.setdefault(strategy_name, []).append(vector)
            labels_by_strategy.setdefault(strategy_name, []).append(1 if realized_pnl > 0 else 0)

        scorers, per_strategy_metrics = fit_strategy_scorers(
            features_by_strategy, labels_by_strategy, min_events_per_strategy
        )

        if not scorers:
            LOGGER.info(
                "train_strategy_selector: no strategy_name cleared min_events_per_strategy=%d with both "
                "outcome classes present - skipping, not writing artifacts.",
                min_events_per_strategy,
            )
            return 0

        trained_at = datetime.now(timezone.utc).isoformat()
        model_payload = {
            "version_id": args.version_id,
            "trained_at": trained_at,
            "strategy_names": list(scorers.keys()),
            "scorers": scorers,
            "feature_keys": list(FEATURE_KEYS),
        }
        feature_schema_payload = {"feature_keys": list(FEATURE_KEYS)}
        training_metrics_payload = {
            "project": "aether_quant",
            "phase": "V4.7",
            "version_id": args.version_id,
            "trained_at": trained_at,
            "training_window_days": lookback_days,
            "sample_count": usable_event_count,
            "strategies_scored": len(scorers),
            "per_strategy": per_strategy_metrics,
        }

        paths = strategy_selector_candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        paths["strategy_selector_model"].write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        paths["strategy_selector_feature_schema"].write_text(
            json.dumps(feature_schema_payload, indent=2), encoding="utf-8"
        )
        paths["strategy_selector_training_metrics"].write_text(
            json.dumps(training_metrics_payload, indent=2), encoding="utf-8"
        )

        LOGGER.info(
            "train_strategy_selector: wrote strategy_selector artifacts for version %s "
            "(%d strategies scored, %d samples).",
            args.version_id,
            len(scorers),
            usable_event_count,
        )
        return 0
    except Exception as exc:  # never let an unexpected failure look ambiguous to the caller
        LOGGER.error("train_strategy_selector: unexpected failure - %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
