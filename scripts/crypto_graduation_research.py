"""Which observation-only crypto names would pay for themselves as book candidates? (V5.7.0, todo.md finding 7)

Only BTCUSD and LTCUSD trade: the other ten crypto names fail `phase9.asset_quality.min_training_rows` (250 TRAIN rows;
ETH starts in 2017-09 with 54) although the pooled model scores them like everything else. Each one is added to the book
pool alone (and all together) in the full as-live simulator, with Coinbase's 56-80 bps per fill, and kept only if it
helps on BOTH splits under the R-GATE margins (backtest Sharpe +0.10, validation not worse by more than 0.02, drawdown not
worse by more than 1 pp). A name that graduates also needs a Lean quote zip (`aq backfill yfinance --quotes`).

    python scripts/crypto_graduation_research.py     -> ml/evaluation/crypto_graduation_research.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from as_live_levers import AsLiveHarness, summarize  # noqa: E402
from gate_research import decide  # noqa: E402


def run_with_extra_candidates(harness: AsLiveHarness, extra: list[str]):
    metadata = {ticker: dict(entry) for ticker, entry in harness.metadata.items()}
    for ticker in extra:
        metadata[ticker] = {**metadata.get(ticker, {}), "trading_eligible": True}
    original_core = harness.core_crypto
    harness.core_crypto = frozenset(original_core) | frozenset(extra)
    harness._mechanisms.clear()
    try:
        return harness.as_live(candidate_metadata_by_ticker=metadata)
    finally:
        harness.core_crypto = original_core
        harness._mechanisms.clear()


def main() -> int:
    harnesses = {split: AsLiveHarness(split) for split in ("backtest", "validation")}
    reference = harnesses["backtest"]
    candidates = sorted(
        ticker
        for ticker, kind in reference.asset_class_by_ticker.items()
        if kind == "crypto" and not reference.metadata[ticker]["trading_eligible"]
    )
    present = {split: set(h.frame["ticker"].unique()) for split, h in harnesses.items()}
    candidates = [ticker for ticker in candidates if all(ticker in tickers for tickers in present.values())]
    print("observation-only crypto candidates with rows on both splits:", candidates)

    experiments = {"baseline": []} | {ticker: [ticker] for ticker in candidates} | {"all candidates": candidates}
    results: dict[str, dict] = {}
    for name, extra in experiments.items():
        results[name] = {split: summarize(run_with_extra_candidates(h, extra)) for split, h in harnesses.items()}
        print(
            f"{name:16s} "
            + " | ".join(
                f"{split[:4]} sharpe {results[name][split]['net_sharpe']:+.3f} ret {100 * results[name][split]['net_total_return']:+.2f}% "
                f"dd {100 * results[name][split]['net_max_drawdown']:.2f}%"
                for split in results[name]
            ),
            flush=True,
        )
    for name, entry in results.items():
        if name != "baseline":
            entry["decision"] = decide(results["baseline"], entry)
    graduates = [name for name, entry in results.items() if entry.get("decision", {}).get("passes_r_gate") and name not in ("all candidates",)]
    print("graduates (R-GATE on both splits):", graduates or "none")
    out = ROOT_DIR / "ml" / "evaluation" / "crypto_graduation_research.json"
    out.write_text(json.dumps({"candidates": candidates, "results": results, "graduates": graduates}, indent=2), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
