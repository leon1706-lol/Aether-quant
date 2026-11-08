"""k09's decision for a session (V6.6.4): quarterly accruals, pooled by sector, from a host that has fundamentals.

k09 (trailing-twelve-month accruals over assets, IC t 2.60 in round 3) is a forward observer at zero capital (`ml/evaluation/v664/observers.json`). The bare runner can't decide it: the signal needs the
EDGAR quarterly download. This builds the weights the same way the research cell does (`features.wide_panel.extended_info_features`, minus the accruals rank, pooled within sector, the wide
weight settings) for one session, from files under `data_wide/` and Yahoo's closes, and writes `ticker,weight`. `--ledger` also appends the dated decision (`scripts/cycle_decide.py`); pushing
`forward/decisions.jsonl` to the `forward-ledger` branch before that session's 22:45 UTC run is the owner's step, and a decision is good for 25 sessions.

    AQ_SEC_CONTACT=... python scripts/build_wide_info.py --parts extended --refresh     # new quarterly filings (the contact is used for this one run and never stored)
    python scripts/k09_decide.py --session 2026-11-06 --out ml/cycle/k09_2026-11-06.csv [--ledger <worktree>/forward/decisions.jsonl --generation g0005]
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from portfolio.premia_signals import POOLED, ResearchPanel, WeightSettings, signal_to_weights  # noqa: E402

SETTINGS = WeightSettings(target_vol=0.07, gross_cap=1.4, name_cap=0.03, class_caps={"crypto": 0.15}, name_cap_by_class={"crypto": 0.05})
HISTORY_SESSIONS = 120


def k09_weights(session: str, known: pd.DataFrame, extended: pd.DataFrame, fundamentals: pd.DataFrame, members: list[str], sectors: dict[str, str]) -> dict[str, float]:
    """The weights k09 holds after `session`'s close. `known` holds closes up to and including the session; a name with no sector, no price or no accruals figure is not ranked."""
    from features.wide_panel import extended_info_features

    columns = [ticker for ticker in members if ticker in known.columns and sectors.get(ticker, "unknown") != "unknown"]
    if not columns:
        return {}
    sessions = list(known.index)  # the table maps a filing to the session after its date, so it needs the calendar, not the one day
    scores = extended_info_features(sessions, columns, extended=extended, fundamentals=fundamentals)["accruals_ttm"] * -1.0
    signal = scores.reindex(index=known.index, columns=known.columns)
    asset_class = {ticker: sectors.get(ticker, "unknown") for ticker in known.columns}
    panel = ResearchPanel(known, asset_class, {}, {})
    rows = signal_to_weights(signal, panel, kind=POOLED, rebalance_every=1, settings=SETTINGS, start=session, end=session)
    return {ticker: float(weight) for ticker, weight in rows.get(session, {}).items() if weight}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", default=None, help="the session whose close the decision follows (default: the last weekday)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--generation", default=None)
    args = parser.parse_args(argv)
    import forward_ledger
    from cycle_decide import write_decision
    from data_pipeline.edgar_facts import read_fundamentals
    from data_pipeline.sp500_membership import load_membership
    from evaluation.research_cells import membership_mask

    session = args.session or forward_ledger.session_for_outage(datetime.datetime.now(datetime.timezone.utc))
    reference = ROOT / "data_wide" / "reference"
    membership = load_membership(reference / "sp500_ticker_start_end.csv")
    sectors = json.loads((reference / "sectors.json").read_text(encoding="utf-8"))
    names = sorted(ticker for ticker in membership if sectors.get(ticker, "unknown") != "unknown")
    mask = membership_mask(membership, [session], names)
    members = [ticker for ticker in names if bool(mask.at[session, ticker])]
    closes: dict[str, dict[str, float]] = {}
    for ticker in members:
        try:
            closes[ticker] = forward_ledger.yahoo_closes(ticker.replace(".", "-"), forward_ledger._get_json)
        except Exception as error:  # a name Yahoo cannot serve is not ranked; the run says how many
            print(f"{ticker}: {type(error).__name__}", file=sys.stderr)
    frame = pd.DataFrame(closes).sort_index()
    known = frame[frame.index <= session].tail(HISTORY_SESSIONS)
    if session not in known.index:
        print(f"no closes for {session} yet", file=sys.stderr)
        return 1
    extended = read_fundamentals(reference / "edgar_fundamentals_ext.csv.gz")
    fundamentals = read_fundamentals(reference / "edgar_fundamentals.csv.gz")
    weights = k09_weights(session, known, extended, fundamentals, list(known.columns), sectors)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.Series(weights, name="weight").rename_axis("ticker").reset_index().to_csv(out, index=False, lineterminator="\n")
    print(f"{session}: {len(weights)} weights ({sum(1 for value in weights.values() if value > 0)} long, {sum(1 for value in weights.values() if value < 0)} short) -> {out}")
    if args.ledger:
        if not args.generation:
            print("--ledger needs --generation", file=sys.stderr)
            return 2
        from cycle_decide import read_weights

        created = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        row = write_decision(ROOT / "ml" / "generations" / "registry.json", args.generation, read_weights(out), Path(args.ledger), session=session, created_at=created, source=str(out))
        print("already decided" if row is None else "decision appended; push forward/decisions.jsonl to the forward-ledger branch before the next 22:45 UTC run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
