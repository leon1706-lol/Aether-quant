"""V5.4.1 - auto-rollback hardening: dry-run mode, continuous degradation
score, and integration tests with fakeredis + mock Postgres.

The dry-run mode returns the same decision dict but adds a
`dry_run: True` key so the caller can log what would have happened without
executing. The degradation score is a continuous 0-1 weighted composite of
all trigger severities, giving more signal than the binary flags alone."""

from __future__ import annotations


def compute_degradation_score(degradation_signals: dict, *, weights: dict | None = None) -> float:
    """Continuous 0-1 composite of all trigger severities.

    Default weights: kill_switch_tripped=0.40 (most severe), net_sharpe_decay=0.25,
    rank_ic_decay=0.20, slippage_divergence=0.15. Each signal contributes its
    weight if True, 0 if False/missing. Result is capped at 1.0."""
    w = weights or {
        "kill_switch_tripped": 0.40,
        "net_sharpe_decay": 0.25,
        "rank_ic_decay": 0.20,
        "slippage_divergence": 0.15,
    }
    score = sum(float(wt) for name, wt in w.items() if bool(degradation_signals.get(name, False)))
    return min(round(score, 4), 1.0)


def select_rollback_target_dry_run(
    active_version: dict,
    version_history: list[dict],
    degradation_signals: dict,
    config: dict,
) -> dict:
    """Dry-run wrapper around select_rollback_target(): identical return
    shape plus `dry_run: True` so callers can audit rollback decisions
    without executing them."""
    from retraining.auto_rollback import select_rollback_target

    result = select_rollback_target(active_version, version_history, degradation_signals, config)
    result["dry_run"] = True
    result["degradation_score"] = compute_degradation_score(degradation_signals)
    return result
