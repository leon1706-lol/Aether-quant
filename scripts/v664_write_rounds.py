"""Writes round 4C's, round 4E's and round 4F's rule files and the observers rule, once, with their hashes (V6.6.4).

Run before any score: `evaluation.research_round.write_rules` refuses a second write, so the files and their `.sha256` are never edited. `scripts/vault_record.py` then records them in
the vault, whose commit time is the evidence that the rules came first.

    python scripts/v664_write_rounds.py [--only round4f]
"""

# ruff: noqa: E501  (the rule text and the trial table are one line per entry, so each can be read against the plan)
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.research_round import write_rules  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v664"
V660 = json.loads((ROOT / "ml" / "evaluation" / "v660" / "rules.json").read_text(encoding="utf-8"))
ROUND3 = json.loads((ROOT / "ml" / "evaluation" / "v661" / "round3.json").read_text(encoding="utf-8"))
BAR = ROUND3["bar"]
LEDGER = "ml/evaluation/v660/trial_ledger.jsonl"
CRYPTO_TOP_K = 10
SECTOR_ETFS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLC", "XLRE"]
BOND_ETFS = ["SHY", "IEF", "TLT", "AGG", "LQD", "HYG", "TIP", "MBB", "EMB", "MUB", "BND", "GOVT", "SHV", "IGIB", "VCIT", "VCSH", "BIV", "BSV", "TLH", "IGSB", "JNK", "BWX"]

R_ROUND4C = (
    "Cell CS, side A, hashed before any score. x01-x14 count in N whether run or not. CS has been read by c1-c5. Bar unchanged: R-SLEEVE3 and PBO < 0.5 (evaluation/pbo.py, blocks = 16, over c1-c5 and "
    "x01-x14 on CS). Crypto minimum names 12, except x10 and x11 which hold BTC and ETH by design (2). A gated trial (x12, x14) holds nothing while its gate is off, so its live names are counted on the rebalances where the gate is on, against the same minimum of 12; IC names 8; x09, x10, x11 have no IC clause. x13 starts 2019-01-01 with the split 2020-07-01 "
    "unchanged. Any pass is audited (oracle, reversed, one-day shift, cost check) before it is believed. A defect voids the trial, with no re-score. The single survivor, or the highest-Sharpe survivor, "
    "is frozen. Zero survivors: verdict at once, no freeze, no read of CV. Then crypto R-HOLD1 once on CV, then R-LEAN21 and R-EDGE2 unchanged. CV's side B was read once by t3 alone (R-CRYPTO1), "
    "disclosed. A survivor's coins that Coinbase's public product list doesn't show as trading today are reported beside its verdict, flagged as hindsight, and do not change the gate."
)
R_ROUND4E = (
    "Cell S, side A, hashed before any score. q01-q07, e4, e5 count in N whether run or not. S has been read by 39 scored trials and 18 audit looks, so a pass is weaker evidence than a round-1 pass. "
    "Bar unchanged: R-SLEEVE3 and PBO < 0.5 (blocks = 16, over round 3's prior columns, k01-k10, and these nine). e4 and e5 have no IC clause. e4 needs 5 names, e5 needs 1. q03 starts 2013-01-01 with "
    "the split 2015-01-01 unchanged, because its signal needs earlier years. Audit, voiding, freeze and zero-survivor rules as in R-ROUND3. Then R-HOLD1 once, then R-LEAN21 and R-EDGE2 unchanged."
)
R_ROUND4F = (
    "Cell S, side A, hashed before any score. e4b and e5b count in N whether run or not. They are round 4E's e4 and e5 again, unchanged in hypothesis, assets, windows and minimum names: those two were voided "
    "because the runner masked every table to the cell's index members, and ETFs and SPY are not members, so they held nothing (no live names, Sharpe 0.0, found from the live-name count before any return was "
    "read). The runner now masks a time-series or direct trial to the assets it names. Bar unchanged: R-SLEEVE3 and PBO < 0.5 (blocks = 16, over round 3's prior columns, k01-k10, q01-q07 and these two). "
    "e4b and e5b have no IC clause. e4b needs 5 names, e5b needs 1. Audit, voiding, freeze and zero-survivor rules as in R-ROUND3 and R-ROUND4E, with no further re-registration of either."
)
R_OBSERVERS = (
    "k09, plus the three x-trials with the highest pooled Sharpe on CS, by that rule alone (a tie goes to the lower trial number). Each enters the registry as tier none, stage shadow, admission {}, "
    "expected_sharpe 0, and can't hold capital. An x-trial needing funding or a history the forward feed lacks is replaced by the next-highest eligible trial, recorded here when it happens. Each counts "
    "in N when judged, at 60, 252 and 504 sessions, alongside the incumbent, inside forward/generations.jsonl."
)


def crypto_trials() -> dict:
    def xs(builder: str, *, every: int = 20, params: dict | None = None, tests: str, why: str, **extra) -> dict:
        return {"tests": tests, "kind": "cross_sectional", "rebalance_every": every, "top_k": CRYPTO_TOP_K, "builder": builder, "params": params or {}, "why": why, **extra}

    return {
        "x01": xs("low_vol", params={"window": 60}, tests="low volatility", why="the calmer coin earning more per unit of risk is the best-replicated crypto anomaly after momentum, and no earlier trial held it"),
        "x02": xs("lottery_max", params={"window": 30}, tests="the lottery effect", why="coins with one huge recent day are over-bought and earn less afterwards; the book is long-only, so it holds the calm end"),
        "x03": xs("amihud", params={"window": 30}, tests="illiquidity", why="less liquid coins should pay a premium; the liquid-universe filter keeps it tradeable"),
        "x04": xs("volume_trend", params={"short": 7, "long": 28}, tests="rising attention", why="volume is information c1-c4 never read"),
        "x05": xs("high_proximity", params={"window": 365, "min_periods": 180}, tests="distance to the 52-week high", why="the equity version (w11, 0.26) was weak, crypto's retail anchoring is different"),
        "x06": xs("short_reversal", every=5, params={"window": 7}, tests="weekly reversal", why="the short-horizon reversal that costs killed in equities (w14) is cheaper in crypto only if turnover stays low, tested once"),
        "x07": xs("low_beta", params={"window": 60}, tests="low beta to BTC", why="the betting-against-beta pattern, long leg only"),
        "x08": xs("idio_vol", params={"window": 60}, tests="idiosyncratic volatility", why="the volatility left after BTC; c2 used the return left after BTC, never its volatility"),
        "x09": {"tests": "trend not crowded by funding", "kind": "time_series", "rebalance_every": 5, "builder": "funding_filtered_trend", "params": {"window": 14, "rank_window": 180, "cut": 0.8}, "why": "the installed sleeve's trend with crowded coins set flat; funding starts 2020-01-01, so before that this is the plain trend votes"},
        "x10": {"tests": "BTC and ETH while breadth is wide", "kind": "time_series", "rebalance_every": 5, "min_live_names": 2, "builder": "breadth_timing", "params": {"window": 50, "floor": 0.5}, "why": "a market-wide trend filter on the two coins that c5 holds"},
        "x11": {"tests": "BTC and ETH on a volatility target, always", "kind": "time_series", "rebalance_every": 5, "min_live_names": 2, "builder": "core_constant", "params": {}, "why": "the control: if a volatility-managed hold of the core coins matches the trend sleeve, the trend adds nothing"},
        "x12": xs("low_vol", params={"window": 60}, tests="low volatility, only while BTC is above its 120-day average", why="x01 gated by regime", gate="regime"),
        "x13": {"tests": "walk-forward gradient boosting on the ten crypto features", "kind": "cross_sectional", "rebalance_every": 20, "top_k": CRYPTO_TOP_K, "start": "2019-01-01", "score_file": "x13", "why": "the only learned trial; refit each 1 January and 1 July on finished labels, scripts/v664_crypto_gbm.py"},
        "x14": {"tests": "a composite of x01, x02 and x05, regime gated", "kind": "cross_sectional", "rebalance_every": 20, "top_k": CRYPTO_TOP_K, "gate": "regime", "recipe": {"op": "rank_mean", "parts": ["x01", "x02", "x05"], "minimum": 3}, "why": "the three that need no volume"},
    }


def equity_trials() -> dict:
    def pooled(builder: str, params: dict, tests: str, why: str, *, every: int = 20, **extra) -> dict:
        return {"tests": tests, "kind": "pooled", "rebalance_every": every, "min_weight_change": 0.001, "builder": builder, "params": params, "why": why, **extra}

    return {
        "q01": pooled("similarity_table", {"max_age": 130}, "an unchanged 10-K or 10-Q", "a filing that barely changed from last year's carries no news (Cohen, Malloy and Nguyen); new information, never read here"),
        "q02": pooled("announcement_proximity", {"window_days": 14}, "the announcement premium", "stocks earn more in the sessions before their expected earnings date (Frazzini and Lamont); expected from the date a year earlier", every=5),
        "q03": pooled("same_month_seasonality", {"years": 7, "min_years": 3}, "same-calendar-month seasonality", "a name's own past returns in this month (Heston and Sadka); starts 2013-01-01", start="2013-01-01", every=21),
        "q04": pooled("opportunistic_buying", {"routine_years": 3, "window": 63}, "opportunistic insider purchases", "routine buyers carry no information (Cohen, Malloy and Pomorski); w08 netted every trade"),
        "q05": pooled("cash_profitability", {"max_age": 400}, "cash-flow profitability", "trailing operating cash flow over assets, from the quarterly download; w06 held it only inside a composite"),
        "q06": pooled("announcement_return", {"days": 3, "decay": 60, "bench": "SPY"}, "the earnings-day reaction", "the abnormal move around the release, which w07's surprise (-0.52) never read"),
        "q07": {"tests": "q01 with quarterly accruals", "kind": "pooled", "rebalance_every": 20, "min_weight_change": 0.001, "recipe": {"op": "rank_mean", "parts": ["q01", "accruals_ttm"], "signs": {"accruals_ttm": -1.0}, "minimum": 2}, "why": "k09, the strongest earlier signal (IC t 2.60), joined to new information; k09 itself is not rerun"},
        "e4": {"tests": "12-1 month trend across sector, bond and equity ETFs", "kind": "time_series", "rebalance_every": 21, "min_live_names": 5, "builder": "cross_asset_trend", "params": {"tickers": [*SECTOR_ETFS, *BOND_ETFS, "SPY"], "long": 252, "skip": 21}, "universe": ["sector_etf", "bond_etf", "benchmark"], "why": "time-series momentum on liquid ETFs, the managed-futures premium without futures"},
        "e5": {"tests": "SPY on term and credit conditions", "kind": "direct", "rebalance_every": 21, "min_live_names": 1, "builder": "term_credit_timing", "params": {"ticker": "SPY", "window": 252}, "universe": ["benchmark"], "why": "long SPY only while the curve is positive and credit is tight"},
    }


def validate(payload: dict) -> None:
    """Every trial must be one the runner can build: a closed builder, a known kind and gate, a recipe over earlier trials. Nothing is scored."""
    from evaluation.research_round import KINDS
    from evaluation.round_builders import BUILDERS

    seen: list[str] = []
    for trial, entry in payload["trials"].items():
        assert entry["kind"] in KINDS, (trial, entry["kind"])
        assert sum(key in entry for key in ("builder", "recipe", "score_file")) == 1, (trial, "exactly one of builder, recipe, score_file")
        if "builder" in entry:
            assert entry["builder"] in BUILDERS, (trial, entry["builder"])
        if "recipe" in entry:
            assert all(part in seen or part in ("accruals_ttm",) for part in entry["recipe"]["parts"]), (trial, "a recipe names an earlier trial or a stored feature")
        assert entry.get("gate") in (None, "regime"), (trial, entry.get("gate"))
        seen.append(trial)
    assert set(payload["no_ic_clause"]) <= set(payload["trials"])


def round4f_payload(equity: dict) -> dict:
    trials = {"e4b": {**equity["trials"]["e4"], "tests": equity["trials"]["e4"]["tests"] + " (round 4E's e4, masked to its ETFs)"},
              "e5b": {**equity["trials"]["e5"], "tests": equity["trials"]["e5"]["tests"] + " (round 4E's e5, masked to SPY)"}}
    return {
        "name": "round4f", "written": "before any e4b/e5b score", "rule": R_ROUND4F, **{k: equity[k] for k in ("bar", "ledger", "window_label", "out_dir", "side", "track", "cell", "min_live_names", "min_ic_names", "pbo_blocks")},
        "pbo_rule": "evaluation/pbo.py with blocks=16 over round 3's prior columns, k01-k10, q01-q07 and these two on cell S. PBO >= 0.5 or None: verdict at once, no retry.",
        "no_ic_clause": ["e4b", "e5b"],
        "prior_daily": [*equity["prior_daily"], "ml/evaluation/v664/selection_daily_round4e.parquet"],
        "prior_columns": [*equity["prior_columns"], "q01", "q02", "q03", "q04", "q05", "q06", "q07"],
        "parent": equity["parent"], "trials": trials,
        "disclosures": ["Round 4E's e4 and e5 are void (a masking defect in the runner, #336) and stay counted in N; these two are new trials of the same hypotheses, so N rises by two more.",
                        "Cell S has been read by 48 scored trials and 18 audit looks, and these two are chosen with that knowledge, but their returns were never seen: the voided runs held nothing."],
    }


def main(argv: list[str] | None = None) -> int:
    only = list(sys.argv[1:] if argv is None else argv)
    OUT.mkdir(parents=True, exist_ok=True)
    common = {"bar": BAR, "track": None, "ledger": LEDGER, "window_label": "v660_selection", "out_dir": "ml/evaluation/v664", "side": "A"}
    crypto = {
        "name": "round4c", "written": "before any x-score", "rule": R_ROUND4C, **{k: v for k, v in common.items() if k != "track"}, "track": "C", "cell": "CS", "min_live_names": 12, "min_ic_names": 8, "pbo_blocks": 16,
        "pbo_rule": "evaluation/pbo.py with blocks=16 over c1-c5 and x01-x14 on cell CS. PBO >= 0.5 or None: verdict at once, no retry. x13 is zero-filled before 2019-01-01.",
        "no_ic_clause": ["x09", "x10", "x11"], "prior_daily": ["ml/evaluation/v660/selection_daily.parquet"], "prior_columns": ["c1", "c2", "c3", "c4", "c5"],
        "parent": {"file": "rules.json", "sha256": ROUND3["parent"]["sha256"]}, "trials": crypto_trials(),
        "disclosures": [
            "CS has been read by c1-c5, and these fourteen are chosen with that knowledge.",
            "The cell holds Binance's USDT coins, priced under the Coinbase cost model; coins Coinbase does not list today are in it, so a survivor's coverage on Coinbase is reported beside its verdict.",
            "Funding starts 2020-01-01: before that x09 is the plain trend votes.",
            "The book is long-only (crypto weights are clipped at zero), so a reversal or a low-risk rank only ever holds the long leg.",
            "x05 needs 180 sessions of history and x03, x04 need volume, so a coin's first sessions are blank.",
            "x13 starts 2019-01-01, and its first half is 18 months.",
            "x12 and x14 are gated by BTC's 120-session average and hold nothing while it is off, so their live names are counted on the rebalances where the gate is on (the median over all rebalances would read the gate as a lack of names).",
        ],
    }
    equity = {
        "name": "round4e", "written": "before any q-score", "rule": R_ROUND4E, **{k: v for k, v in common.items() if k != "track"}, "track": "W", "cell": "S", "min_live_names": 150, "min_ic_names": 20, "pbo_blocks": 16,
        "pbo_rule": "evaluation/pbo.py with blocks=16 over round 3's prior columns, k01-k10 and these nine on cell S. PBO >= 0.5 or None: verdict at once, no retry. q03 is zero-filled before 2013.",
        "no_ic_clause": ["e4", "e5"],
        "prior_daily": ["ml/evaluation/v660/selection_daily.parquet", "ml/evaluation/v660/selection_daily_r2.parquet", "ml/evaluation/v661/selection_daily_round3.parquet"],
        "prior_columns": [*ROUND3["prior_columns"], "k01", "k02", "k03", "k04", "k05", "k06", "k07", "k08", "k09", "k10"],
        "parent": ROUND3["parent"], "trials": equity_trials(),
        "disclosures": [
            "Cell S has been read by 39 scored trials and 18 audit looks, and these nine are chosen with that knowledge.",
            "q01, q02 and q06 read an EDGAR download made in this phase, for today's ticker list and side-A names only, with nothing filed after 2018-12-31. Its coverage by year is reported with the verdict.",
            "q02's expected date is an announcement 52 weeks earlier, so a name needs a year of history; q04 reads insider filings dated by `filed`.",
            "e4's ETFs and e5's rates are read on S's calendar; e5 reads the rates one session late.",
            "q03 starts 2013-01-01 and needs three earlier years of the same month.",
        ],
    }
    if only[-2:] == ["--only", "round4f"]:
        payload = round4f_payload(equity)
        validate(payload)
        print(json.dumps({"round4f": write_rules(payload, OUT / "round4f.json")}, indent=1))
        return 0
    digests = {}
    for payload in (crypto, equity):
        validate(payload)
    for name, payload in (("round4c", crypto), ("round4e", equity)):
        digests[name] = write_rules(payload, OUT / f"{name}.json")
    observers = {"name": "observers", "written": "before any x-score", "rule": R_OBSERVERS, "ledger": LEDGER}
    digests["observers"] = write_rules(observers, OUT / "observers.json")
    print(json.dumps(digests, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
