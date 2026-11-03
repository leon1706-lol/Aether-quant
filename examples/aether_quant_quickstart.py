"""A tour of the aether_quant library (V6.4.3): every call below is the same pure function the live algorithm or the
research chain uses. Runs in a few seconds on synthetic data:

    python examples/aether_quant_quickstart.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aether_quant import audit, execution, formal, portfolio, research, risk  # noqa: E402


def main() -> int:
    # 1. a market-neutral book: per-name cap, sector cap, dollar neutrality, gross cap
    weights, diagnostics = portfolio.apply_book_neutrality(
        {"AAA": 0.20, "BBB": 0.10, "CCC": -0.15, "DDD": -0.05},
        sector_by_symbol={"AAA": "tech", "BBB": "tech", "CCC": "energy", "DDD": "tech"},
        dollar_neutral=True, sector_neutral=True, gross_exposure_cap=0.5, max_weight_per_name=0.12, sector_max_net_weight=0.15,
        reapply_sector_cap_after_dollar_neutral=True,
    )
    print("book:", {k: round(v, 4) for k, v in weights.items()}, "steps:", diagnostics["steps_applied"])

    # 2. the order gate never trades in observation mode, and a risk lock stops paper/live
    print("observation may trade:", execution.resolve_order_permission("observation", True, True, True)[0])
    print("paper with a tripped lock:", execution.resolve_order_permission("paper", True, True, False))

    # 3. sizing never flips a trade and never exceeds the cap
    decision = risk.build_dynamic_position_sizing(-0.3, 0.9, 0.02, 0.10)
    print("sized target:", round(decision.target_weight, 4))

    # 4. a tamper-evident log, anchored so truncation is caught too
    rows, prev = [], audit.GENESIS_HASH
    for index in range(3):
        row = {"prev_hash": prev, "event_type": "fill", "created_at": f"2026-11-02T10:0{index}:00", "payload": {"n": index}}
        row["hash"] = audit.compute_entry_hash(prev, row["event_type"], row["created_at"], row["payload"])
        rows.append(row)
        prev = row["hash"]
    print("chain ok:", audit.verify_chain(rows), "truncated:", audit.verify_chain(rows[:2], expected_tail_hash=prev))

    # 5. research: IC report, factor spanning and PBO for a synthetic signal
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-01", periods=160, freq="B").strftime("%Y-%m-%d")
    rows = []
    for date in dates:
        future = rng.normal(size=30)
        score = 0.3 * future + rng.normal(size=30)
        ranks = pd.Series(future).rank(pct=True).to_numpy()
        for i in range(30):
            rows.append({"date": date, "ticker": f"T{i}", "split": "validation", "score": score[i], "target_rank_20d": ranks[i],
                         "target_rank_5d": ranks[i], "target_return_1d": future[i] / 100})
    frame = pd.DataFrame(rows)
    report = research.evaluate_signal(frame, score_column="score", splits=("validation",), bootstrap_draws=200)
    h20 = report["splits"]["validation"]["h20"]
    print(f"IC {h20['mean_ic']:.3f}, HAC t {h20['hac_t']:.1f}, CI {[round(x, 3) for x in h20['ci95']]}")
    returns = rng.normal(0, 0.01, size=(400, 8))
    print("PBO of 8 noise variants:", research.probability_of_backtest_overfitting(returns, blocks=8)["pbo"])

    # 6. the Lean 4 differential cases ship with the library
    print("formal targets:", formal.targets())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
