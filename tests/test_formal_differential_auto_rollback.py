"""retraining/auto_rollback.py against its Lean 4 model (formal/AetherFormal/AutoRollback.lean)."""

from __future__ import annotations

from aether_quant.formal import load_cases
from retraining.auto_rollback import select_rollback_target

VALUES = {"true": True, "false": False, "string_true": "true", "one": 1}
REASON = {"disabled": "auto_rollback_disabled", "no_trigger": "no_configured_trigger_fired", "blocked": "blocked", "triggered": "triggered_by"}
TRIGGERS = ["kill_switch_tripped", "net_sharpe_decay", "rank_ic_decay"]


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("auto_rollback")["cases"]):
        given, expected = case["input"], case["expected"]
        config = {"require_prior_gate_pass": given["require_gate"]}
        if given["enabled"] != "missing":
            config["enabled"] = VALUES[given["enabled"]]
        signals = {name: VALUES[kind] for name, kind in zip(TRIGGERS, given["triggers"]) if kind != "missing"}
        signals["bars_since_promotion"] = given["bars_since_promotion"]
        signals["bars_since_last_rollback"] = given["bars_since_last_rollback"]
        history = [{"model_version_id": f"v{i}", "metrics": {"validation_gate": {"passed": VALUES[kind]}}} for i, kind in enumerate(given["gates"])]
        out = select_rollback_target({}, history, signals, config)
        target = expected["target"]
        assert out["should_rollback"] is (target is not None), index
        assert out["to_version_id"] == (None if target is None else f"v{target}"), index
        assert out["reason"].startswith(REASON[expected["reason"]]), (index, out["reason"])
