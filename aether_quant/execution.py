"""Execution gates: order permission, slippage, the cost / net-edge model and position reconciliation (formally verified
in formal/AetherFormal/{OrderGate,CostModel,Reconciliation}.lean)."""

from execution.cost_model import (
    NetEdgeDecision,
    build_net_edge_decision,
    estimate_round_trip_cost_bps,
    expected_edge_bps,
    expected_fill_fee_bps,
)
from execution.order_gate import (
    resolve_fill_slippage,
    resolve_order_permission,
    resolve_risk_exit_permission,
    resolve_runtime_mode,
    resolve_slippage_bps,
    slippage_amount,
)
from execution.reconciliation import ReconciliationReport, reconcile_positions
from execution.paper_readiness import evaluate_broker_config, evaluate_live_broker_config, evaluate_live_risk_posture, evaluate_observation_readiness, evaluate_paper_broker_config, evaluate_velocity_decision
from execution.secret_scan import find_populated_secret_fields, is_secret_field, is_tracked_env_secret

__all__ = [
    "NetEdgeDecision",
    "ReconciliationReport",
    "build_net_edge_decision",
    "estimate_round_trip_cost_bps",
    "evaluate_broker_config",
    "evaluate_live_broker_config",
    "evaluate_live_risk_posture",
    "evaluate_observation_readiness",
    "evaluate_paper_broker_config",
    "evaluate_velocity_decision",
    "expected_edge_bps",
    "expected_fill_fee_bps",
    "find_populated_secret_fields",
    "is_secret_field",
    "is_tracked_env_secret",
    "reconcile_positions",
    "resolve_fill_slippage",
    "resolve_order_permission",
    "resolve_risk_exit_permission",
    "resolve_runtime_mode",
    "resolve_slippage_bps",
    "slippage_amount",
]
