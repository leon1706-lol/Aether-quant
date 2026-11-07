"""R-ROUND3's rule file, written once before any k-score. The trials were fixed in the phase plan before the audit ran; the audit can only be cited.

    python scripts/v661_write_round3.py [--cite ml/evaluation/v661/model_audit.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.research_round import write_rules  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v661"
ROUND_FILE = OUT / "round3.json"
V660 = ROOT / "ml" / "evaluation" / "v660"
BAND = 0.001
LATE_START = "2013-01-01"
R_ROUND3 = (
    "Cell S, side A, hashed before any score. k01-k10 and the 18 audit looks count in N whether run or not (N = 192). S has been read by 36 trials, so a pass is weaker "
    "evidence than a round-1 pass. Bar unchanged: R-SLEEVE3 and PBO < 0.5 (evaluation/pbo.py, blocks = 16, over round 1's 22 columns, round 2's 8 and k01-k10). k06-k08 start "
    "2013-01-01 with the split 2015-01-01 unchanged, and are zero-filled earlier in the PBO matrix. Any pass is audited (oracle, reversed, one-day shift, cost check) before it is "
    "believed. A defect voids the trial, with no re-score. One candidate is frozen: the single survivor, or the better of t1/t2 by selection Sharpe. Zero survivors: verdict at "
    "once, no freeze, no holdout read. Then R-HOLD1 once, then R-LEAN21 and R-EDGE2 unchanged."
)
FUNDAMENTAL_SIGNS = {
    "gp_assets": 1.0, "net_issuance": -1.0, "asset_growth": -1.0, "accruals": -1.0, "earnings_yield": 1.0, "book_to_market": 1.0, "leverage": -1.0, "cfo_assets": 1.0,
}
R03_RECIPE = {"op": "rank_mean", "parts": ["w03", "w04", "w06"], "minimum": 3}


def trials() -> dict:
    return {
        "k01": {
            "tests": "per-class gross by breadth", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND, "recipe": {"op": "single", "parts": ["w04"]},
            "why": "w04 is the one premium that kept a positive IC in all 8 years; each sector was given gross 1 whatever its size, which is the book's real inefficiency",
        },
        "k02": {"tests": "r03 pooled", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND, "recipe": R03_RECIPE, "why": "r03 was the best net score, 0.57; its second half fell to 0.21"},
        "k03": {
            "tests": "k02 less known exposures", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND,
            "recipe": {"op": "residualise", "parts": ["w03", "w04", "w06"], "minimum": 3, "exposures": ["beta_252", "market_cap", "vol_60"]},
            "why": "a residual against beta, size and volatility should cost little Sharpe if the premium is not those exposures",
        },
        "k04": {"tests": "k02 at a third of the cost", "kind": "pooled", "rebalance_every": 60, "min_weight_change": 0.005, "recipe": R03_RECIPE, "why": "these are slow signals; costs took about a third of w04's gross Sharpe"},
        "k05": {
            "tests": "slopes held to published signs", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND, "builder": "fama_macbeth_ridge", "signs": FUNDAMENTAL_SIGNS, "kappa": 36, "ridge": 1.0,
            "why": "the first model that reads only years holding its inputs: m2-m4 trained from 2004 on features 19 names had in 2009",
        },
        "k06": {
            "tests": "a small tree held to published signs", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND, "score_file": "k06", "start": LATE_START,
            "trainer": "train_cross_sectional.py --model gbm_monotone --variant a --seeds 1,2,3 --feature-set fundamental --train-start 2011-07-01 --first-test-year 2013 --purge-days 31 --score-end 2018-12-31",
            "why": "interactions without the freedom to learn a premium backward",
        },
        "k07": {
            "tests": "the installed network family, on the fundamentals era", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND, "score_file": "k07", "start": LATE_START,
            "trainer": "train_cross_sectional.py --model mlp_multitask --variant a --seeds 1,2,3,4,5 --feature-set fundamental --train-start 2011-07-01 --first-test-year 2013 --purge-days 31 --score-end 2018-12-31",
            "runs_if": "k05's mean rank IC is above 0; counted regardless",
            "why": "the network the project ships, given inputs it can learn from; if the linear model finds nothing, the network has nothing to find",
        },
        "k08": {
            "tests": "a fixed ensemble of the models", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND, "start": LATE_START,
            "recipe": {"op": "rank_mean", "parts": ["k05", "k06", "k07"], "optional_parts": True, "minimum": 2}, "why": "averaging different errors, never fitted",
        },
        "k09": {
            "tests": "accruals on quarterly filings", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND, "recipe": {"op": "single", "parts": ["accruals_ttm"], "signs": {"accruals_ttm": -1.0}},
            "why": "w04 read annual filings, up to 15 months stale; the literature's accruals are quarterly",
        },
        "k10": {
            "tests": "balance-sheet bloat", "kind": "pooled", "rebalance_every": 20, "min_weight_change": BAND,
            "recipe": {"op": "rank_mean", "parts": ["k09", "noa", "capex_growth"], "signs": {"noa": -1.0, "capex_growth": -1.0}, "minimum": 2},
            "why": "net operating assets and capital spending are the investment side of accruals, and no earlier trial held them",
        },
    }


def payload(*, cite: Path | None = None) -> dict:
    rules = json.loads((V660 / "rules.json").read_text(encoding="utf-8"))
    r2 = json.loads((V660 / "rules_r2.json").read_text(encoding="utf-8"))
    written = {
        "name": "round3", "written": "before any k-score", "rule": R_ROUND3, "bar": rules["rules"]["R-SLEEVE3"], "pbo_rule": rules["rules"]["PBO"], "cell": "S", "side": "A", "track": "W",
        "out_dir": "ml/evaluation/v661", "ledger": "ml/evaluation/v660/trial_ledger.jsonl", "window_label": "v660_selection", "min_live_names": 150, "min_ic_names": 20, "pbo_blocks": 16,
        "prior_daily": ["ml/evaluation/v660/selection_daily.parquet", "ml/evaluation/v660/selection_daily_r2.parquet"], "prior_columns": [*rules["trials"]["pbo_columns"], *r2["trials"]],
        "parent": {"file": "rules.json", "sha256": hashlib.sha256((V660 / "rules.json").read_bytes()).hexdigest()}, "trials": trials(),
        "disclosures": [
            "Cell S has been read by 36 trials, and these ten are chosen with that knowledge.",
            "The model audit looked at six feature groups at three horizons on S before this file was written. The trials were fixed in the phase plan before it ran, and it added none.",
            "Filings before about 2011 are sparse (19 names in 2009, 292 in 2010, 466 in 2011), so k05 leans on its sign prior in its first year and k06-k08 only begin in 2013, leaving two years in their first half.",
            "k09 and k10 read a quarterly and annual download made in this phase, which uses today's list of tickers, as every fundamentals trial has.",
            "The holdouts stay closed unless the gate leaves a survivor.",
        ],
    }
    if cite is not None:
        written["audit_cited"] = {"file": str(cite.name), "sha256": hashlib.sha256(cite.read_bytes()).hexdigest()}
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cite", default=None)
    args = parser.parse_args(argv)
    print(write_rules(payload(cite=Path(args.cite) if args.cite else None), ROUND_FILE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
