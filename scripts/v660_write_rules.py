"""Writes ml/evaluation/v660/rules.json and its hash, before any V6.6.0 candidate has a score. Refuses to overwrite.

    python scripts/v660_write_rules.py
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

from v660_trials import ALL_SPECS, COMBINATION_IDS, MIN_IC_NAMES, MIN_LIVE_NAMES, MIN_LIVE_NAMES_BY_TRIAL, NO_IC_CLAUSE, PBO_COLUMNS, cell_of  # noqa: E402

from data_pipeline.sp500_membership import ISSUER_TWINS, RENAMES  # noqa: E402
from evaluation.research_cells import CELLS, FREE_CELLS  # noqa: E402
from evaluation.wide_context import PATH_OVERRIDES, WIDE_SETTINGS  # noqa: E402
from portfolio.target_weights import DEFAULT_NO_BAR_HAIRCUT  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v660"

RULES = {
    "written": "2026-11-05, before any V6.6.0 candidate score; text = the plan the owner started on 2026-11-05",
    "disclosures": [
        "The families come from published work and decayed after publication; V1 and V3 measure that.",
        "Project names were read 2013-2026 by every earlier phase and are always side A.",
        "Cell P's side A rows are read by ML training (cell TA).",
        "Market-wide conditions over all windows are known to whoever wrote these rules.",
        "Yahoo has no delisted names; R-SURV1 charges for the gap, and QC cloud tests it where available.",
        "S&P 500 membership is built from Wikipedia's change lists, and has errors.",
        "EDGAR's ticker list holds current tickers, so a name that no longer trades has no fundamentals or sector; such a name is never traded and counts as missing in R-SURV1.",
        "t3_crypto_trend_blend's selection window was read in V6.5.0; it enters the combination pool as installed.",
        "A sector comes from today's SIC code, not the code at each date; it only sets which names rank together.",
    ],
    "cells": {name: asdict(cell) for name, cell in CELLS.items()},
    "free_cells": sorted(FREE_CELLS),
    "rename_and_twin_maps": {"renames": RENAMES, "issuer_twins": ISSUER_TWINS},
    "trial_budget": 30,
    "weight_settings": asdict(WIDE_SETTINGS),
    "path_overrides": PATH_OVERRIDES,
    "no_bar_exit_haircut_by_class": DEFAULT_NO_BAR_HAIRCUT,
    "costs": {
        "equity_and_bond": "max(1.5 bps, $1) per side + 3 bps slippage",
        "crypto": "Coinbase date-effective taker fee + 10 bps slippage, long only, 5% per name, 15% class (blocking); a Binance-fee run is reported, never gating",
        "financing": "debit at Lean's rate + 150 bps; stock borrow 25 bps",
        "sensitivity": "NAV $25k and 2x costs reported for every survivor, not a gate",
    },
    "model_track": {
        "training_rows": "side A only, always, including verification and any install",
        "purge_calendar_days": 31,
        "early_stop_gap_sessions": 22,
        "first_training_year": 2004,
        "selection_test_years": [2011, 2018],
        "seeds": [1, 2, 3],
        "m4_hidden_layers": [128, 64],
        "m4_dropout": 0.15,
        "m3_compute_fallback": "If one window takes over 40 minutes: 1 seed, 8 epochs. If still over 90 minutes: close m3, and m5 is the rank mean of m2 and m4.",
    },
    "trials": {
        "sleeves": [{"id": spec.id, "track": spec.track, "kind": spec.kind, "family": spec.family, "universe": list(spec.universe), "rebalance_every": spec.rebalance_every, "params": dict(spec.params), "cell": cell_of(spec)} for spec in ALL_SPECS],
        "combinations": COMBINATION_IDS,
        "no_ic_clause": list(NO_IC_CLAUSE),
        "min_live_names": MIN_LIVE_NAMES,
        "min_live_names_by_trial": MIN_LIVE_NAMES_BY_TRIAL,
        "min_ic_names": MIN_IC_NAMES,
        "pbo_columns": list(PBO_COLUMNS),
    },
    "rules": {
        "R-VEL1": "On t3_crypto_trend_blend, 2014-12-01..2026-11-02, engine: a sticky drawdown-velocity lock at k x target_vol / sqrt(252), k in {5, 8}, against off. Adopt the smallest k whose lock leaves >= 95% of sessions trading and cuts the worst 5-day loss by >= 20%, verified in Lean. Otherwise velocity stays off as a decision, with the numbers.",
        "R-INSTR2": "On BT25 and BT27: daily correlation engine vs Lean >= 0.99, annual gap <= 100 bps, fees within 2%, within <= 3 fix cycles. On failure selection stays on the engine, but every survivor must repeat its score in Lean on its selection cell.",
        "R-SLEEVE3": "Net of costs and financing, on strategy_excess (sessions at 252 unless crypto-only), median of 5 phases, in its selection cell: clears min_live_names; Sharpe >= 0.40 in both halves and pooled >= 0.50; rank-IC non-overlapping t >= 2.0 (not for no_ic_clause); p < 0.05 against each null of nulls_for, 100 placebos each, run only for trials passing the earlier clauses. Among survivors, daily correlation > 0.7 drops the lower Sharpe; at most 5 remain. Zero survivors: verdict at once.",
        "PBO": "evaluation/pbo.py with blocks=16 over pbo_columns on cell S. PBO >= 0.5 or None: verdict at once, no retry. Crypto trials and w13 are on other windows, and t1/t2 are built from survivors; they are outside the matrix.",
        "R-LEAN21": "The better of t1/t2 by selection Sharpe, in Lean on the free cells (equities S, crypto CS): alpha HAC t >= 2.0 against SPY/AGG/BTC, drawdown <= 15%, complete run. Failure: verdict at once.",
        "R-HOLD1": "After the freeze, once, offline, on the candidate's equity sleeves: V3 Sharpe >= 0.50 and alpha t >= 2.0; V1 and V2 Sharpe > 0 (V1 from 2023-01-01 if it holds w13). A crypto-only candidate reads CV: Sharpe >= 0.50 and alpha t >= 2.0. Failure: verdict at once, no Lean placebos spent.",
        "R-CRYPTO1": "Frozen t3_crypto_trend_blend on never-read side-B liquid coins, 2018-01-01..2026-11-02, delisted included: Sharpe, alpha t and the share of return from coins later delisted. Reported always; gating only when the candidate holds crypto (E5a).",
        "R-SURV1": "drag(y) = missing_share(y) x long_gross(y) x 0.30, per year, subtracted evenly per day. missing_share counts every excluded name and, for a fundamental family, names with no EDGAR data. E1 after drag = Lean Sharpe - drag / Annual Standard Deviation.",
        "R-EDGE2": {
            "E1": "Lean Sharpe >= 1.00 on 2023-07-01..2026-11-02, median of 5 phases; the median run becomes the pin; minimum phase reported.",
            "E2": "Alpha Newey-West t >= 3.0 vs SPY/AGG/BTC on the longest window the candidate can be scored in (2011-01-01..2026-11-02 with fundamentals), on the T-bill-free series, with n asserted to span it.",
            "E3": "Deflated Sharpe >= 0.95 on the E2 series, N = 128 + V6.6 candidates (asserted), variance from v660 selection candidates floored at 0.04. Legacy-variance DSR reported beside it.",
            "E4": "40 asset_block + 40 time_shift Lean placebos on the E1 window: strategy Sharpe beaten by <= 1 in each set (p = 2/41). Time-series sleeves use sign_block.",
            "E5a": "Lean, side B only, 2019-01-01..2026-11-02: strategy-excess Sharpe >= 0.50 and alpha t >= 2.0. A candidate holding crypto also passes R-CRYPTO1 with Sharpe > 0.",
            "E5b": "Lean on cell P, price families only (fundamental weight redistributed, disclosed): Sharpe > 0, alpha > 0. Not applicable if the candidate has no price family; recorded.",
            "E6a": "After R-SURV1's drag, E1 and E2 still pass.",
            "E6b": "QC cloud, if available on the owner's free plan: strategy Sharpe >= 50% of the free-data figure on the same window and alpha > 0. Unavailable is recorded and doesn't fail; the label then says survivorship bounded, not tested.",
        },
        "after_the_read": "A defect found after R-HOLD1 is read gets its fix, test and Problems entry, with no re-read and no re-freeze. If it could have changed a clause, the verdict is recorded as not verified.",
        "install": "All of R-EDGE2 passing installs the candidate by rule, labelled verified on historical data, forward test pending. Anything else changes nothing and is written up as refuted for this search, quoting excluded_alpha_sharpe per track. No iteration on any verification data.",
    },
}


def main() -> int:
    path = OUT / "rules.json"
    if path.exists():
        raise SystemExit(f"{path} exists: the rules are written once")
    OUT.mkdir(parents=True, exist_ok=True)
    text = json.dumps(RULES, indent=1)
    path.write_text(text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (OUT / "rules.sha256").write_text(digest + "\n", encoding="utf-8", newline="\n")
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
