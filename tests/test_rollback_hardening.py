"""V5.4.1 - tests for auto-rollback hardening (dry-run mode, degradation
score) and the multitask fallback instrumentation."""

import pytest

from retraining.rollback_hardening import compute_degradation_score, select_rollback_target_dry_run
from retraining.auto_rollback import select_rollback_target


DEGRADATION = {
    "kill_switch_tripped": True,
    "net_sharpe_decay": True,
    "rank_ic_decay": False,
    "slippage_divergence": True,
    "bars_since_promotion": 60,
    "bars_since_last_rollback": None,
}
CONFIG = {"enabled": True, "min_bars_since_promotion": 40, "cooldown_bars": 120}
ACTIVE = {"model_version_id": "v-current", "metrics": {"validation_gate": {"passed": True}}}
HISTORY = [{"model_version_id": "v-prior", "metrics": {"validation_gate": {"passed": True}}}]


class TestDegradationScore:
    def test_all_signals_fired_caps_at_one(self):
        all_on = {k: True for k in ("kill_switch_tripped", "net_sharpe_decay", "rank_ic_decay", "slippage_divergence")}
        assert compute_degradation_score(all_on) == pytest.approx(1.0)

    def test_no_signals_scores_zero(self):
        assert compute_degradation_score({}) == 0.0

    def test_partial_signals_weighted_correctly(self):
        signals = {"kill_switch_tripped": True, "rank_ic_decay": True}
        assert compute_degradation_score(signals) == pytest.approx(0.60)

    def test_custom_weights_override_defaults(self):
        score = compute_degradation_score({"kill_switch_tripped": True}, weights={"kill_switch_tripped": 1.0})
        assert score == 1.0


class TestDryRun:
    def test_dry_run_returns_same_decision_with_extra_keys(self):
        dry = select_rollback_target_dry_run(ACTIVE, HISTORY, DEGRADATION, CONFIG)
        real = select_rollback_target(ACTIVE, HISTORY, DEGRADATION, CONFIG)
        assert dry["should_rollback"] == real["should_rollback"]
        assert dry["to_version_id"] == real["to_version_id"]
        assert dry["dry_run"] is True
        assert "degradation_score" in dry

    def test_dry_run_does_not_fire_when_disabled(self):
        cfg = {**CONFIG, "enabled": False}
        result = select_rollback_target_dry_run(ACTIVE, HISTORY, DEGRADATION, cfg)
        assert result["should_rollback"] is False
        assert result["reason"] == "auto_rollback_disabled"
