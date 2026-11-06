"""V6.6.0 addendum: a second, small selection round on the free cell S, and the report-only analyses round 1 left undone.

Round 2 exists because round 1's evidence says where the cost goes: eight sleeves earn a positive no-cost Sharpe that costs then take away. Its eight
trials (rules_r2.json, hashed and recorded in the vault before any score) test two standard remedies, a no-trade band and a wider book, and one fixed
composite of the lowest-turnover signals. They are counted in the trial ledger (so in the deflated Sharpe's N), judged by round 1's unchanged bar,
and read only cell S on side-A names. Nothing here opens V1, V2, V3, P or CV.

    python scripts/v660_round2.py rules
    python scripts/v660_round2.py score
    python scripts/v660_round2.py placebo [--draws 100]
    python scripts/v660_round2.py gate
    python scripts/v660_round2.py pbo
    python scripts/v660_round2.py report      # rank IC by year, sector and liquidity; costs at 2x and NAV 25k (no gate reads these)
    python scripts/v660_round2.py ib_subset   # the installed sleeve on the coins IB lists, at IB's fees
    python scripts/v660_round2.py kraken_subset  # the same on the 11 coins Kraken lists, at Kraken's taker fee
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v660_research import (  # noqa: E402
    DAILY,
    LEDGER,
    OUT,
    WINDOW_LABEL,
    _ic_clause,
    _show,
    assert_selection_only,
    base_config,
    check_rules,
    load_cells,
    passes_earlier_clauses,
    read_json,
    write_json,
)
from v660_trials import PBO_COLUMNS, SECTORS, TOP_K, W, min_live_names  # noqa: E402

from evaluation.premia_research import (  # noqa: E402
    annual_sharpe,
    nulls_for,
    placebo_p_value,
    placebo_sharpes,
    score_sleeve,
    selection_gate,
    weights_for,
)
from evaluation.target_weights_engine import simulate_target_weights  # noqa: E402
from evaluation.trial_ledger import append_trial  # noqa: E402
from portfolio.premia_signals import XS, SleeveSpec  # noqa: E402
from portfolio.wide_signals import live_names_per_rebalance, rank_mean  # noqa: E402

RULES_R2 = OUT / "rules_r2.json"
RULES_R2_SHA = OUT / "rules_r2.sha256"
SCORES_R2 = OUT / "selection_scores_r2.json"
DAILY_R2 = OUT / "selection_daily_r2.parquet"
GATE_R2 = OUT / "selection_gate_r2.json"
PBO_R2 = OUT / "selection_pbo_r2.json"
REPORT_R2 = OUT / "report_only_r2.json"
IB_SUBSET = OUT / "ib_subset.json"

# id: (what it tests, base table(s), rebalance days, names per sector, no-trade band as a share of NAV, why)
TRIALS = {
    "r01": ("a wider book", ("w04",), 20, 10, 0.001, "w04 had the best net score and the nearest miss; twice the names per sector halves the single-name noise"),
    "r02": ("a fixed composite", ("w03", "w04"), 20, TOP_K, 0.001, "asset growth and accruals: the two lowest-turnover signals with a positive net score; equal rank mean, never fitted"),
    "r03": ("a fixed composite", ("w03", "w04", "w06"), 20, TOP_K, 0.001, "r02 plus the quality composite, the third lowest-turnover signal with a positive net score"),
    "r04": ("a no-trade band", ("w14",), 5, TOP_K, 0.01, "residual reversal earned 0.63 before costs and paid them out at a turnover of 97; skip trades under 1% of NAV"),
    "r05": ("a no-trade band", ("w14",), 10, TOP_K, 0.01, "r04 at half the rebalance frequency"),
    "r06": ("a no-trade band", ("w11",), 20, TOP_K, 0.005, "52-week high: 0.39 before costs, 0.26 after, turnover 19"),
    "r07": ("a no-trade band", ("w09",), 20, TOP_K, 0.005, "residual momentum: 0.33 before costs, 0.13 after, turnover 12"),
    "r08": ("a no-trade band", ("w10",), 20, TOP_K, 0.005, "overnight momentum: 0.36 before costs, 0.19 after, turnover 9.6"),
}
IB_COINS = ("BTCUSD", "ETHUSD", "LTCUSD", "BCHUSD", "LINKUSD", "XRPUSD", "ADAUSD", "DOGEUSD")
# Cost-sensitivity set: every sleeve whose no-cost Sharpe was positive in round 1, plus round 2's.
SENSITIVITY = ("w03", "w04", "w06", "w09", "w10", "w11", "w14", "w15")


def spec_of(trial: str) -> SleeveSpec:
    _, _, every, top_k, _, _ = TRIALS[trial]
    return SleeveSpec(trial, "W", XS, "external_score", SECTORS, every, {"table": trial, "top_k": top_k})


def band_of(trial: str) -> float:
    return TRIALS[trial][4]


def check_rules_r2() -> dict:
    check_rules()
    payload = RULES_R2.read_bytes()
    if hashlib.sha256(payload).hexdigest() != RULES_R2_SHA.read_text(encoding="utf-8").strip():
        raise SystemExit("rules_r2.json is not the recorded hash")
    return json.loads(payload)


def stage_rules(args) -> int:
    if RULES_R2.exists():
        raise SystemExit("rules_r2.json is already written and is never overwritten")
    rules = json.loads((OUT / "rules.json").read_text(encoding="utf-8"))
    payload = {
        "written": "before any round-2 score",
        "parent": {"file": "rules.json", "sha256": hashlib.sha256((OUT / "rules.json").read_bytes()).hexdigest()},
        "why_a_second_round": (
            "Round 1 found 0 of 28 survivors on cell S. Eight sleeves had a positive no-cost Sharpe that costs removed (w03 .31, w04 .68, w06 .32, w09 .33, "
            "w10 .36, w11 .39, w14 .63, w15 .19 gross; net 0.10, 0.45, 0.13, 0.13, 0.19, 0.26, -2.06, -0.11). The owner asked for research to improve the model before committing."
        ),
        "honest_limits": [
            "Cell S has now been read by 28 trials; these eight are chosen with that knowledge, so a pass here is weaker than a round-1 pass.",
            "The deflated Sharpe's N counts them (the same ledger), and the bar is round 1's, unchanged: R-SLEEVE3 and PBO below 0.5 over round 1's columns plus these.",
            "A survivor would go to a freeze and the unread holdouts V1-V3 and P once. None of them is read in this round.",
        ],
        "bar": rules.get("rules", {}).get("R-SLEEVE3") or "round 1's R-SLEEVE3, unchanged",
        "cell": "S", "side": "A",
        "trials": {
            trial: {"tests": tests, "tables": list(tables), "rebalance_every": every, "top_k": top_k, "min_weight_change": band, "why": why}
            for trial, (tests, tables, every, top_k, band, why) in TRIALS.items()
        },
        "report_only": [
            "rank IC by year, sector and dollar-volume tercile for m1-m5 and w04",
            f"net Sharpe at 2x costs and at NAV $25k for {', '.join(SENSITIVITY)} and r01-r08",
            f"the installed crypto sleeve on {', '.join(IB_COINS)} at IB's fee schedule (0.15% with a $1.75 minimum, the middle of its 0.12-0.18%)",
        ],
    }
    RULES_R2.write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")
    RULES_R2_SHA.write_text(hashlib.sha256(RULES_R2.read_bytes()).hexdigest() + "\n", encoding="utf-8", newline="\n")
    print(RULES_R2_SHA.read_text().strip())
    return 0


def prepared_cell():
    """Cell S with round 2's tables added and one context per trial (the no-trade band lives in the config)."""
    cell = load_cells([W[0]])["S"]
    panel, member = cell.context.panel, cell.member
    for trial, (_, tables, _, _, _, _) in TRIALS.items():
        parts = [panel.extras[name] for name in tables]
        table = parts[0] if len(parts) == 1 else rank_mean(parts, minimum=len(parts))
        panel.extras[trial] = table.where(member)
    contexts = {trial: dataclasses.replace(cell.context, config=dataclasses.replace(cell.context.config, min_weight_change=band_of(trial))) for trial in TRIALS}
    return cell, contexts


def stage_score(args) -> int:
    check_rules_r2()
    cell, contexts = prepared_cell()
    assert_selection_only(cell.cell.end)
    scores = read_json(SCORES_R2, {})
    frames = pd.read_parquet(DAILY_R2).to_dict("series") if DAILY_R2.exists() else {}
    for trial in TRIALS:
        if (args.only and trial not in args.only) or (trial in scores and not args.force):
            continue
        spec = spec_of(trial)
        signal = cell.context.panel.extras[trial]
        live = live_names_per_rebalance(signal.loc[signal.index >= cell.cell.start], spec.rebalance_every)
        score = score_sleeve(spec, contexts[trial], start=cell.cell.start, split=cell.cell.split, end=cell.cell.end, signal=signal)
        daily = score.pop("daily")
        middle = daily[min(daily)]
        frames[trial] = middle
        ic = _ic_clause(spec, cell, signal)
        scores[trial] = {**score, "cell": "S", "live_names": live, "ic": ic, "round": 2}
        append_trial(LEDGER, trial_id=trial, track="W", window=WINDOW_LABEL, role="candidate", annualised_sharpe=score["sharpe"], n_obs=len(middle), engine="offline",
                     detail={"cell": "S", "round": 2})
        write_json(SCORES_R2, scores)
        pd.DataFrame(frames).sort_index().to_parquet(DAILY_R2)
        first, second, t = _show(score["sharpe_first_half"]), _show(score["sharpe_second_half"]), _show((ic or {}).get("nonoverlap_t"))
        print(f"{trial} Sharpe {_show(score['sharpe'])} ({first}, {second}) IC t {t} live {live['median']:.0f} turnover {score['turnover']:.1f}", flush=True)
    return 0


def stage_placebo(args) -> int:
    check_rules_r2()
    scores = read_json(SCORES_R2, {})
    eligible = [trial for trial in TRIALS if trial in scores and passes_earlier_clauses(trial, "W", scores[trial])]
    print("reach the placebo clause:", eligible or "none", flush=True)
    if not eligible:
        return 0
    cell, contexts = prepared_cell()
    path = OUT / "selection_placebos_r2.json"
    done = read_json(path, {})
    for trial in eligible:
        if trial in done and not args.force:
            continue
        spec = spec_of(trial)
        out = {}
        for mode in nulls_for(spec):
            sharpes = placebo_sharpes(spec, contexts[trial], mode, start=cell.cell.start, end=cell.cell.end, draws=args.draws)
            out[mode] = {"p": placebo_p_value(scores[trial]["sharpe"], sharpes), "draws": len(sharpes), "median": float(pd.Series(sharpes).median()) if sharpes else None}
            print(f"{trial} {mode:12s} p {out[mode]['p']:.3f} median {_show(out[mode]['median'])}", flush=True)
        done[trial] = out
        write_json(path, done)
    return 0


def stage_gate(args) -> int:
    check_rules_r2()
    scores = read_json(SCORES_R2, {})
    placebos = read_json(OUT / "selection_placebos_r2.json", {})
    daily = pd.read_parquet(DAILY_R2)
    eligible = {name: score for name, score in scores.items() if passes_earlier_clauses(name, "W", score)}
    rows = [{**score, "id": name, "daily": {0: daily[name].dropna()}} for name, score in eligible.items()]
    p_values = {name: {mode: entry["p"] for mode, entry in tests.items()} for name, tests in placebos.items()}
    gate = selection_gate(rows, p_values)
    failed_early = {}
    for name, score in scores.items():
        if name in eligible:
            continue
        if (score.get("live_names") or {}).get("median", 0.0) < min_live_names(name, "W"):
            failed_early[name] = "live_names"
        elif not (score["sharpe"] is not None and score["sharpe"] >= 0.5 and score["sharpe_first_half"] >= 0.4 and score["sharpe_second_half"] >= 0.4):
            failed_early[name] = "sharpe"
        else:
            failed_early[name] = "ic"
    gate["failed_earlier_clauses"] = failed_early
    gate["unscored"] = [trial for trial in TRIALS if trial not in scores]
    write_json(GATE_R2, gate)
    print(json.dumps({key: gate[key] for key in ("survivors", "failed", "failed_earlier_clauses", "unscored")}, indent=1))
    return 0


def stage_pbo(args) -> int:
    from evaluation.pbo import probability_of_backtest_overfitting

    check_rules_r2()
    both = pd.concat([pd.read_parquet(DAILY), pd.read_parquet(DAILY_R2)], axis=1)
    columns = [name for name in (*PBO_COLUMNS, *TRIALS) if name in both.columns]
    window = ("2011-01-01", "2018-12-31")
    matrix = both[columns]
    matrix = matrix[(matrix.index >= window[0]) & (matrix.index <= window[1])].dropna(how="all").fillna(0.0)
    result = probability_of_backtest_overfitting(matrix.to_numpy(dtype=float), blocks=16, periods_per_year=252)
    report = {"pbo": result.get("pbo"), "num_trials": len(columns), "window": "..".join(window), "round_1_columns": len(PBO_COLUMNS), "round_2_columns": len(TRIALS)}
    write_json(PBO_R2, report)
    print(json.dumps(report, indent=1))
    return 0


def ic_by_group(table: pd.DataFrame, label: pd.DataFrame, groups: dict[str, pd.DataFrame | pd.Series], *, start: str, end: str, step: int = 20) -> dict:
    """Mean Spearman IC over every `step`th session, overall and within each group. `groups` maps a name to a ticker->group Series (static) or a
    session x ticker frame of group labels (dynamic)."""
    dates = [date for date in table.index if start <= date <= end][::step]
    rows: dict[str, dict[str, list[float]]] = {name: {} for name in groups}
    rows["year"] = {}
    for date in dates:
        pair = pd.concat([table.loc[date], label.loc[date]], axis=1, keys=["s", "y"]).dropna()
        if len(pair) < 30:
            continue
        rows["year"].setdefault(date[:4], []).append(float(pair["s"].rank().corr(pair["y"].rank())))
        for name, grouping in groups.items():
            membership = grouping.loc[date] if isinstance(grouping, pd.DataFrame) else grouping
            for group, part in pair.groupby(membership.reindex(pair.index)):
                if len(part) >= 12:
                    rows[name].setdefault(str(group), []).append(float(part["s"].rank().corr(part["y"].rank())))
    return {name: {group: {"ic": float(np.mean(values)), "dates": len(values)} for group, values in sorted(by.items())} for name, by in rows.items()}


def cost_variants(context, trial_spec, signal, *, start: str, end: str, split: str) -> dict:
    """Median-phase net Sharpe at today's costs, 2x costs, NAV $25k, and both."""
    base = context.config
    doubled = dataclasses.replace(
        base, equity_fee_bps=base.equity_fee_bps * 2.0, equity_min_fee_usd=base.equity_min_fee_usd * 2.0,
        slippage_bps_by_class={name: value * 2.0 for name, value in base.slippage_bps_by_class.items()},
    )
    out = {}
    for label, config, nav in (("as_is", base, 100_000.0), ("costs_2x", doubled, 100_000.0), ("nav_25k", base, 25_000.0), ("nav_25k_costs_2x", doubled, 25_000.0)):
        values = []
        for offset in range(0, trial_spec.rebalance_every, max(1, trial_spec.rebalance_every // 5)):
            weights = weights_for(trial_spec, context, signal, start=start, end=end, phase_offset=offset)
            result = simulate_target_weights(
                weights, context.market, config, start=start, end=end, nav=nav, sweep_config=context.sweep, rf_dates=context.rf_dates, rf_rates=context.rf_rates,
                carry_fn=context.carry,
            )
            values.append(annual_sharpe(result["strategy_excess"], sessions=context.market.sessions))
        finite = [value for value in values if value is not None]
        out[label] = float(np.median(finite)) if finite else None
    return out


def stage_report(args) -> int:
    check_rules_r2()
    cell, contexts = prepared_cell()
    window = cell.cell
    bars = cell.bars
    dollar_volume = (bars.raw_close * bars.volume).rolling(60, min_periods=30).median().shift(1)
    tercile = dollar_volume.rank(axis=1, pct=True).apply(lambda column: pd.cut(column, [0, 1 / 3, 2 / 3, 1.0], labels=["low", "mid", "high"], include_lowest=True))
    sector = pd.Series(cell.sectors)
    report: dict = {"ic": {}, "costs": {}}
    for name in ("m1", "m2", "m3", "m4", "m5", "w04"):
        table = cell.context.panel.extras.get(name)
        if table is None:
            continue
        report["ic"][name] = ic_by_group(table, cell.label, {"sector": sector, "liquidity": tercile}, start=window.start, end=window.end)
        print(name, "IC by year", {year: round(value["ic"], 4) for year, value in report["ic"][name]["year"].items()}, flush=True)
    for trial in (*SENSITIVITY, *TRIALS):
        if trial in TRIALS:
            spec, context, signal = spec_of(trial), contexts[trial], cell.context.panel.extras[trial]
        else:
            spec = next(item for item in W if item.id == trial)
            context, signal = cell.context, cell.context.panel.extras[trial]
        report["costs"][trial] = cost_variants(context, spec, signal, start=window.start, end=window.end, split=window.split)
        print(trial, report["costs"][trial], flush=True)
    write_json(REPORT_R2, report)
    return 0


def stage_ib_subset(args) -> int:
    from v660_verdict import INSTALLED

    from evaluation.premia_research import build_context
    from portfolio.premia_signals import signal_to_weights, sleeve_signal

    check_rules_r2()
    base = base_config()
    context = build_context(ROOT, base)
    panel = context.panel
    signal = sleeve_signal(INSTALLED, panel)
    crypto = [column for column in signal.columns if panel.asset_class.get(column) == "crypto"]
    ib_signal = signal.copy()
    ib_signal[[column for column in crypto if column not in IB_COINS]] = np.nan
    no_eos = signal.copy()
    no_eos["EOSUSD"] = np.nan  # Coinbase lists EOS-USD as delisted (status "delisted", trading disabled)

    def ib_fee(asset_class, notional, date, config):
        return max(1.75, abs(notional) * 15.0 / 1e4) if asset_class == "crypto" else 0.0

    from evaluation.target_weights_engine import default_fee_usd

    out = {}
    for label, window in (("2014-12..2026-11", ("2014-12-01", "2026-11-02")), ("2023-07..2026-11", ("2023-07-01", "2026-11-02")), ("2025-07..2026-11", ("2025-07-01", "2026-11-02"))):
        for name, table, fee in (
            ("12_coins_coinbase_fees", signal, default_fee_usd), ("11_coins_without_eos_coinbase_fees", no_eos, default_fee_usd),
            ("8_ib_coins_coinbase_fees", ib_signal, default_fee_usd), ("8_ib_coins_ib_fees", ib_signal, ib_fee),
        ):
            weights = signal_to_weights(table, panel, kind=INSTALLED.kind, rebalance_every=INSTALLED.rebalance_every, settings=context.settings, start=window[0], end=window[1])
            result = simulate_target_weights(
                weights, context.market, context.config, start=window[0], end=window[1], sweep_config=context.sweep, rf_dates=context.rf_dates, rf_rates=context.rf_rates,
                carry_fn=context.carry, fee_fn=fee,
            )
            strategy = result["strategy_excess"]
            out.setdefault(label, {})[name] = {"sharpe": annual_sharpe(strategy), "fees_usd": float(result["fees"]), "mean_gross": float(result["gross"].mean())}
            print(label, name, out[label][name], flush=True)
    out["added_after_the_rules_were_hashed"] = "the 11-coins-without-EOS rows: Coinbase's product API says EOS-USD is delisted, found while checking venues. Report only."
    out["note"] = (
        "Diagnostic only. The 12 coins were picked with hindsight and the IB list is from press reports, not IB's own page: BTC, ETH, LTC, BCH (Paxos since 2021), "
        "LINK, XRP, ADA, DOGE (2025-26 additions). XLM, EOS, ETC and ZEC were not found on any IB list."
    )
    write_json(IB_SUBSET, out)
    return 0


def stage_kraken_subset(args) -> int:
    """The installed sleeve on the 11 coins Kraken lists (all but EOS) at Kraken's spot taker fee. Its schedule is disputed between sources (0.25%/0.40%
    maker/taker at the lowest volume tier on one, 0.40%/0.80% on another), so both takers are run. Report only."""
    from v660_verdict import INSTALLED

    from evaluation.premia_research import build_context
    from portfolio.premia_signals import signal_to_weights, sleeve_signal

    base = base_config()
    context = build_context(ROOT, base)
    panel = context.panel
    signal = sleeve_signal(INSTALLED, panel)
    signal["EOSUSD"] = np.nan

    def taker(bps: float):
        return lambda asset_class, notional, date, config: abs(notional) * bps / 1e4 if asset_class == "crypto" else 0.0

    out = {}
    for label, window in (("2014-12..2026-11", ("2014-12-01", "2026-11-02")), ("2023-07..2026-11", ("2023-07-01", "2026-11-02")), ("2025-07..2026-11", ("2025-07-01", "2026-11-02"))):
        weights = signal_to_weights(signal, panel, kind=INSTALLED.kind, rebalance_every=INSTALLED.rebalance_every, settings=context.settings, start=window[0], end=window[1])
        for name, fee in (("kraken_taker_40bps", taker(40.0)), ("kraken_taker_80bps", taker(80.0))):
            result = simulate_target_weights(
                weights, context.market, context.config, start=window[0], end=window[1], sweep_config=context.sweep, rf_dates=context.rf_dates, rf_rates=context.rf_rates,
                carry_fn=context.carry, fee_fn=fee,
            )
            out.setdefault(label, {})[name] = {"sharpe": annual_sharpe(result["strategy_excess"]), "fees_usd": float(result["fees"])}
            print(label, name, out[label][name], flush=True)
    out["note"] = "Diagnostic only, hindsight coins. Coinbase's date-effective schedule on the same 11 coins is in ib_subset.json (11_coins_without_eos_coinbase_fees)."
    write_json(OUT / "kraken_subset.json", out)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="stage", required=True)
    commands.add_parser("rules")
    score = commands.add_parser("score")
    score.add_argument("--only", nargs="*", default=None)
    score.add_argument("--force", action="store_true")
    placebo = commands.add_parser("placebo")
    placebo.add_argument("--draws", type=int, default=100)
    placebo.add_argument("--force", action="store_true")
    for name in ("gate", "pbo", "report", "ib_subset", "kraken_subset"):
        commands.add_parser(name)
    args = parser.parse_args()
    return {"rules": stage_rules, "score": stage_score, "placebo": stage_placebo, "gate": stage_gate, "pbo": stage_pbo, "report": stage_report, "ib_subset": stage_ib_subset, "kraken_subset": stage_kraken_subset}[args.stage](args)


if __name__ == "__main__":
    raise SystemExit(main())
