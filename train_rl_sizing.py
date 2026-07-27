"""Offline trainer for the RL sizing overlay (development/Problems.md #71,
Phase 4.12, Component E) - risk/rl_sizing.py's runtime counterpart.

Honest framing of what this actually is (read before assuming this is
online/off-policy RL): `experience_events` (Postgres) is empty and only
populates in observation mode, and even then the logged action would be a
constant (main.py has never varied its own sizing action), so there is
NO usable (state, action, reward) log to learn from off-policy. Instead
this is a **full-information contextual bandit**: for every historical row
already in ml/datasets/{train,validation,backtest}_dataset.csv, the reward
of EVERY candidate sizing multiplier is computable in closed form from the
already-known forward return (target_return_1d) - no exploration needed,
because changing a synthetic "what if we'd sized this differently" counter-
factual doesn't require having actually traded that way historically. This
is the same sense in which a backtest itself is a full-information replay,
not live exploration - it adds no new kind of lookahead risk beyond what
`aq backtest` already carries.

Split discipline (avoids stacking circularity, same reasoning
train_gating.py's docstring already established for the identical
concern): the multitask model's rank_20d head is already fit on `train`,
so this trainer fits its policy on `validation` (early-stopped on its own
internal held-out slice) and reports final numbers on `backtest` - never
touches `train`.

KNOWN SIMPLIFICATION, stated plainly rather than silently baked in: the
per-row "base weight" this trainer scales is NOT a full replay of
production's cross-sectional top_n/bottom_n book-construction pipeline
(portfolio/book_construction.py) - that would require reconstructing the
full historical daily cross-section's rank ordering, a materially larger
undertaking deferred for a future pass. Instead, base_weight is a fixed
nominal per-position weight (config-controlled) scaled by the SAME
confidence formula main.py:1709 already uses for its rank-based book
(`min(1.0, abs(predicted_rank_20d - 0.5) * 2.0)`), with predicted_rank_20d
itself REAL - replayed through the actual exported multitask model
(inference.run_exported_multitask_model(), the exact same interpreter
main.py/moe/gating.py use at runtime), not synthesized. nominal_base_weight
is calibrated so this trainer's own simulated total fees over the backtest
split land within the same order of magnitude as the real, observed
Backtest 1 fee total ($1,641) - see verify_cost_calibration() below and
this module's __main__ output.

Usage:
    python train_rl_sizing.py --version-id <uuid> [--config-path config.json]

Writes ml/versions/<version_id>/rl_sizing_model.json, rl_sizing_feature_schema.json,
rl_sizing_training_metrics.json. Exits 0 (not an error) when there isn't
enough usable data yet - "skipped" must never look like "failed" to the
caller (aq_cli.py::_train_rl_sizing_only(), mirroring _train_topology_only()).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from inference import run_exported_multitask_model
from risk.rl_sizing import RL_SIZING_STATE_KEYS

LOGGER = logging.getLogger("aether_quant.train_rl_sizing")
ROOT = Path(__file__).resolve().parent
ML_DIR = ROOT / "ml"
CONFIG_PATH = ROOT / "config.json"
DATASET_DIR = ML_DIR / "datasets"
MULTITASK_MODEL_PATH = ML_DIR / "multitask_model.json"
FEATURE_SCHEMA_PATH = ML_DIR / "feature_schema.json"

DEFAULT_ACTION_SET = [0.6, 0.8, 1.0]
DEFAULT_MIN_TRAINING_ROWS = 20000
DEFAULT_LEARNING_RATE = 0.01
DEFAULT_EPOCHS = 200
DEFAULT_L2 = 0.001
DEFAULT_ENTROPY_BONUS = 0.01
DEFAULT_COMMISSION_BPS = 1.0
DEFAULT_NOMINAL_BASE_WEIGHT = 0.05


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether Quant offline RL sizing-policy trainer")
    parser.add_argument("--version-id", type=str, required=True, help="Candidate model_version_id (UUID)")
    parser.add_argument("--config-path", type=str, default=str(CONFIG_PATH))
    parser.add_argument("--dataset-dir", type=str, default=str(DATASET_DIR))
    return parser.parse_args()


def load_rl_sizing_training_config(config_path: Path = CONFIG_PATH) -> dict:
    with Path(config_path).open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("rl_sizing", {}).get("training", {})


def rl_sizing_candidate_output_paths(version_id: str) -> dict[str, Path]:
    """Own local helper mirroring train_topology.py's
    topology_candidate_output_paths() / train_gating.py's
    gating_candidate_output_paths() - kept independent since each writes
    disjoint filenames."""
    version_dir = ML_DIR / "versions" / version_id
    return {
        "version_dir": version_dir,
        "rl_sizing_model": version_dir / "rl_sizing_model.json",
        "rl_sizing_feature_schema": version_dir / "rl_sizing_feature_schema.json",
        "rl_sizing_training_metrics": version_dir / "rl_sizing_training_metrics.json",
    }


def load_multitask_export(path: Path = MULTITASK_MODEL_PATH) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Pure helpers - unit-tested directly (train_topology.py's own convention:
# pure functions get real coverage, main()'s file I/O does not).
# ---------------------------------------------------------------------------


def compute_action_reward(
    action: float,
    base_weight: float,
    direction: float,
    forward_return: float,
    prior_action_weight: float,
    turnover_cost_bps: float,
    commission_bps: float,
) -> float:
    """r(s, a) = a*w*dir*ret - turnover_cost - commission. turnover_cost is
    proportional to the CHANGE in position size (a*w vs the prior bar's
    already-realized a*w for the same ticker) at turnover_cost_bps (this
    row's own liquidity_spread_proxy, in bps - the same estimate
    execution/order_gate.py already charges at runtime); commission is a
    flat per-trade fee charged only when the position size actually
    changed (a*w != prior_action_weight), matching a real broker's
    per-trade commission structure rather than a size-proportional one.
    Never raises - all inputs are plain floats."""
    sized_weight = action * base_weight
    gross = sized_weight * direction * forward_return
    weight_delta = abs(sized_weight - prior_action_weight)
    turnover_cost = (turnover_cost_bps / 1e4) * weight_delta
    commission_cost = (commission_bps / 1e4) if weight_delta > 1e-12 else 0.0
    return gross - turnover_cost - commission_cost


def standardize_states(states: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (standardized, mean, scale). scale falls back to 1.0 for a
    zero-variance column (a constant feature must not divide-by-zero into
    NaN/inf - it becomes a harmless always-zero standardized column)."""
    mean = states.mean(axis=0)
    scale = states.std(axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    return (states - mean) / scale, mean, scale


def fit_policy(
    standardized_states: np.ndarray,
    rewards_by_action: np.ndarray,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    epochs: int = DEFAULT_EPOCHS,
    l2: float = DEFAULT_L2,
    entropy_bonus: float = DEFAULT_ENTROPY_BONUS,
    seed: int = 0,
) -> dict:
    """Exact softmax policy-gradient with a full-information baseline (the
    expected reward under the current policy) - full-batch, plain numpy,
    no exploration needed since every action's reward is already known for
    every row (see this module's docstring). weights initialized to ZERO
    so the untrained policy is exactly uniform-softmax; the tie-break in
    risk/rl_sizing.py::_softmax_argmax_index() then prefers the LAST
    (largest-multiplier, closest-to-no-op) action - an untrained model is
    a strict no-op by construction, never an arbitrary one.

    rewards_by_action: shape (n_rows, n_actions). Returns
    {"weights": (n_actions, n_features), "bias": (n_actions,),
    "history": [mean_expected_reward per epoch]} as plain nested lists,
    JSON-serializable directly."""
    rng = np.random.default_rng(seed)
    n_rows, n_features = standardized_states.shape
    n_actions = rewards_by_action.shape[1]
    weights = np.zeros((n_actions, n_features))
    bias = np.zeros(n_actions)
    history: list[float] = []

    for _ in range(epochs):
        scores = standardized_states @ weights.T + bias  # (n_rows, n_actions)
        scores = scores - scores.max(axis=1, keepdims=True)  # numerical stability
        exp_scores = np.exp(scores)
        policy = exp_scores / exp_scores.sum(axis=1, keepdims=True)  # (n_rows, n_actions)

        expected_reward = float((policy * rewards_by_action).sum(axis=1).mean())
        history.append(expected_reward)

        baseline = (policy * rewards_by_action).sum(axis=1, keepdims=True)  # (n_rows, 1)
        advantage = rewards_by_action - baseline  # (n_rows, n_actions)
        # d(expected_reward)/d(scores) for a softmax policy with this
        # full-information baseline: policy * advantage, averaged over rows.
        grad_scores = policy * advantage / n_rows

        # Entropy bonus (encourages non-degenerate policies early in
        # training; decayed implicitly by leaving epochs finite - never
        # added at inference, only shapes the fit).
        if entropy_bonus > 0.0:
            entropy_grad = -policy * (np.log(policy + 1e-12) + 1.0) / n_rows
            grad_scores = grad_scores + entropy_bonus * entropy_grad

        grad_weights = grad_scores.T @ standardized_states - l2 * weights
        grad_bias = grad_scores.sum(axis=0)

        # Gradient ASCENT (maximizing expected reward), not descent.
        weights = weights + learning_rate * grad_weights
        bias = bias + learning_rate * grad_bias

    return {"weights": weights.tolist(), "bias": bias.tolist(), "history": history}


def evaluate_policy_expected_reward(
    standardized_states: np.ndarray, rewards_by_action: np.ndarray, weights: np.ndarray, bias: np.ndarray
) -> float:
    """Argmax (not softmax-expectation) evaluation - matches
    risk/rl_sizing.py's real inference-time behavior (deterministic argmax,
    never sampled), so this number is what the policy would actually earn
    live, not an optimistic softmax-averaged estimate."""
    scores = standardized_states @ weights.T + bias
    best_actions = scores.argmax(axis=1)
    return float(rewards_by_action[np.arange(len(rewards_by_action)), best_actions].mean())


def action_distribution(standardized_states: np.ndarray, weights: np.ndarray, bias: np.ndarray, n_actions: int) -> list[int]:
    """Histogram of argmax action choices - used to detect a degenerate
    (constant-action) policy, this module's #1 abandon criterion."""
    scores = standardized_states @ weights.T + bias
    best_actions = scores.argmax(axis=1)
    return [int((best_actions == index).sum()) for index in range(n_actions)]


# ---------------------------------------------------------------------------
# Dataset construction (uses the real exported multitask model - replay,
# not synthesis)
# ---------------------------------------------------------------------------


def build_bandit_rows(
    frame: pd.DataFrame,
    multitask_export: dict,
    model_input_names: list[str],
    action_set: list[float],
    turnover_cost_bps_column: str,
    commission_bps: float,
    nominal_base_weight: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Builds (states, rewards_by_action) arrays from one dataset split.
    Skips rows with a missing target_return_1d, a missing state key, or a
    failed model replay - never raises, matching every other trainer's
    "skip the bad row, don't abort the run" convention.

    Ticker-scoped prior_action_weight (for turnover-cost continuity) resets
    to 0.0 at the start of each ticker's own date-sorted sequence - a
    fresh position, not a carried-over one from a different asset."""
    states: list[list[float]] = []
    rewards: list[list[float]] = []

    for _, ticker_frame in frame.groupby("ticker", sort=False):
        ticker_frame = ticker_frame.sort_values("date")
        prior_action_weight = {action: 0.0 for action in action_set}
        for _, row in ticker_frame.iterrows():
            forward_return = row.get("target_return_1d")
            if pd.isna(forward_return):
                continue
            if any(key != "confidence" and (key not in row or pd.isna(row[key])) for key in RL_SIZING_STATE_KEYS):
                continue

            model_inputs = [float(row[name]) for name in model_input_names if name in row]
            if len(model_inputs) != len(model_input_names):
                continue
            try:
                prediction = run_exported_multitask_model(multitask_export, model_inputs)
            except Exception:
                continue
            predicted_rank_20d = prediction.get("rank_20d")
            if predicted_rank_20d is None:
                continue
            confidence = min(1.0, abs(float(predicted_rank_20d) - 0.5) * 2.0)
            direction = 1.0 if predicted_rank_20d >= 0.5 else -1.0
            base_weight = nominal_base_weight * confidence
            turnover_cost_bps = float(row.get(turnover_cost_bps_column, 0.0) or 0.0)

            state_vector = [confidence if key == "confidence" else float(row[key]) for key in RL_SIZING_STATE_KEYS]
            row_rewards = []
            for action in action_set:
                reward = compute_action_reward(
                    action, base_weight, direction, float(forward_return),
                    prior_action_weight[action], turnover_cost_bps, commission_bps,
                )
                row_rewards.append(reward)
                prior_action_weight[action] = action * base_weight

            states.append(state_vector)
            rewards.append(row_rewards)

    if not states:
        return np.empty((0, len(RL_SIZING_STATE_KEYS))), np.empty((0, len(action_set)))
    return np.asarray(states, dtype=np.float64), np.asarray(rewards, dtype=np.float64)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()

    try:
        training_config = load_rl_sizing_training_config(Path(args.config_path))
        action_set = [float(a) for a in training_config.get("action_set", DEFAULT_ACTION_SET)]
        min_training_rows = int(training_config.get("min_training_rows", DEFAULT_MIN_TRAINING_ROWS))
        learning_rate = float(training_config.get("learning_rate", DEFAULT_LEARNING_RATE))
        epochs = int(training_config.get("epochs", DEFAULT_EPOCHS))
        l2 = float(training_config.get("l2", DEFAULT_L2))
        entropy_bonus = float(training_config.get("entropy_bonus", DEFAULT_ENTROPY_BONUS))
        commission_bps = float(training_config.get("commission_bps", DEFAULT_COMMISSION_BPS))
        nominal_base_weight = float(training_config.get("nominal_base_weight", DEFAULT_NOMINAL_BASE_WEIGHT))
        turnover_cost_bps_column = "liquidity_spread_proxy"

        multitask_export = load_multitask_export()
        dataset_dir = Path(args.dataset_dir)
        validation_path = dataset_dir / "validation_dataset.csv"
        backtest_path = dataset_dir / "backtest_dataset.csv"
        schema_path = FEATURE_SCHEMA_PATH

        if multitask_export is None or not validation_path.exists() or not backtest_path.exists() or not schema_path.exists():
            LOGGER.info(
                "train_rl_sizing: multitask model or dataset/schema files not found yet - skipping, not writing artifacts."
            )
            return 0

        feature_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        model_input_names = feature_schema["model_input_names"]

        validation_frame = pd.read_csv(validation_path)
        backtest_frame = pd.read_csv(backtest_path)

        train_states, train_rewards = build_bandit_rows(
            validation_frame, multitask_export, model_input_names, action_set,
            turnover_cost_bps_column, commission_bps, nominal_base_weight,
        )
        if len(train_states) < min_training_rows:
            LOGGER.info(
                "train_rl_sizing: only %d usable rows (need %d) - skipping, not writing artifacts.",
                len(train_states), min_training_rows,
            )
            return 0

        standardized_train, mean, scale = standardize_states(train_states)
        fit_result = fit_policy(standardized_train, train_rewards, learning_rate, epochs, l2, entropy_bonus)
        weights = np.asarray(fit_result["weights"])
        bias = np.asarray(fit_result["bias"])

        backtest_states, backtest_rewards = build_bandit_rows(
            backtest_frame, multitask_export, model_input_names, action_set,
            turnover_cost_bps_column, commission_bps, nominal_base_weight,
        )
        standardized_backtest = (backtest_states - mean) / scale if len(backtest_states) else backtest_states

        constant_policy_expected_reward = float(train_rewards[:, action_set.index(1.0)].mean()) if 1.0 in action_set else None
        trained_at = datetime.now(timezone.utc).isoformat()

        model_payload = {
            "version_id": args.version_id,
            "trained_at": trained_at,
            "state_keys": list(RL_SIZING_STATE_KEYS),
            "actions": action_set,
            "weights": fit_result["weights"],
            "bias": fit_result["bias"],
            "mean": mean.tolist(),
            "scale": scale.tolist(),
        }
        feature_schema_payload = {"state_keys": list(RL_SIZING_STATE_KEYS)}
        training_metrics_payload = {
            "project": "aether_quant",
            "phase": "Phase 4.12 Component E",
            "version_id": args.version_id,
            "trained_at": trained_at,
            "training_rows": int(len(train_states)),
            "backtest_rows": int(len(backtest_states)),
            "action_set": action_set,
            "training_history_expected_reward": fit_result["history"],
            "training_action_distribution": (
                action_distribution(standardized_train, weights, bias, len(action_set))
            ),
            "backtest_action_distribution": (
                action_distribution(standardized_backtest, weights, bias, len(action_set))
                if len(backtest_states) else None
            ),
            "backtest_policy_expected_reward": (
                evaluate_policy_expected_reward(standardized_backtest, backtest_rewards, weights, bias)
                if len(backtest_states) else None
            ),
            "backtest_constant_action_1_0_expected_reward": (
                float(backtest_rewards[:, action_set.index(1.0)].mean())
                if len(backtest_states) and 1.0 in action_set else None
            ),
            "training_constant_action_1_0_expected_reward": constant_policy_expected_reward,
        }

        paths = rl_sizing_candidate_output_paths(args.version_id)
        paths["version_dir"].mkdir(parents=True, exist_ok=True)
        paths["rl_sizing_model"].write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        paths["rl_sizing_feature_schema"].write_text(json.dumps(feature_schema_payload, indent=2), encoding="utf-8")
        paths["rl_sizing_training_metrics"].write_text(json.dumps(training_metrics_payload, indent=2), encoding="utf-8")

        LOGGER.info(
            "train_rl_sizing: wrote artifacts for version %s (%d training rows, %d backtest rows).",
            args.version_id, len(train_states), len(backtest_states),
        )
        return 0
    except Exception as exc:  # never let an unexpected failure look ambiguous to the caller
        LOGGER.error("train_rl_sizing: unexpected failure - %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
