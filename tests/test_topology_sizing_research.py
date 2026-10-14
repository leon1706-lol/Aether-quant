"""scripts/topology_sizing_research.py: the R-TOPO decision (keep the learned topology ON unless OFF passes R-GATE)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from topology_sizing_research import PEER_DISTANCE, decide  # noqa: E402


def _summary(backtest: float, validation: float, drawdown: float = -0.05) -> dict:
    return {"backtest": {"net_sharpe": backtest, "net_max_drawdown": drawdown},
            "validation": {"net_sharpe": validation, "net_max_drawdown": drawdown}}


def test_topology_stays_on_unless_off_clears_the_r_gate_margins():
    on = _summary(1.0, 0.5)
    assert decide({"on_mid": on, "off": _summary(1.05, 0.5)})["branch"] == "keep_on"  # +0.05 < the +0.10 margin
    assert decide({"on_mid": on, "off": _summary(1.2, 0.2)})["branch"] == "keep_on"  # validation worse by 0.3
    assert decide({"on_mid": on, "off": _summary(1.2, 0.49, drawdown=-0.07)})["branch"] == "keep_on"  # drawdown 2 pp worse
    off = decide({"on_mid": on, "off": _summary(1.2, 0.49)})
    assert off["branch"] == "switch_off" and off["topology_learning_enabled"] is False


def test_peer_distance_bracket_spans_best_to_worst():
    assert PEER_DISTANCE == {"on_best": 0.0, "on_mid": 0.5, "on_worst": 1.0}
