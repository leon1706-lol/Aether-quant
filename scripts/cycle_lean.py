"""R-BLEND1 in Lean (V6.6.1): the blended weight file runs as the engine says it does, and a blend at share 1.0 is the installed book, fill for fill.

These runs are plumbing, never evidence: they read free cells only, and r03 failed its round. They count in nothing.

    python scripts/cycle_lean.py r03                       # on the training Codespace: r03's weights on cell S (equity_cell needs the RAM)
    python scripts/cycle_lean.py make                      # the run configs
    python scripts/cycle_lean.py verdict <bl1 run> <bl2 run>
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "ml" / "evaluation" / "v661"
WEIGHTS = OUT / "weights"
R03_FILE = WEIGHTS / "r03_s.csv"
PIN = "backtests/2026-11-04_18-10-49"
PIN_FILLS = 1012
PINNED_SHA = "57240be0c0486c8ce56fa238c80450a2d26507540482a23b353d139fbb911690"
WINDOW = ("2015-01-02", "2018-12-31")
HANDOVER_START = "2016-01-04"
GLIDE_SESSIONS = 252


def stage_r03() -> int:
    """r03 as it was scored: the rank mean of asset growth, accruals and quality, top 5 by sector, every 20 sessions."""
    from evaluation.premia_research import weights_for
    from evaluation.wide_context import SECTORS, equity_cell
    from portfolio.premia_signals import XS, SleeveSpec
    from portfolio.target_weights import write_weight_file
    from portfolio.wide_signals import rank_mean

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cell = equity_cell(ROOT, base, "S")
    panel = cell.context.panel
    table = rank_mean([panel.extras[name] for name in ("w03", "w04", "w06")], minimum=3).where(cell.member)
    panel.extras["r03"] = table
    spec = SleeveSpec("r03", "W", XS, "external_score", SECTORS, 20, {"table": "r03", "top_k": 5})
    rows = weights_for(spec, cell.context, table, start=WINDOW[0], end=WINDOW[1], phase_offset=0)
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    print(write_weight_file(rows, R03_FILE), len(rows))
    return 0


def blended_identity(path: Path) -> dict:
    """A blend at share 1.0 of the installed file, written the way the file is written. It must hash to the same bytes: nothing about blending may touch a row."""
    from portfolio.generation_blend import blend_generation_rows
    from portfolio.target_weights import FLAT_TICKER, load_weight_file, write_weight_file

    rows = load_weight_file(ROOT / "ml" / "target_weights.csv", PINNED_SHA)
    blended = {date: blend_generation_rows({"g": {ticker: weight for ticker, weight in row.items() if ticker != FLAT_TICKER}}, {"g": 1.0}) for date, row in rows.items()}
    return {"rows": len(blended), "sha256": write_weight_file(blended, path)}


def frozen_rule_rows(panel, *, start: str, end: str) -> dict:
    """`t3_crypto_trend_blend`, from its frozen definition in `ml/forward/candidates.json`, on this panel's crypto."""
    from portfolio.premia_signals import ResearchPanel, SleeveSpec, known_closes, signal_to_weights, sleeve_signal

    candidates = json.loads((ROOT / "ml" / "forward" / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    definition = next(entry for entry in candidates if entry["id"] == "t3_crypto_trend_blend")
    spec = SleeveSpec(definition["id"], "forward", definition["kind"], definition["family"], tuple(definition["universe"]), int(definition["rebalance_every"]), dict(definition["params"]))
    known = known_closes(panel.dates, panel.tickers, panel.closes, panel.asset_class, panel.sessions)
    research = ResearchPanel(known, panel.asset_class, {}, {})
    return signal_to_weights(sleeve_signal(spec, research), research, kind=spec.kind, rebalance_every=spec.rebalance_every, start=start, end=end)


def stage_make() -> int:
    from v650_instrument import target_path_config
    from v660_lean import WIDE_PATH, write_run

    from build_wide_root import wide_config
    from evaluation.generation_ledger import replay_handover
    from evaluation.target_weights_engine import load_market_panel
    from portfolio.generation_blend import GlidePolicy
    from portfolio.target_weights import FLAT_TICKER, load_weight_file, write_weight_file

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "data_wide" / "wide_manifest.json").read_text(encoding="utf-8"))
    identity = blended_identity(WEIGHTS / "identity.csv")
    if identity["sha256"] != PINNED_SHA:
        raise SystemExit(f"a blend at share 1.0 changed the file: {identity['sha256']}")

    def clean(rows: dict) -> dict:
        return {date: {ticker: weight for ticker, weight in row.items() if ticker != FLAT_TICKER} for date, row in rows.items()}

    r03 = clean(load_weight_file(R03_FILE))
    held = {ticker for row in r03.values() for ticker in row}
    universe = wide_config(base, manifest, tickers=held, keep_project_crypto=True)
    panel = load_market_panel(ROOT, universe, data_dir="data_wide")
    sessions = sorted(date for date in panel.sessions if WINDOW[0] <= date <= WINDOW[1])
    # The installed file starts in 2023, so the frozen rule writes its own rows here: an incumbent with no rows would blend nothing with the successor.
    t3 = frozen_rule_rows(panel, start=WINDOW[0], end=WINDOW[1])
    if not any(t3.values()):
        raise SystemExit("the incumbent holds nothing in this window: the run would not blend two generations")
    replay = replay_handover({"t3": t3, "r03": r03}, sessions, incumbent="t3", successor="r03", start=HANDOVER_START, policy=GlidePolicy(glide_sessions=GLIDE_SESSIONS))
    sha = write_weight_file(replay["rows"], WEIGHTS / "v661_bl1.csv")
    config = target_path_config(universe, weights_path="ml/evaluation/v661/weights/v661_bl1.csv", weights_sha256=sha, window=WINDOW, locks=False)
    config["phase_v2"]["target_weights"].update(WIDE_PATH)
    runs = {"v661_bl1": {**write_run("v661_bl1", config, data_root="data_wide"), "weights_sha": sha, "rows": len(replay["rows"]), "role": "plumbing"}}
    gated = copy.deepcopy(base)
    gated["runtime"]["lean_window_override"] = {"start": "2023-07-01", "end": "2026-11-02"}
    runs["v661_bl2"] = {**write_run("v661_bl2", gated), "role": "plumbing", "is": f"equals {PIN}, order for order", "identity": identity}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bl_manifest.json").write_text(json.dumps({**runs, "shares": replay["shares"]}, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(runs, indent=1))
    return 0


def stage_make3() -> int:
    """R-BLEND2's run: three generations at once under the dynamic mode, each one's evidence from its own simulated returns. On the training Codespace: the panel holds a few hundred names."""
    from v650_instrument import target_path_config
    from v660_lean import WIDE_PATH, write_run

    from build_wide_root import wide_config
    from evaluation.generation_ledger import replay_dynamic
    from evaluation.premia_research import weights_for
    from evaluation.target_weights_engine import load_market_panel, simulate_target_weights
    from evaluation.wide_context import SECTORS, equity_cell, path_config
    from portfolio.financing import load_rate_series
    from portfolio.generation_blend import GlidePolicy, resolve_glide_policy
    from portfolio.premia_signals import POOLED, SleeveSpec
    from portfolio.target_weights import FLAT_TICKER, load_weight_file, write_weight_file

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "data_wide" / "wide_manifest.json").read_text(encoding="utf-8"))
    cell = equity_cell(ROOT, base, "S")
    table = (cell.features["accruals_ttm"] * -1.0).where(cell.member)
    cell.context.panel.extras["k09"] = table
    spec = SleeveSpec("k09", "W", POOLED, "external_score", SECTORS, 20, {"table": "k09"})
    k09 = weights_for(spec, cell.context, table, start=WINDOW[0], end=WINDOW[1], phase_offset=0)
    r03 = {date: {ticker: weight for ticker, weight in row.items() if ticker != FLAT_TICKER} for date, row in load_weight_file(R03_FILE).items()}
    held = {ticker for rows in (r03, k09) for row in rows.values() for ticker in row}
    universe = wide_config(base, manifest, tickers=held, keep_project_crypto=True)
    panel = load_market_panel(ROOT, universe, data_dir="data_wide")
    t3 = frozen_rule_rows(panel, start=WINDOW[0], end=WINDOW[1])
    sessions = sorted(date for date in panel.sessions if WINDOW[0] <= date <= WINDOW[1])
    target = path_config(base)
    rf_dates, rf_rates = load_rate_series(ROOT / "data_wide" / "alternative" / "interest-rate" / "usa" / "interest-rate.csv")
    rows_by_generation = {"t3": t3, "r03": r03, "k09": k09}
    returns = {}
    for name, rows in rows_by_generation.items():
        result = simulate_target_weights(rows, panel, target, start=WINDOW[0], end=WINDOW[1], sweep_config=base["phase_v2"]["cash_sweep"], rf_dates=rf_dates, rf_rates=rf_rates, carry_fn=lambda ticker, date: 0.0)
        returns[name] = {str(date): float(value) for date, value in result["strategy_excess"].items()}
    raw = json.loads((ROOT / "ml" / "generations" / "policy.json").read_text(encoding="utf-8")).get("glide") or {}
    policy = resolve_glide_policy(raw)
    if policy.mode != "dynamic":
        policy = GlidePolicy(mode="dynamic", half_life_sessions=63, prior_sessions=252.0, blend_every=int(raw.get("blend_every", 21)))
    replay = replay_dynamic(
        rows_by_generation, returns, sessions, born={"t3": WINDOW[0], "r03": "2016-01-04", "k09": "2017-01-03"}, priors={"t3": 0.5, "r03": 0.5, "k09": 0.5}, policy=policy, initial={"t3": 1.0},
    )
    held_three = [date for date, shares in replay["shares"].items() if sum(value >= policy.retire_share for value in shares.values()) >= 3]
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    sha = write_weight_file(replay["rows"], WEIGHTS / "v661_bl3.csv")
    final_universe = wide_config(base, manifest, tickers={ticker for row in replay["rows"].values() for ticker in row}, keep_project_crypto=True)
    config = target_path_config(final_universe, weights_path="ml/evaluation/v661/weights/v661_bl3.csv", weights_sha256=sha, window=WINDOW, locks=False)
    config["phase_v2"]["target_weights"].update(WIDE_PATH)
    run = {**write_run("v661_bl3", config, data_root="data_wide"), "weights_sha": sha, "rows": len(replay["rows"]), "role": "plumbing", "rows_with_three_holders": len(held_three), "first_with_three": min(held_three) if held_three else None}
    used = {"half_life_sessions": policy.half_life_sessions, "prior_sessions": policy.prior_sessions, "blend_every": policy.blend_every}
    (OUT / "bl3_manifest.json").write_text(json.dumps({"run": run, "policy": used, "shares": replay["shares"], "scores": replay["scores"]}, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(run, indent=1))
    return 0 if held_three else 1


def r_blend2(engine: dict, rows_with_three_holders: int) -> dict:
    """R-BLEND2: R-BLEND1's engine clauses on a run where at least three generations held capital at once."""
    fees = engine.get("fees_within_2pct")
    clauses = {
        "correlation_099": engine.get("correlation") is not None and float(engine["correlation"]) >= 0.99, "annual_gap_100bps": engine.get("annual_gap_bps") is not None and float(engine["annual_gap_bps"]) <= 100.0,
        "fees_within_2pct": fees is True, "three_generations_held_at_once": int(rows_with_three_holders) > 0,
    }
    return {"rule": "R-BLEND2", "passed": all(clauses.values()), "clauses": clauses, "engine": engine}


def stage_verdict3(bl3: str) -> int:
    from v660_lean import compare

    manifest = json.loads((OUT / "bl3_manifest.json").read_text(encoding="utf-8"))
    report = r_blend2(compare("v661_bl3", Path(bl3)), int(manifest["run"]["rows_with_three_holders"]))
    (OUT / "r_blend2.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=1, default=str))
    return 0 if report["passed"] else 1


def r_blend1(engine: dict, orders: dict, identity_sha: str) -> dict:
    """R-BLEND1's clauses. A missing figure fails."""
    fees = engine.get("fees_within_2pct")
    clauses = {
        "correlation_099": engine.get("correlation") is not None and float(engine["correlation"]) >= 0.99, "annual_gap_100bps": engine.get("annual_gap_bps") is not None and float(engine["annual_gap_bps"]) <= 100.0,
        "fees_within_2pct": fees is True, "identity_sha": identity_sha == PINNED_SHA, "fills_equal_the_pin": orders.get("equal") is True and orders.get("fills_first") == PIN_FILLS,
    }
    return {"rule": "R-BLEND1", "passed": all(clauses.values()), "clauses": clauses, "engine": engine, "orders": orders}


def stage_verdict(bl1: str, bl2: str) -> int:
    from v660_lean import compare, compare_orders

    identity = hashlib.sha256((WEIGHTS / "identity.csv").read_bytes()).hexdigest()
    report = r_blend1(compare("v661_bl1", Path(bl1)), compare_orders(Path(bl2), Path(PIN)), identity)
    (OUT / "r_blend1.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=1, default=str))
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="stage", required=True)
    commands.add_parser("r03")
    commands.add_parser("make")
    verdict = commands.add_parser("verdict")
    verdict.add_argument("bl1")
    verdict.add_argument("bl2")
    commands.add_parser("make3")
    verdict3 = commands.add_parser("verdict3")
    verdict3.add_argument("bl3")
    args = parser.parse_args()
    if args.stage == "r03":
        return stage_r03()
    if args.stage == "make":
        return stage_make()
    if args.stage == "make3":
        return stage_make3()
    if args.stage == "verdict3":
        return stage_verdict3(args.bl3)
    return stage_verdict(args.bl1, args.bl2)


if __name__ == "__main__":
    raise SystemExit(main())
