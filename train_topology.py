"""Offline trainer for the learned topology model (Phase V2-17.5).

Separate script from train.py: different data source (Postgres
experience_events, not the OHLCV/phase1 dataset pipeline train.py owns),
and must be independently best-effort/failable without ever blocking or
rejecting the primary probability-model candidate - see
retraining/orchestrator.py::train_topology(), which runs this as its own
subprocess between the main `train` and `validate` stages and treats any
failure here as a warning, not a candidate rejection.

Free to use numpy/scikit-learn, unlike topology/learned_topology.py's pure-
Python runtime inference path: this script never runs inside the Lean
container, only as a retraining-pipeline subprocess or manual CLI call.

Usage:
    python train_topology.py --version-id <uuid> [--postgres-dsn ...] [--config-path config.json]

Writes ml/versions/<version_id>/topology_model.json,
topology_training_metrics.json and topology_feature_schema.json. Exits 0
(not an error) when there isn't enough training data yet - "skipped" must
never look like "failed" to the caller.
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
from sklearn.cluster import KMeans

from performance.postgres_triggers import fetch_recent_events
from topology.learned_topology import FEATURE_KEYS, liquidity_score_from_decision

LOGGER = logging.getLogger("aether_quant.train_topology")
ROOT = Path(__file__).resolve().parent
ML_DIR = ROOT / "ml"
CONFIG_PATH = ROOT / "config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether Quant learned-topology trainer (V2-17.5)")
    parser.add_argument("--version-id", type=str, required=True, help="Candidate model_version_id (UUID)")
    parser.add_argument("--postgres-dsn", type=str, default="", help="Overridden by AETHER_POSTGRES_DSN env")
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    return parser.parse_args()


def load_topology_learning_config(config_path: Path = CONFIG_PATH) -> dict:
    with Path(config_path).open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("topology_learning", {}).get("training", {})


def topology_candidate_output_paths(version_id: str) -> dict[str, Path]:
    """Own local helper mirroring train.py's candidate_output_paths(), kept
    independent (not imported from train.py) so this script stays free of
    train.py's torch/pandas import weight."""
    version_dir = ML_DIR / "versions" / version_id
    return {
        "version_dir": version_dir,
        "topology_model": version_dir / "topology_model.json",
        "topology_training_metrics": version_dir / "topology_training_metrics.json",
        "topology_feature_schema": version_dir / "topology_feature_schema.json",
    }


def derive_realized_outcomes(events: list[dict]) -> list[str | None]:
    """Per-ticker, chronological: track the latest action=="trade" event as
    "open"; when a later event for the same ticker carries a non-null
    portfolio.last_realized_pnl, every event in that open->realize span
    (inclusive) is back-labeled win/loss/neutral. Events with no subsequent
    realization keep outcome_label=None and are excluded from win-rate
    weighting downstream (still usable, unlabeled, for centroid geometry).

    Reuses the same "realized pnl closes the previous trade" signal
    experience/observation_metrics.py's simulated_win_loss() already relies
    on, just attributed per-ticker instead of portfolio-wide.

    `events` is assumed already sorted chronologically ascending (the shape
    performance.postgres_triggers.fetch_recent_events() returns). Returns a
    list aligned index-for-index with `events`.
    """
    outcomes: list[str | None] = [None] * len(events)
    open_index_by_ticker: dict[str, int] = {}

    for index, event in enumerate(events):
        ticker = event.get("ticker")
        if not ticker:
            continue

        if event.get("action") == "trade" and event.get("signal") in ("buy", "sell"):
            open_index_by_ticker[ticker] = index

        pnl = (event.get("portfolio") or {}).get("last_realized_pnl")
        if pnl is None:
            continue

        label = "win" if pnl > 0 else "loss" if pnl < 0 else "neutral"
        open_index = open_index_by_ticker.pop(ticker, None)
        if open_index is None:
            outcomes[index] = label
            continue
        # Only back-label this ticker's own events within the span - other
        # tickers' events are interleaved chronologically in between and
        # must not be touched.
        for span_index in range(open_index, index + 1):
            if events[span_index].get("ticker") == ticker:
                outcomes[span_index] = label

    return outcomes


def build_feature_vector(event: dict) -> dict | None:
    """Pulls a topology.learned_topology.FEATURE_KEYS-shaped feature vector
    out of one experience_events payload. Returns None if the event has no
    topology payload (e.g. warmup bars).

    "momentum" isn't itself a field topology/market_topology.py persists on
    a node - probability_up-0.5 is used as a directional-strength proxy
    that's actually present on every event, rather than inventing a new
    field the runtime side would also have to compute and pass through.
    """
    topology = event.get("topology")
    if not isinstance(topology, dict) or "volatility_pressure" not in topology:
        return None

    regime = event.get("regime") or {}
    liquidity = event.get("liquidity") or {}

    return {
        "volatility": float(topology.get("volatility_pressure", 0.0) or 0.0),
        "momentum": float(event.get("probability_up", 0.5) or 0.5) - 0.5,
        "correlation_strength": float(topology.get("correlation_strength", 0.0) or 0.0),
        "liquidity_score": liquidity_score_from_decision(liquidity),
        "regime_risk_score": float(regime.get("risk_score", 0.0) or 0.0),
    }


def fit_prototypes(
    feature_vectors: list[dict],
    outcome_labels: list,
    regime_labels: list[str],
    num_prototypes: int,
    distance_scale_percentile: float,
) -> dict:
    """KMeans over z-scored features. Returns prototypes (with a small,
    win-rate-signed offset later bounded by topology.learned_topology's
    max_offset_xy/z at inference time - never a full replacement embedding),
    per-feature normalization stats, and a distance_scale (p`distance_scale_percentile`
    of within-cluster nearest-centroid distances) used as the novelty/stress
    reference scale.

    The offset's x/y components are absolute scene units; z is normalized
    to [-1, 1] and scaled by max_offset_z at apply time - see the offset
    construction below for why z's contract differs from x/y's."""
    matrix = np.array([[vector[key] for key in FEATURE_KEYS] for vector in feature_vectors], dtype=float)
    means = matrix.mean(axis=0)
    stds = matrix.std(axis=0)
    stds[stds == 0] = 1.0
    normalized = (matrix - means) / stds

    n_clusters = max(1, min(int(num_prototypes), len(feature_vectors)))
    kmeans = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    labels = kmeans.fit_predict(normalized)

    distances_to_own_centroid = np.linalg.norm(normalized - kmeans.cluster_centers_[labels], axis=1)
    distance_scale = (
        float(np.percentile(distances_to_own_centroid, distance_scale_percentile))
        if len(distances_to_own_centroid)
        else 1.0
    )
    distance_scale = distance_scale or 1.0

    prototypes = []
    for cluster_index in range(n_clusters):
        member_indices = [i for i, label in enumerate(labels) if label == cluster_index]
        if not member_indices:
            continue

        member_regimes = [regime_labels[i] for i in member_indices if regime_labels[i]]
        dominant_regime_label = Counter(member_regimes).most_common(1)[0][0] if member_regimes else "unknown"

        member_outcomes = [outcome_labels[i] for i in member_indices if outcome_labels[i] is not None]
        total_labeled = len(member_outcomes)
        win_rate = (sum(1 for label in member_outcomes if label == "win") / total_labeled) if total_labeled else None

        # Offset direction is a coarse, bounded nudge signed by win rate.
        # x/y are absolute scene units: apply_learned_topology() clamps the
        # applied shift to max_offset_xy regardless, so these raw values
        # only need to encode direction/relative magnitude, not final
        # scale - true in both the 2D and 3D (V4-W3) embedding modes,
        # since x/y's scale never changes between them.
        offset_sign = 0.0 if win_rate is None else (1.0 if win_rate >= 0.5 else -1.0)

        # z is normalized to [-1, 1] instead (development/Problems.md #56):
        # unlike x/y, z's scene scale itself changes between the 2D
        # (volatility encoding, 0..1) and 3D (spatial embedding, 0..100)
        # modes, so a raw offset tuned for one scale is meaningless on the
        # other. apply_learned_topology() multiplies this by the active
        # max_offset_z before clamping, the same way confidence already
        # scales it - see _score_node()'s z line. Graded by win rate
        # (unlike x/y's binary sign) since z was already a graded encoding
        # before V4-W3 and there is no reason to lose that resolution.
        centroid = kmeans.cluster_centers_[cluster_index]
        prototypes.append(
            {
                "label": f"proto_{cluster_index}",
                "centroid": {key: float(value) for key, value in zip(FEATURE_KEYS, centroid)},
                "dominant_regime_label": dominant_regime_label,
                "offset": {
                    "x": offset_sign * 2.0,
                    "y": offset_sign * 1.0,
                    "z": 0.0 if win_rate is None else (win_rate - 0.5) * 2.0,
                },
                "sample_count": len(member_indices),
                "win_rate": win_rate,
            }
        )

    feature_stats = {key: {"mean": float(mean), "std": float(std)} for key, mean, std in zip(FEATURE_KEYS, means, stds)}

    return {
        "prototypes": prototypes,
        "feature_stats": feature_stats,
        "distance_scale": distance_scale,
        "n_clusters": n_clusters,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()

    try:
        training_config = load_topology_learning_config(Path(args.config_path))
        min_training_events = int(training_config.get("min_training_events", 500))
        lookback_days = int(training_config.get("lookback_days", 90))
        num_prototypes = int(training_config.get("num_prototypes", 6))
        distance_scale_percentile = float(training_config.get("distance_scale_percentile", 90))

        import psycopg

        dsn = os.environ.get("AETHER_POSTGRES_DSN", args.postgres_dsn)
        conn = psycopg.connect(dsn, autocommit=False)
        try:
            since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            events = fetch_recent_events(conn, limit=max(min_training_events * 4, 5000), since=since)
        finally:
            conn.close()

        outcomes = derive_realized_outcomes(events)

        feature_vectors: list[dict] = []
        outcome_labels: list = []
        regime_labels: list[str] = []
        for event, outcome in zip(events, outcomes):
            vector = build_feature_vector(event)
            if vector is None:
                continue
            feature_vectors.append(vector)
            outcome_labels.append(outcome)
            regime_labels.append((event.get("regime") or {}).get("primary_regime", "unknown"))

        if len(feature_vectors) < min_training_events:
            LOGGER.info(
                "train_topology: only %d usable events (need %d) - skipping, not writing artifacts.",
                len(feature_vectors),
                min_training_events,
            )
            return 0

        fit_result = fit_prototypes(feature_vectors, outcome_labels, regime_labels, num_prototypes, distance_scale_percentile)
        trained_at = datetime.now(timezone.utc).isoformat()

        model_payload = {
            "version_id": args.version_id,
            # development/Problems.md #56: format identity for the
            # prototypes[].offset contract, distinct from version_id
            # (a pipeline run identity, not a schema version). 2 = z
            # normalized to [-1, 1] (V4.1); no schema 1 model has ever
            # existed to migrate from, so apply_learned_topology() has no
            # legacy branch - this is purely a detection hook for any
            # future contract change.
            "offset_schema": 2,
            "trained_at": trained_at,
            "prototypes": fit_result["prototypes"],
            "distance_scale": fit_result["distance_scale"],
            "n_clusters": fit_result["n_clusters"],
        }
        feature_schema_payload = {
            "feature_keys": list(FEATURE_KEYS),
            "feature_stats": fit_result["feature_stats"],
        }
        training_metrics_payload = {
            "project": "aether_quant",
            "phase": "V2-17.5",
            "version_id": args.version_id,
            "trained_at": trained_at,
            "training_window_days": lookback_days,
            "sample_count": len(feature_vectors),
            "labeled_sample_count": sum(1 for label in outcome_labels if label is not None),
            "n_clusters": fit_result["n_clusters"],
            "distance_scale": fit_result["distance_scale"],
            "per_cluster": [
                {
                    "label": prototype["label"],
                    "sample_count": prototype["sample_count"],
                    "win_rate": prototype["win_rate"],
                    "dominant_regime_label": prototype["dominant_regime_label"],
                }
                for prototype in fit_result["prototypes"]
            ],
        }

        paths = topology_candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        paths["topology_model"].write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        paths["topology_feature_schema"].write_text(json.dumps(feature_schema_payload, indent=2), encoding="utf-8")
        paths["topology_training_metrics"].write_text(json.dumps(training_metrics_payload, indent=2), encoding="utf-8")

        LOGGER.info(
            "train_topology: wrote topology artifacts for version %s (%d clusters, %d samples).",
            args.version_id,
            fit_result["n_clusters"],
            len(feature_vectors),
        )
        return 0
    except Exception as exc:  # never let an unexpected failure look ambiguous to the caller
        LOGGER.error("train_topology: unexpected failure - %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
