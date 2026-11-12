"""Build the dashboard's demo data (V6.6.5, #344): every file `monitoring/api_server.py` reads, from `aq hello`'s run of
the shipped rule on the bundled sample. Deterministic, so a rebuild reproduces the tracked files byte for byte.

The demo is what `docker run ... aether-quant-dashboard` shows: `AQ_DASHBOARD_ROOT=monitoring/demo AQ_DASHBOARD_DEMO=1`.
It is labelled demo data on every page; nothing in it comes from a broker, a model or a Lean run.

    python scripts/build_dashboard_demo.py            # write monitoring/demo/
    python scripts/build_dashboard_demo.py --out DIR  # write elsewhere (the test compares the two)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aether_quant import samples  # noqa: E402
from audit.hash_chain import GENESIS_HASH, compute_entry_hash  # noqa: E402
from evaluation.backtest_api import backtest, summary_statistics  # noqa: E402
from evaluation.hello_world import DEADBAND, HELLO_RULE, PERIODS_PER_YEAR, rule_weights, run_hello  # noqa: E402
from execution.cost_models import coinbase_model  # noqa: E402
from topology.market_topology import build_market_topology  # noqa: E402

DEFAULT_OUT = ROOT / "monitoring" / "demo"
NAV = 100_000.0
BANNER = "DEMO DATA: the shipped rule on the bundled sample (aq hello). No broker, no model, no live orders."


def _round(value, digits: int = 6):
    if isinstance(value, float):
        return round(value, digits) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _round(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [_round(item, digits) for item in value]
    return value


def _json(payload) -> str:
    return json.dumps(_round(payload), indent=1, sort_keys=True, allow_nan=False) + "\n"


def _csv(rows: list[dict], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: (f"{value:.6f}" if isinstance(value, float) else value) for key, value in row.items()})
    return buffer.getvalue()


def build(out: Path) -> dict[str, str]:
    """{relative path: text} of every demo file, also written under `out`."""
    closes = samples.load_sample_prices()
    report = run_hello(closes, data_source="bundled sample (demo)")
    start, end = report.start, report.end
    window = closes.loc[start:end]
    weights = rule_weights(closes, start=start, end=end)
    result = backtest(weights.reindex(window.index), window, fill="close", cost_model=coinbase_model(end), periods_per_year=PERIODS_PER_YEAR,
                      min_weight_change=DEADBAND, initial_nav=NAV)
    btc = window["BTCUSD"] / window["BTCUSD"].iloc[0]
    nav = result.nav
    held = result.weights.iloc[-1]
    last = window.iloc[-1]
    stats = result.stats()
    returns = window.pct_change(fill_method=None)

    positions = [
        {"symbol": ticker, "quantity": round(float(held[ticker]) * float(nav.iloc[-1]) / float(last[ticker]), 8), "weight": round(float(held[ticker]), 6)}
        for ticker in window.columns if abs(float(held[ticker])) > 1e-9
    ]
    decision = weights.dropna(how="all").iloc[-1]
    signals = {
        ticker: {
            "ticker": ticker, "symbol": ticker, "security_type": "crypto", "trading_eligible": True,
            "signal": "buy" if float(decision[ticker]) > 0 else "hold", "target_weight": round(float(decision[ticker]), 6),
            "reason": "trend votes over 20/60/120 sessions" if float(decision[ticker]) > 0 else "no positive trend vote",
            "execution_note": "demo: no order is placed",
        }
        for ticker in window.columns
    }
    heatmap = []
    asset_rows = []
    for ticker in window.columns:
        coin = returns[ticker].dropna()
        contribution = (result.weights[ticker].shift(1) * returns[ticker]).dropna()
        coin_stats = summary_statistics(coin, periods_per_year=PERIODS_PER_YEAR)
        exposure = float((result.weights[ticker] > 1e-9).mean())
        trades = int((result.weights[ticker].diff().abs() > 1e-6).sum())
        entry = {
            "ticker": ticker, "strategy_return": float(contribution.sum()), "excess_return": float(contribution.sum() - coin.sum()),
            "sharpe": coin_stats["sharpe_ratio"], "max_drawdown": -coin_stats["max_drawdown"], "exposure_rate": exposure, "trade_count": trades,
            "signal_bias": "positive" if float(decision[ticker]) > 0 else "neutral",
        }
        heatmap.append(entry)
        asset_rows.append(entry)

    drawdown = 1.0 - nav / nav.cummax()
    state = {
        "project": "Aether Quant", "mode": "demo", "updated_at": f"{end}T00:00:00Z",
        "insight": f"Demo: {HELLO_RULE['id']} on 11 coins, {start} to {end}. Sharpe {stats['sharpe_ratio']:.2f} without T-bill carry; no verified edge.",
        "portfolio": {"cash": float(nav.iloc[-1] * (1.0 - held.sum())), "total_portfolio_value": float(nav.iloc[-1]), "invested_positions": len(positions)},
        "positions": positions,
        "signals": signals,
        "risk": {"trade_lock_active": False, "trade_lock_reason": "", "daily_drawdown": float(drawdown.iloc[-1] - drawdown.iloc[-2]) if len(drawdown) > 1 else 0.0,
                 "total_drawdown": float(drawdown.iloc[-1]), "max_daily_drawdown_pct": 0.05, "max_total_drawdown_pct": 0.15, "max_position_weight": 0.05,
                 "max_leverage": 1.0},
        "dashboard": {
            "scorecards": [
                {"key": "nav", "label": "Demo NAV", "value": float(nav.iloc[-1]), "format": "currency"},
                {"key": "cagr", "label": "CAGR", "value": stats["cagr"], "format": "percent"},
                {"key": "sharpe", "label": "Sharpe (no T-bill)", "value": stats["sharpe_ratio"], "format": "number"},
                {"key": "max_drawdown", "label": "Max drawdown", "value": stats["max_drawdown"], "format": "percent"},
                {"key": "pbo", "label": "PBO (8 variants)", "value": float(report.pbo or 0.0), "format": "number"},
                {"key": "gross", "label": "Gross exposure", "value": float(held.abs().sum()), "format": "percent"},
            ],
            "asset_heatmap": heatmap,
            "strategy_snapshot": {
                "rows": int(len(nav)), "exposure_rate": float((result.weights.abs().sum(axis=1) > 1e-9).mean()), "trade_count": int((result.turnover > 0).sum()),
                "turnover": stats["turnover_annual"],
                "strategy": {"total_return": stats["total_return"], "annualized_return": stats["cagr"], "annualized_volatility": stats["annual_volatility"],
                             "sharpe": stats["sharpe_ratio"], "max_drawdown": -stats["max_drawdown"]},
                "buy_and_hold": {"total_return": float(btc.iloc[-1] - 1.0), "annualized_return": report.btc_buy_hold.cagr,
                                 "annualized_volatility": report.btc_buy_hold.volatility, "sharpe": report.btc_buy_hold.sharpe, "max_drawdown": -report.btc_buy_hold.max_drawdown},
                "excess_return_vs_buy_and_hold": float(stats["total_return"] - (btc.iloc[-1] - 1.0)),
            },
            "runtime_mode": "demo", "simulated_mode": True, "visualization_stage": "demo",
        },
        "observation": {"mode": "demo", "allow_live_orders": False, "is_observation_mode": True, "visually_distinct_banner": BANNER,
                        "count_observations": int(len(nav)), "simulated_sharpe": stats["sharpe_ratio"], "simulated_max_drawdown": -stats["max_drawdown"],
                        "simulated_equity": float(nav.iloc[-1]), "simulated_exposure": float(held.abs().sum()), "simulated_turnover": stats["turnover_annual"]},
        "kill_switch": {"tripped": False, "severity": "none", "triggers": [], "reason": "demo data: the kill switch is not evaluated", "recommended_action": "none",
                        "observed": {}, "thresholds": {}},
        "reconciliation": {"status": "not_applicable", "reason": "demo data: there is no broker to reconcile against"},
    }

    corr_window = returns.iloc[-120:]
    topology = build_market_topology({ticker: [float(v) for v in corr_window[ticker].fillna(0.0)] for ticker in window.columns}).to_dict()
    scene_nodes = [{"id": "portfolio", "label": "Book", "kind": "portfolio", "x": 0.0, "y": 0.0, "z": 0.0, "intensity": float(held.abs().sum()), "value": float(nav.iloc[-1])}]
    scene_links = []
    for node in topology.get("nodes", []):
        ticker = node["symbol"]
        scene_nodes.append({"id": ticker, "label": ticker, "kind": "asset", "x": float(node["x"]), "y": float(node["y"]), "z": float(node["z"]),
                            "intensity": float(abs(held.get(ticker, 0.0)) / max(float(held.abs().max()), 1e-9)), "value": float(held.get(ticker, 0.0)),
                            "detail": signals[ticker]["reason"]})
        scene_links.append({"source": "portfolio", "target": ticker, "strength": float(abs(held.get(ticker, 0.0)))})
    scene = {"layout": "topology", "nodes": scene_nodes, "links": scene_links, "dimensions": topology.get("dimensions") or {"width": 1, "height": 1, "depth": 1}}

    weekly = nav.iloc[::7]
    equity_rows = [
        {"date": day, "ticker": "SLEEVE", "split": "demo", "probability_up": 0.5, "position": float(result.weights.loc[day].abs().sum()),
         "strategy_return": float(result.returns.loc[day]), "baseline_return": float(btc.pct_change().fillna(0.0).loc[day]),
         "cumulative_strategy": float(nav.loc[day] / NAV), "cumulative_baseline": float(btc.loc[day]), "strategy_drawdown": -float(drawdown.loc[day]),
         "baseline_drawdown": -float((1.0 - btc / btc.cummax()).loc[day])}
        for day in weekly.index
    ]
    observation_rows = [
        {"bar_index": index, "equity": float(nav.loc[day]), "cash": float(nav.loc[day] * (1.0 - result.weights.loc[day].sum())),
         "exposure": float(result.weights.loc[day].abs().sum()), "drawdown": float(drawdown.loc[day])}
        for index, day in enumerate(weekly.index)
    ]
    metrics = {"project": "Aether Quant", "phase": "demo", "mode": "demo", "updated_at": f"{end}T00:00:00Z", "portfolio_value": float(nav.iloc[-1]),
               "cash": state["portfolio"]["cash"], "holdings_value": float(nav.iloc[-1] * held.sum()), "invested_positions": len(positions),
               "active_signals": int(sum(1 for s in signals.values() if s["signal"] == "buy")), "total_drawdown": float(drawdown.iloc[-1]),
               "trade_lock_active": False, "runtime_mode": "demo", "allow_live_orders": False}

    events, prev = [], GENESIS_HASH
    for index, (event_type, payload) in enumerate([
        ("credential_load", {"fields": [], "note": "demo: no credential is loaded"}),
        ("live_mode_transition", {"from": "backtest", "to": "demo"}),
        ("order_placement", {"symbol": "BTCUSD", "note": "demo: simulated, never sent"}),
    ]):
        created = f"{end}T00:0{index}:00Z"
        digest = compute_entry_hash(prev, event_type, created, payload)
        events.append({"event_id": f"demo-{index}", "created_at": created, "event_type": event_type, "actor": "demo", "prev_hash": prev, "hash": digest, "payload": payload})
        prev = digest
    audit_log = {"generated_at": f"{end}T00:00:00Z", "total_entries": len(events), "chain_valid": True, "chain_broken_at_event_id": None, "recent_events": events}

    retraining = {"generated_at": f"{end}T00:00:00Z", "active_model": None, "latest_candidate": None, "last_trigger": None, "latest_retraining_event": None,
                  "validation_status": "demo: the shipped book is a rule, not a model", "rollback_available": False, "rollback_candidates": []}
    paper = {
        "generated_at": f"{end}T00:00:00Z", "ready": False, "blocking_reasons": ["demo data: no observation period, no broker"],
        "checks": {"observation_count": {"pass": False, "value": 0, "threshold": 500}, "simulated_sharpe": {"pass": stats["sharpe_ratio"] >= 0.3, "value": stats["sharpe_ratio"], "threshold": 0.3}},
        "broker_config_present": False, "broker_config_reason": "demo: no broker is configured",
    }
    from datetime import datetime, timezone

    from execution.live_readiness import build_scorecard

    readiness = build_scorecard({}, now=datetime.fromisoformat(f"{end}T00:00:00").replace(tzinfo=timezone.utc), account="demo").to_dict()
    files = {
        "visualization/grafana/live_readiness.json": _json(readiness),
        "visualization/grafana/retraining_status.json": _json(retraining),
        "visualization/grafana/paper_readiness_report.json": _json(paper),
        "visualization/state.json": _json(state),
        "visualization/scene.json": _json(scene),
        "visualization/topology_state.json": _json(topology),
        "visualization/grafana/runtime_metrics_snapshot.json": _json(metrics),
        "visualization/grafana/audit_log.json": _json(audit_log),
        "visualization/grafana/equity_curves.csv": _csv(equity_rows, list(equity_rows[0])),
        "visualization/grafana/asset_performance.csv": _csv(asset_rows, list(asset_rows[0])),
        "visualization/grafana/observation_equity_curve.csv": _csv(observation_rows, list(observation_rows[0])),
        "ml/evaluation/hello_world.json": _json({key: value for key, value in report.to_dict().items() if key not in ("equity", "benchmark_equity", "elapsed_s")}),
        "README.md": (
            "# Dashboard demo data\n\n"
            "Generated by `python scripts/build_dashboard_demo.py` from `aq hello`'s run of the shipped rule on the bundled sample. Every file "
            "`monitoring/api_server.py` reads, in the shapes the web UI expects. Served when `AQ_DASHBOARD_ROOT` points here and "
            "`AQ_DASHBOARD_DEMO=1` (the `dashboard` Docker image). Nothing here comes from a broker, a model or a Lean run; every page says so.\n"
        ),
    }
    for relative, text in files.items():
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    files = build(Path(args.out))
    total = sum(len(text.encode("utf-8")) for text in files.values())
    print(f"wrote {len(files)} files, {total / 1024:.0f} KB, to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
