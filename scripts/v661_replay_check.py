"""Does the generations' ledger earn what the book earns? g0001's weight file through the ledger's own functions, against the offline engine, which tracks Lean at 0.99+. A timing check, on read data.

    python scripts/v661_replay_check.py [--start 2023-07-01] [--end 2026-11-02]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.alpha_proof import to_sessions  # noqa: E402
from evaluation.generation_ledger import held_by_lag, session_return_covered  # noqa: E402
from evaluation.target_weights_engine import load_market_panel, simulate_target_weights  # noqa: E402
from portfolio.financing import load_rate_series  # noqa: E402
from portfolio.premia_signals import known_closes  # noqa: E402
from portfolio.target_weights import FLAT_TICKER, load_weight_file, resolve_target_weights_config  # noqa: E402

PINNED_SHA = "57240be0c0486c8ce56fa238c80450a2d26507540482a23b353d139fbb911690"


def ledger_returns(rows: dict, marks: pd.DataFrame, classes: dict, *, start: str, end: str) -> pd.Series:
    """The session returns the ledger would have written, from the same weights."""
    sessions = [date for date in marks.index if date <= end]
    last: dict[str, float] = {}
    mine: list[dict] = []
    out: dict[str, float] = {}
    for position, session in enumerate(sessions):
        held = held_by_lag(mine, classes, {})
        before = held_by_lag(mine[:-1], classes, {}) if mine else {}
        if session >= start and position > 0:
            traded = {ticker: held.get(ticker, 0.0) - before.get(ticker, 0.0) for ticker in set(held) | set(before)}
            result = session_return_covered(held, marks, sessions[position - 1], session, classes=classes, traded=traded)
            if result["session_return"] is not None:
                out[session] = float(result["session_return"])
        if session in rows:
            last = {ticker: float(weight) for ticker, weight in rows[session].items() if ticker != FLAT_TICKER}
        mine.append({"session": session, "decided": dict(last)})
    return pd.Series(out, dtype=float).sort_index()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2023-07-01")
    parser.add_argument("--end", default="2026-11-02")
    args = parser.parse_args(argv)
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assets = [asset for asset in base["phase1"]["universe"]["assets"] if asset["security_type"] == "crypto" or asset["ticker"] in ("SPY", "AGG")]
    config = {**base, "phase1": {**base["phase1"], "universe": {**base["phase1"]["universe"], "assets": assets}}}
    panel = load_market_panel(ROOT, config)
    rows = load_weight_file(ROOT / "ml" / "target_weights.csv", PINNED_SHA)
    target = resolve_target_weights_config(base["phase_v2"]["target_weights"])
    rf_dates, rf_rates = load_rate_series(ROOT / "data" / "alternative" / "interest-rate" / "usa" / "interest-rate.csv")
    engine = simulate_target_weights(rows, panel, target, start=args.start, end=args.end, sweep_config=base["phase_v2"]["cash_sweep"], rf_dates=rf_dates, rf_rates=rf_rates, carry_fn=lambda ticker, date: 0.0)
    marks = known_closes(panel.dates, panel.tickers, panel.closes, panel.asset_class, panel.sessions)
    classes = {ticker: panel.asset_class.get(ticker, "equity") for ticker in panel.tickers}
    ledger = ledger_returns(rows, marks, classes, start=args.start, end=args.end)
    book = to_sessions(engine["strategy"], sorted(panel.sessions))
    joined = pd.concat([ledger, book], axis=1, join="inner").dropna()
    joined.columns = ["ledger", "engine"]
    # the existing ledger's timing, one bar early, for comparison: this is what the lag fixes
    early = joined["ledger"].shift(-1).dropna()
    report = {
        "start": args.start, "end": args.end, "sessions": len(joined), "correlation": float(joined.corr().iloc[0, 1]), "ledger_annual": float(joined["ledger"].mean() * 252.0), "engine_annual": float(joined["engine"].mean() * 252.0),
        "correlation_one_bar_early": float(pd.concat([early, joined["engine"]], axis=1, join="inner").corr().iloc[0, 1]),
    }
    out = ROOT / "ml" / "evaluation" / "v661" / "replay_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=1))
    return 0 if report["correlation"] >= 0.95 else 1


if __name__ == "__main__":
    raise SystemExit(main())
