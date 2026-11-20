"""portfolio/book_optimizer.paper_loss_guard against its Lean 4 model (formal/AetherFormal/PaperLossGuard.lean), V6.6.10."""

from __future__ import annotations

from aether_quant.formal import load_cases, to_float
from portfolio.book_optimizer import paper_loss_guard


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("paper_loss_guard")["cases"]):
        given = case["input"]
        held = paper_loss_guard([to_float(x) for x in given["increments"]], lookback=given["lookback"], max_loss=to_float(given["max_loss"]))
        assert held is case["expected"]["held"], index
