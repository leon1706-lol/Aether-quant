"""risk/kill_switch.py against its Lean 4 model (formal/AetherFormal/KillSwitch.lean). The model takes the rolling
Sharpe as an input, so `_rolling_sharpe` is replaced by the case's value."""

from __future__ import annotations

from aether_quant.formal import load_cases, to_float
from risk import kill_switch

METRIC_KEYS = ("drawdown_velocity_pct_per_bar", "live_rank_ic", "consecutive_losses", "slippage_divergence_bps", "model_age_days")
THRESHOLD_KEYS = ("min_rolling_sharpe", "max_drawdown_velocity_pct_per_bar", "min_live_rank_ic", "max_consecutive_losses",
                  "max_slippage_divergence_bps", "max_model_age_days")


def test_python_matches_the_lean_model(monkeypatch):
    for index, case in enumerate(load_cases("kill_switch")["cases"]):
        given, expected = case["input"], case["expected"]
        sharpe = to_float(given["rolling_sharpe"])
        monkeypatch.setattr(kill_switch, "_rolling_sharpe", lambda *args, _s=sharpe, **kwargs: _s)
        metrics = {
            "recent_bar_returns": [0.0, 0.0] if sharpe is not None else [],
            "rolling_sharpe_below_run_last_bar": given["rolling_sharpe_below_run_last_bar"],
            "rolling_sharpe_tripped_last_bar": given["rolling_sharpe_tripped_last_bar"],
            "reconciliation_breach": given["reconciliation_breach"],
        }
        metrics.update({key: to_float(given[key]) for key in METRIC_KEYS})
        config = {"enabled": given["enabled"], "evaluation_bars": 2, "min_bars_for_sharpe": 1,
                  "trip_confirm_bars": given["trip_confirm_bars"], "release_rolling_sharpe": to_float(given["release_rolling_sharpe"])}
        config.update({key: to_float(given[key]) for key in THRESHOLD_KEYS})
        decision = kill_switch.evaluate_kill_switch(metrics, config)
        assert decision.triggers == expected["triggers"], index
        assert decision.tripped == expected["tripped"], index
        assert (decision.severity == "critical") == expected["critical"], index
