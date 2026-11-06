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

__all__ = [
    "NetEdgeDecision",
    "ReconciliationReport",
    "build_net_edge_decision",
    "estimate_round_trip_cost_bps",
    "expected_edge_bps",
    "expected_fill_fee_bps",
    "reconcile_positions",
    "resolve_fill_slippage",
    "resolve_order_permission",
    "resolve_risk_exit_permission",
    "resolve_runtime_mode",
    "resolve_slippage_bps",
    "slippage_amount",
]
