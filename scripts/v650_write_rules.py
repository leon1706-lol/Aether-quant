"""Writes ml/evaluation/v650/rules.json and its hash, before any V6.5.0 candidate has a score. Refuses to overwrite.

    python scripts/v650_write_rules.py
"""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from portfolio.premia_signals import WeightSettings  # noqa: E402
from v650_trials import ABLATION_IDS, ALL_SPECS, COMBINATION_IDS  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v650"

SELECTION = {"rule_sleeves": ["2014-12-01", "2019-03-15", "2023-06-30"], "ml_sleeves": ["2019-01-01", "2021-04-01", "2023-06-30"]}
WINDOWS = {
    "verification": ["2023-07-01", "2026-11-02"],
    "long": ["2014-12-01", "2026-11-02"],
    "pre2013": ["2004-06-01", "2012-12-31"],
    "selection_lean": ["2014-12-01", "2023-06-30"],
}


def rules() -> dict:
    return {
        "written": "2026-11-04, before any V6.5.0 candidate score; text = the plan the owner started on 2026-11-04",
        "disclosure": [
            "t3_trend_blend's 2014-2023 result was read in V6.4.4 (Problems.md #262); the V6.4.4 trend rule failed on 2023-2025.",
            "The installed models were trained on 2014-2021 and validated on 2022-2023 with the V5.8.0 recipe; T1/T2 recipes share its design, so the ML selection window is not unseen in that sense.",
            "The BT18-BT23 ablations run on the verification window, already read for this path by every run since V5.8; they compete only in R-LEAN19.",
            "The universe was chosen with hindsight and has no delisted names: long legs and reversal are flattered; null time_shift partly catches it.",
            "EDGAR earnings-surprise trials: SEC refused the generic client (HTTP 403) and no personal contact is sent without the owner's say; those 2 planned trials are closed as data unavailable, never scored, and not counted.",
            "Only 2-core and 4-core Codespace machines are available; nothing in the rules depends on the machine.",
        ],
        "selection_windows": SELECTION,
        "windows": WINDOWS,
        "trial_budget": 60,
        "weight_settings": asdict(WeightSettings()),
        "costs": {
            "equity_and_bond": "max(1.5 bps, $1) per side + 3 bps slippage",
            "forex": "max(0.2 bps, $2) per side + 1 bp slippage; minimum trade $5,000",
            "crypto": "Coinbase date-effective taker fee + 10 bps slippage, long only, 5% per name, 15% class",
            "financing": "debit at Lean's rate + 150 bps; stock borrow 25 bps; forex r_base - r_quote, less 50 bps on |notional|",
            "sensitivity": "2x costs reported for the installed candidate, not a gate",
        },
        "risk_on_the_target_path": {
            "target_vol": 0.07, "gross_cap": 1.4, "max_total_drawdown_pct": 0.15, "max_daily_drawdown_pct": 0.05,
            "max_drawdown_velocity_pct_per_bar": "3 x 7% / sqrt(252)", "rolling_sharpe_trigger": "off",
            "bypass_sticky_trade_lock": "false in every verification run",
        },
        "trials": {
            "sleeves": [
                {"id": spec.id, "track": spec.track, "kind": spec.kind, "family": spec.family, "universe": list(spec.universe),
                 "rebalance_every": spec.rebalance_every, "params": dict(spec.params)}
                for spec in ALL_SPECS
            ],
            "combinations": COMBINATION_IDS,
            "ablations": ABLATION_IDS,
        },
        "R-INSTR1": "G0. Daily return correlation engine vs Lean >= 0.90 on BT13, BT14 and BT15, annual return gap <= 100 bps, within <= 3 fix cycles. If it fails, thin Lean itself scores the trials and each survivor gets 20 Lean placebos instead of 200 offline.",
        "R-SLEEVE2": "G1 (evaluation.premia_research.selection_gate). Net of costs and financing, median over 5 rebalance phases: Sharpe >= 0.40 in both halves and >= 0.50 pooled on its selection window, and p < 0.05 against each applicable null (200 offline placebos per null: asset_block and time_shift for rankings, sign_block and time_shift for directions and timing). Among survivors daily correlation > 0.7 drops the lower Sharpe; at most 5 remain, by pooled Sharpe. Zero survivors go to R-LEAN19.",
        "PBO": "evaluation.pbo over every selection-window trial's daily returns. PBO >= 0.5 goes to R-LEAN19.",
        "T6": "Over the survivors only: t6_inverse_vol (trailing-year inverse volatility) and t6_hrp (compute_hrp_weights), monthly, never fitted to returns; the one with the higher selection Sharpe goes on. A single survivor is its own combination.",
        "R-LEAN20": "G2. The T6 winner in Lean over 2014-12-01..2023-06-30: alpha Newey-West t >= 2.0 vs SPY/AGG/BTC, drawdown <= 15%, complete run. Failure goes to R-LEAN19 with no verification read.",
        "R-EDGE1": {
            "freeze": "Candidate weight code and config hashed and recorded in the local vault before any row after 2023-06-30 is generated.",
            "E1": "Lean Sharpe >= 1.00 on 2023-07-01..2026-11-02: median of 5 phase offsets; the median run becomes the pin.",
            "E2": "Alpha Newey-West t >= 3.0 vs SPY/AGG/BTC on Lean 2014-12-01..2026-11-02.",
            "E3": "Deflated Sharpe >= 0.95 on the E2 series: N = 78 legacy trials + all V6.5.0 candidates; variance = same-window V6.5.0 candidates, floored at 0.04. The legacy-variance figure is reported beside it and does not block (owner saw this choice at the start).",
            "E4": "Lean placebos on the E1 window: 40 per null, the candidate's ex-T-bill Sharpe beaten by at most 1 in each set (p = 2/41).",
            "E5": "Lean on data_pre2013: ex-T-bill Sharpe > 0 and alpha > 0 at the same costs; 20 placebos reported, not blocking.",
            "reads": "Each once; no iteration on a verification window after a failure.",
        },
        "R-LEAN19": "Fallback when R-EDGE1 fails or is not reached. Pool: the T6 winner, every G1 survivor alone, BT18-BT23. Each gets 5 phases on 2023-07-01..2026-11-02 (the gated BT18-BT23 path runs its one configured phase). The best by median ex-T-bill Sharpe installs iff: Lean Sharpe >= BT11 + 0.10 (>= -0.104); ex-T-bill Sharpe >= BT11 + 0.10 (>= 0.368), which leverage alone cannot pass; vol <= 10%; drawdown <= 15%; gross <= 2x; complete run with no engine-log errors; long-window ex-T-bill Sharpe > 0 where it can be scored. README label: 'improved, not verified'. No pass: BT11 stays.",
        "R-ALPHA2": "Descriptive: the E2/E3 figures of whatever is pinned at the end, reported for every candidate run.",
        "placebos_and_plumbing": "Excluded from N and from the variance: they are nulls or tests of the machinery and can never be selected (owner saw this choice at the start).",
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "rules.json"
    if path.exists():
        print(f"{path} exists; rules are written once", file=sys.stderr)
        return 1
    text = json.dumps(rules(), indent=1)
    path.write_text(text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (OUT / "rules.sha256").write_text(digest + "\n", encoding="utf-8", newline="\n")
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
