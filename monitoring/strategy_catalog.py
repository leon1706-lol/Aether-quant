"""Static catalog of every registered multi-leg options strategy (Phase 4.8).

Pure, read-only report builder, same "compute on read" precedent
`monitoring/assets_status.py`/`monitoring/neural_network_state.py` already
establish - `portfolio/options_strategy.py::MULTI_LEG_STRATEGY_REGISTRY` is
a static, in-memory Python dict (43 entries, one per registered
`OptionStrategies` factory), so reading it fresh on every request is
trivially cheap - no caching, no config/lean.json reads needed (simpler
than either sibling above, since this data isn't config-driven at all).

Deliberately NOT part of `visualization/state.json`/`main.py::_write_state()`:
that file only exists once a Lean process (backtest/live/observation) has
actually run at least once. The strategy catalog is useful independent of
that - e.g. browsable on a fresh checkout before any backtest has ever
run - so it gets its own endpoint instead, following the same
already-established pattern `/api/assets-status`/`/api/neural-network` use
for data that isn't itself part of the per-bar runtime state.
"""

from __future__ import annotations

from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY


def build_strategy_catalog() -> dict:
    """Returns {"strategies": [{"name", "leg_count", "risk_tier",
    "shape_family", "has_expiry_pair"}, ...], "total_count": int} - sorted
    by name for a stable, deterministic response."""
    strategies = [
        {
            "name": name,
            "leg_count": len(spec.legs),
            "risk_tier": spec.risk_tier,
            "shape_family": spec.shape_family,
            "has_expiry_pair": spec.has_expiry_pair,
        }
        for name, spec in sorted(MULTI_LEG_STRATEGY_REGISTRY.items())
    ]
    return {"strategies": strategies, "total_count": len(strategies)}
