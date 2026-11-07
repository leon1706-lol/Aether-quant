"""The research cycle from the library, on made-up numbers: two generations share a book, the old one's capital glides to the new one, a third trips its guard. No data, no network; runs in seconds.

    python examples/aether_quant_cycle.py
"""

from __future__ import annotations

import numpy as np

from aether_quant.cycle import DecayConfig, GlidePolicy, blend_generation_rows, decay_state, update_generation_shares

POLICY = GlidePolicy(glide_sessions=252, entry_share=0.30, retire_share=0.05)
OLD_ROW = {"BTCUSD": 0.02, "ETHUSD": 0.01}
NEW_ROW = {"AAPL": 0.03, "MSFT": -0.03, "BTCUSD": 0.01}


def main() -> list[dict[str, float]]:
    stages = {"old": "active", "new": "ramping"}
    shares = {"old": 1.0, "new": 0.0}
    path = []
    print(f"{'session':>8} {'old':>6} {'new':>6}   blended book")
    for session in range(280):
        shares = update_generation_shares(shares, stages, {}, {}, POLICY)
        path.append(dict(shares))
        if session % 63 == 0 or session == 279:
            book = blend_generation_rows({"old": OLD_ROW, "new": NEW_ROW}, shares)
            print(f"{session:8d} {shares['old']:6.2f} {shares['new']:6.2f}   " + " ".join(f"{ticker} {weight:+.4f}" for ticker, weight in sorted(book.items())))

    returns = np.random.default_rng(1).normal(-0.0015, 0.01, 800)
    report = decay_state(returns, expected_sharpe=0.5, config=DecayConfig())
    print(f"\na generation that stopped earning, 800 sessions on: {report.state} ({report.reason})")

    tripped = update_generation_shares({"old": 0.2, "new": 0.8}, stages, {"new": "tripped"}, {}, POLICY)
    print(f"a guard trip takes risk off at once, not by the ladder: {tripped}; {1.0 - sum(tripped.values()):.2f} goes to T-bills")
    return path


if __name__ == "__main__":
    main()
