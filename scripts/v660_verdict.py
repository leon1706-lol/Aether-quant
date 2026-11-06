"""What V6.6.0's search can and can't say, once selection has ended it. Nothing here selects: no row enters a ledger as a candidate.

    python scripts/v660_verdict.py crypto1   # R-CRYPTO1: the installed rule on never-read coins, delisted included. Reported always, by rule.
    python scripts/v660_verdict.py report    # per trial: alpha t, the alpha sizes excluded, zero-cost Sharpe, known-factor alpha
    python scripts/v660_verdict.py breaks    # how far the coins with a spliced price (crypto_price_breaks.json) moved the crypto numbers
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v660_research import check_rules, load_cells  # noqa: E402
from v660_trials import ALL_SPECS, cell_of  # noqa: E402

from evaluation.alpha_proof import alpha_regression, benchmark_daily_returns, to_sessions  # noqa: E402
from evaluation.power_analysis import excluded_alpha_sharpe  # noqa: E402
from evaluation.premia_research import annual_sharpe, max_drawdown, weights_for  # noqa: E402
from evaluation.research_cells import CELLS, freeze_digest_of, write_freeze  # noqa: E402
from evaluation.target_weights_engine import simulate_target_weights  # noqa: E402
from evaluation.wide_context import crypto_cell  # noqa: E402
from portfolio.premia_signals import SleeveSpec, TS, signal_to_weights, sleeve_signal  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v660"
FREEZE = OUT / "freeze_crypto1.json"
INSTALLED = SleeveSpec("t3_crypto_trend_blend", "installed", TS, "crypto_trend", ("crypto",), 5, {"lookback_a": 20, "lookback_b": 60, "lookback_c": 120})
BENCHMARK_ASSETS = [
    {"ticker": "SPY", "security_type": "equity", "data_path": "data/equity/usa/daily/spy.zip"},
    {"ticker": "AGG", "security_type": "equity", "data_path": "data/equity/usa/daily/agg.zip"},
    {"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"},
]


def alpha_of(series: pd.Series, *, data_dir: str) -> dict:
    """Alpha against SPY, AGG and BTC on a session basis, with the regression's own span, so a short join can't pass unnoticed."""
    config = {"phase1": {"universe": {"assets": BENCHMARK_ASSETS}}}
    bench = benchmark_daily_returns(ROOT, config, ("SPY", "AGG", "BTCUSD"), start=str(series.index.min()), end=str(series.index.max()), data_dir=data_dir, required=True)
    return alpha_regression(to_sessions(series, bench.index), bench)


def report_crypto1() -> dict:
    """The rule itself is frozen since V6.5.0, so the freeze here only opens the held-out coins for this one read."""
    check_rules()
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if not FREEZE.exists():
        write_freeze(FREEZE, {"read": "R-CRYPTO1", "rule": dataclasses.asdict(INSTALLED), "rules_sha": hashlib.sha256((OUT / "rules.json").read_bytes()).hexdigest()})
    cell = crypto_cell(ROOT, base, "CV", freeze_path=FREEZE, freeze_digest=freeze_digest_of(FREEZE), side="B")
    context, panel, allowed = cell.context, cell.context.panel, cell.member
    signal = sleeve_signal(INSTALLED, panel).where(allowed.reindex(index=panel.known.index, columns=panel.known.columns, fill_value=False))
    start, end = "2018-01-01", CELLS["CV"].end

    def weights_on(table: pd.DataFrame) -> dict:
        return signal_to_weights(table, panel, kind=TS, rebalance_every=INSTALLED.rebalance_every, settings=context.settings, start=start, end=end)

    weights = weights_on(signal)
    result = context.simulate(weights, start, end)
    strategy = result["strategy_excess"]
    manifest = json.loads((ROOT / "data_crypto_wide" / "crypto_wide_manifest.json").read_text(encoding="utf-8"))
    stopped = {entry["ticker"] for entry in manifest["coins"].values() if entry["last"] < "2026-09-01"}
    survivors_only = signal.drop(columns=[column for column in signal.columns if column in stopped]).reindex(columns=signal.columns)
    survivors_result = context.simulate(weights_on(survivors_only), start, end)
    total_return = float((1.0 + result["strategy"]).prod() - 1.0)
    survivors_return = float((1.0 + survivors_result["strategy"]).prod() - 1.0)
    held = sorted({ticker for row in weights.values() for ticker in row})

    def on_binance_fees() -> float | None:
        flat = simulate_target_weights(
            weights, context.market, context.config, start=start, end=end, sweep_config=context.sweep, rf_dates=context.rf_dates, rf_rates=context.rf_rates,
            carry_fn=context.carry, fee_fn=lambda asset_class, notional, date, config: abs(notional) * 10.0 / 1e4 if asset_class == "crypto" else 0.0,
        )
        return annual_sharpe(flat["strategy_excess"])

    report = {
        "rule": "R-CRYPTO1", "window": [start, end], "side": "B", "names_ever_held": len(held), "of_which_stopped_trading": len(set(held) & stopped),
        "no_bar_exits": len(result["no_bar_exits"]), "sharpe": annual_sharpe(strategy), "sharpe_2018_2020": annual_sharpe(strategy[strategy.index < "2021-01-01"]),
        "sharpe_2021_2023": annual_sharpe(strategy[(strategy.index >= "2021-01-01") & (strategy.index < "2024-01-01")]), "sharpe_2024_on": annual_sharpe(strategy[strategy.index >= "2024-01-01"]),
        "max_drawdown": max_drawdown(strategy), "total_return": total_return, "survivors_only_total_return": survivors_return,
        "survivors_only_sharpe": annual_sharpe(survivors_result["strategy_excess"]), "alpha": alpha_of(strategy, data_dir="data_crypto_wide"),
        "mean_gross": float(result["gross"].mean()), "sharpe_on_binance_fees_not_gating": on_binance_fees(),
    }
    report["control_same_rule_same_path"] = control_on_side_a(base)
    report["side_b_on_the_control_window"] = annual_sharpe(strategy[(strategy.index >= "2018-01-01") & (strategy.index <= CELLS["CS"].end)])
    (OUT / "r_crypto1.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8", newline="\n")
    return report


def control_on_side_a(base: dict) -> dict:
    """The same rule and path on side A's liquid coins, on the selection cell's window: if this looks like V6.5.0's result and side B doesn't, the difference is
    the coins and not the path. Side A includes the 12 coins the installed sleeve was picked on, so this half is not unread."""
    cell = crypto_cell(ROOT, base, "CS", side="A")
    panel, context = cell.context.panel, cell.context
    signal = sleeve_signal(INSTALLED, panel).where(cell.member.reindex(index=panel.known.index, columns=panel.known.columns, fill_value=False))
    weights = signal_to_weights(signal, panel, kind=TS, rebalance_every=INSTALLED.rebalance_every, settings=context.settings, start=cell.cell.start, end=cell.cell.end)
    strategy = context.simulate(weights, cell.cell.start, cell.cell.end)["strategy_excess"]
    return {"cell": "CS", "side": "A", "window": [cell.cell.start, cell.cell.end], "sharpe": annual_sharpe(strategy), "names_ever_held": len({ticker for row in weights.values() for ticker in row})}


def report_track_table() -> dict:
    """Per trial, on its selection cell: alpha t and what that excludes, Sharpe with no costs (were costs the reason?), and alpha against known factors for the best."""
    from evaluation.factor_spanning import factor_alpha

    check_rules()
    scores = json.loads((OUT / "selection_scores.json").read_text(encoding="utf-8"))
    daily = pd.read_parquet(OUT / "selection_daily.parquet")
    factors = pd.read_parquet(ROOT / "data_wide" / "reference" / "factors_daily.parquet")
    specs = [spec for spec in ALL_SPECS if spec.id in scores]
    cells = load_cells(specs)
    rows = {}
    for spec in specs:
        cell = cells[cell_of(spec)]
        data_dir = "data_crypto_wide" if cell.cell.universe == "crypto" else "data_wide"
        series = daily[spec.id].dropna()
        alpha = alpha_of(series, data_dir=data_dir)
        years = (pd.Timestamp(cell.cell.end) - pd.Timestamp(cell.cell.start)).days / 365.25
        signal = sleeve_signal(spec, cell.context.panel)
        no_cost_config = dataclasses.replace(cell.context.config, equity_fee_bps=0.0, equity_min_fee_usd=0.0, slippage_bps_by_class={}, financing_enabled=False)
        weights = weights_for(spec, cell.context, signal, start=cell.cell.start, end=cell.cell.end, phase_offset=0)
        gross = simulate_target_weights(
            weights, cell.context.market, no_cost_config, start=cell.cell.start, end=cell.cell.end, sweep_config=cell.context.sweep, rf_dates=cell.context.rf_dates,
            rf_rates=cell.context.rf_rates, carry_fn=cell.context.carry, fee_fn=lambda asset_class, notional, date, config: 0.0,
        )
        score = scores[spec.id]
        rows[spec.id] = {
            "track": spec.track, "cell": cell.cell.name, "years": round(years, 2), "sharpe_net": score.get("sharpe"), "first_half": score.get("sharpe_first_half"), "second_half": score.get("sharpe_second_half"),
            "sharpe_no_costs_one_phase": annual_sharpe(gross["strategy_excess"], sessions=cell.context.sessions_for(spec)), "turnover": score.get("turnover"), "ic_mean": (score.get("ic") or {}).get("mean_ic"),
            "ic_nonoverlap_t": (score.get("ic") or {}).get("nonoverlap_t"), "alpha_annual": alpha.get("alpha_annual"), "alpha_t": alpha.get("t_hac"), "alpha_n": alpha.get("n"),
            "excluded_alpha_sharpe_95": excluded_alpha_sharpe(float(alpha["t_hac"]), years) if alpha.get("t_hac") is not None else None,
        }
        if cell.cell.universe == "equity":
            rows[spec.id]["known_factor_alpha"] = factor_alpha(series, factors)
        print(spec.id, json.dumps({key: rows[spec.id][key] for key in ("sharpe_net", "sharpe_no_costs_one_phase", "alpha_t", "excluded_alpha_sharpe_95")}, default=str), flush=True)
    by_track = {}
    for track in sorted({row["track"] for row in rows.values()}):
        members = {name: row for name, row in rows.items() if row["track"] == track}
        bounds = [row["excluded_alpha_sharpe_95"] for row in members.values() if row["excluded_alpha_sharpe_95"] is not None]
        best = max(members, key=lambda name: members[name]["alpha_t"] if members[name]["alpha_t"] is not None else -99.0)
        by_track[track] = {
            "trials": len(members), "best_by_alpha_t": best, "best_alpha_t": members[best]["alpha_t"],
            "excluded_alpha_sharpe_95_at_best": members[best]["excluded_alpha_sharpe_95"], "median_excluded": float(pd.Series(bounds).median()) if bounds else None,
        }
    report = {"trials": rows, "by_track": by_track, "note": "Selection cell only: side A names, the free windows. The held-out cells were never read, so an excluded size holds for this cell."}
    (OUT / "verdict_table.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8", newline="\n")
    return report


def report_breaks() -> dict:
    """Found after selection and R-CRYPTO1 were read, so this can't rescue anything: it only says whether the defect could have changed a clause."""
    from v660_research import _signal_for

    from evaluation.premia_research import score_sleeve

    check_rules()
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    names = set(json.loads((OUT / "crypto_price_breaks.json").read_text(encoding="utf-8"))["breaks"])
    recorded = json.loads((OUT / "selection_scores.json").read_text(encoding="utf-8"))
    specs = [spec for spec in ALL_SPECS if spec.track == "C"]
    cell = load_cells(specs)["CS"]
    report = {"coins": sorted(names), "trials": {}}
    for spec in specs:
        signal = _signal_for(spec, cell)
        signal[[column for column in signal.columns if column in names]] = float("nan")
        score = score_sleeve(spec, cell.context, start=cell.cell.start, split=cell.cell.split, end=cell.cell.end, signal=signal)
        score.pop("daily")
        report["trials"][spec.id] = {
            "recorded": [recorded[spec.id][key] for key in ("sharpe", "sharpe_first_half", "sharpe_second_half")],
            "without_those_coins": [score[key] for key in ("sharpe", "sharpe_first_half", "sharpe_second_half")],
        }
        print(spec.id, report["trials"][spec.id], flush=True)
    held = crypto_cell(ROOT, base, "CV", freeze_path=FREEZE, freeze_digest=freeze_digest_of(FREEZE), side="B")
    panel, context = held.context.panel, held.context
    signal = sleeve_signal(INSTALLED, panel).where(held.member.reindex(index=panel.known.index, columns=panel.known.columns, fill_value=False))
    signal[[column for column in signal.columns if column in names]] = float("nan")
    start, end = "2018-01-01", CELLS["CV"].end
    weights = signal_to_weights(signal, panel, kind=TS, rebalance_every=INSTALLED.rebalance_every, settings=context.settings, start=start, end=end)
    report["r_crypto1_without_those_coins"] = annual_sharpe(context.simulate(weights, start, end)["strategy_excess"])
    report["r_crypto1_recorded"] = json.loads((OUT / "r_crypto1.json").read_text(encoding="utf-8"))["sharpe"]
    (OUT / "crypto_breaks_effect.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["crypto1", "report", "breaks"])
    args = parser.parse_args()
    result = report_crypto1() if args.stage == "crypto1" else report_breaks() if args.stage == "breaks" else report_track_table()["by_track"]
    print(json.dumps(result, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
