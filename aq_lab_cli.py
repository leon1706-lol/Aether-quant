"""The model-lab, data, signal, research and maintainer commands of `aq`: `data`, `signal`, `features`, `overfit`, `lab`,
`dataset`, `stack`, `trials`, `runs`, `api-diff`, `release` and `health`.

Logic lives in the library (`lab/`, `features/feature_registry.py`, `evaluation/`); each `cmd_*` here reads files, calls
it and prints. Registered by `register(subparsers)` from `aq_cli.build_parser()`. Heavy imports wait until a command runs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import aq_devtools as dev

ROOT_DIR = dev.ROOT_DIR
PROJECT_LEDGER = ROOT_DIR / "ml" / "evaluation" / "v671" / "trial_ledger.jsonl"


def _lab_dir(args: argparse.Namespace) -> Path:
    from lab import run_registry

    if getattr(args, "lab", None):
        return Path(args.lab)
    found = run_registry.find_lab(Path.cwd())
    if found is None:
        raise FileNotFoundError("no lab here: run aq lab init DIR, then work inside DIR (or pass --lab DIR)")
    return found


def _fail(message: str, code: int = dev.EXIT_FAIL) -> int:
    print(f"aq: {message}", file=sys.stderr)
    return code


def _closes(path: str | None):
    from lab.data_explore import read_closes

    if path:
        return read_closes(Path(path))
    from aether_quant.samples import load_sample_prices

    return load_sample_prices("close")


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


def cmd_data(args: argparse.Namespace) -> int:
    command = args.data_command
    if command == "fetch":
        import datetime as _datetime

        from data_pipeline.public_candles import bars_to_panel, fetch_daily_bars

        coins = [coin.strip().upper() for coin in args.coins.split(",") if coin.strip()]
        coins = [coin if coin.endswith("USD") or "-" in coin else f"{coin}USD" for coin in coins]
        end = _datetime.date.fromisoformat(args.end) if args.end else _datetime.date.today()
        bars, failed = fetch_daily_bars(coins, _datetime.date.fromisoformat(args.start), end)
        if failed:
            print(f"warning: no data for {', '.join(failed)}", file=sys.stderr)
        closes = bars_to_panel(bars, "close")
        if closes.empty:
            return _fail("no bars downloaded (offline? try aq data sample)")
        out = Path(args.out)
        if out.suffix == ".parquet":
            try:
                closes.to_parquet(out)
            except ImportError:
                return _fail('parquet needs pyarrow: pip install "aether-quant[research]" (or write .csv)')
        else:
            closes.to_csv(out, index_label="date")
        print(f"wrote {out}: {closes.shape[0]} dates x {closes.shape[1]} coins")
        return dev.EXIT_OK
    if command == "sample":
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        from aether_quant.samples import load_sample_prices, sample_info

        closes = load_sample_prices("close")
        closes.to_csv(out / "closes.csv", index_label="date")
        source = sample_info().get("source", "the bundled sample")
        (out / "README.txt").write_text(f"closes.csv: daily closes, a date column then one column per coin ({source}).\n"
                                        "Try: aq data explore closes.csv --out explore.html; aq dataset build --prices closes.csv --out dataset.csv\n", encoding="utf-8")
        print(f"wrote {out / 'closes.csv'} ({closes.shape[0]} dates x {closes.shape[1]} coins) and README.txt")
        return dev.EXIT_OK
    if command == "manifest":
        manifest = data_manifest(Path(args.root))
        if args.out:
            Path(args.out).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
            print(f"wrote {args.out}: {len(manifest['files'])} files")
        else:
            dev.emit(manifest, True)
        return dev.EXIT_OK
    if command == "diff":
        left = json.loads(Path(args.manifest_a).read_text(encoding="utf-8"))
        right = json.loads(Path(args.manifest_b).read_text(encoding="utf-8")) if args.manifest_b else data_manifest(Path(args.root))
        report = manifest_diff(left, right)
        dev.emit(report, args.json, lambda data: "\n".join([*(f"only in A: {name}" for name in data["only_a"]), *(f"only in B: {name}" for name in data["only_b"]),
                                                            *(f"differs:   {name}" for name in data["differs"])]) or "identical")
        return dev.EXIT_GATE if any(report.values()) else dev.EXIT_OK
    from lab import data_explore

    closes = data_explore.read_closes(Path(args.file))
    if command == "info":
        dev.emit(data_explore.info(closes), args.json, data_explore.render_info)
        return dev.EXIT_OK
    page = data_explore.render_explore_html(data_explore.explore(closes, title=f"Data: {Path(args.file).name}"))
    out = Path(args.out or Path(args.file).with_suffix(".html"))
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")
    return dev.EXIT_OK


def data_manifest(root: Path) -> dict:
    """{root, files: {relative path: {size, sha256}}} of every file under `root`."""
    from lab.trainer import sha256_file

    files = {path.relative_to(root).as_posix(): {"size": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(root.rglob("*")) if path.is_file()}
    return {"root": root.as_posix(), "files": files}


def manifest_diff(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, list[str]]:
    a, b = left.get("files", {}), right.get("files", {})
    return {"only_a": sorted(set(a) - set(b)), "only_b": sorted(set(b) - set(a)), "differs": sorted(name for name in set(a) & set(b) if a[name].get("sha256") != b[name].get("sha256"))}


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------


def read_signal(path: Path):
    import pandas as pd

    frame = pd.read_csv(path, dtype={"date": str, "ticker": str})
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna(frame["date"])
    return frame


def signal_targets(prices, horizons: Sequence[int]):
    from evaluation.signal_tools import forward_rank_targets

    return forward_rank_targets(prices, horizons)


def _check_or_fail(frame) -> int | None:
    from evaluation.signal_tools import validate_signal_frame

    problems = validate_signal_frame(frame)
    if problems["errors"]:
        print("the signal file has errors (aq signal check FILE):\n" + "\n".join(f"  {line}" for line in problems["errors"]), file=sys.stderr)
        return dev.EXIT_FAIL
    return None


def cost_model(text: str):
    from execution.cost_models import LinearCostModel, coinbase_model, ib_equity_model

    if text == "coinbase":
        return coinbase_model()
    if text == "ib_equity":
        return ib_equity_model()
    if text.startswith("bps:"):
        return LinearCostModel(commission_bps=float(text[4:]))
    raise ValueError("--cost is coinbase, ib_equity or bps:N")


def cmd_signal(args: argparse.Namespace) -> int:
    import numpy as np
    import pandas as pd

    command = args.signal_command
    if command == "check":
        from evaluation.signal_tools import validate_signal_frame

        report = validate_signal_frame(read_signal(Path(args.file)), min_names=args.min_names)
        dev.emit(report, args.json, lambda data: "\n".join([*(f"error: {line}" for line in data["errors"]), *(f"warning: {line}" for line in data["warnings"])])
                 or "ok: date, ticker, score, no duplicates, every score finite")
        return dev.EXIT_FAIL if report["errors"] else dev.EXIT_OK
    prices = _closes(args.prices)
    horizons = [int(part) for part in str(args.horizons).split(",") if part.strip()]
    if command == "eval":
        signal = read_signal(Path(args.file))
        if (code := _check_or_fail(signal)) is not None:
            return code
        from evaluation.research_harness import evaluate_signal
        from evaluation.signal_tools import ic_decay, quantile_returns

        targets = signal_targets(prices, horizons)
        frame = targets.merge(signal[["date", "ticker", "score"]], on=["date", "ticker"], how="inner")
        report = evaluate_signal(frame, score_column="score", splits=("validation",), horizons=tuple(horizons), min_names_per_date=args.min_names, bootstrap_draws=200)
        wide = signal.pivot(index="date", columns="ticker", values="score").reindex(index=prices.index, columns=prices.columns)
        decay = ic_decay(wide, prices, horizons=(1, 5, 10, 20, 60), min_names=args.min_names)
        from lab.run_evaluation import half_life

        quintiles = quantile_returns(wide, (prices.shift(-1) / prices - 1.0)).mean()
        result = {"report": report, "decay": {int(k): float(v) for k, v in decay.items()}, "half_life_sessions": half_life({int(k): float(v) for k, v in decay.items()}),
                  "quintile_mean_return_1d": {int(k): float(v) for k, v in quintiles.items()}}
        if args.html:
            from lab import report_html as rh

            page = rh.page(f"Signal {Path(args.file).name}", [("Decay", rh.svg_bars({f"{h} sessions": v for h, v in result["decay"].items()}, label="IC decay")),
                                                            ("Quintiles (next-day return)", rh.svg_bars({f"Q{k}": v for k, v in result["quintile_mean_return_1d"].items()}, label="Quintiles")),
                                                            ("Report", f"<pre>{json.dumps(dev_safe(report), indent=1)[:20000]}</pre>")])
            Path(args.html).write_text(page, encoding="utf-8")
            print(f"wrote {args.html}")
        dev.emit(result, args.json, _render_signal_eval)
        return dev.EXIT_OK
    if command == "compare":
        from lab.run_evaluation import daily_ic

        signals = {Path(path).stem: read_signal(Path(path)) for path in args.files}
        for frame in signals.values():
            if (code := _check_or_fail(frame)) is not None:
                return code
        horizon = max(horizons)
        targets = signal_targets(prices, [horizon])
        merged = targets[["date", "ticker", f"target_rank_{horizon}d"]]
        for name, frame in signals.items():
            merged = merged.merge(frame[["date", "ticker", "score"]].rename(columns={"score": name}), on=["date", "ticker"], how="inner")
        names = list(signals)
        ic = {name: float(daily_ic(merged[name], merged[f"target_rank_{horizon}d"], merged["date"]).mean()) for name in names}
        correlation = merged.groupby("date")[names].corr(method="spearman").groupby(level=1).mean().reindex(index=names, columns=names)
        residual = {}
        for name in names:
            others = [other for other in names if other != name]
            if not others:
                continue
            parts = []
            for _, group in merged.groupby("date"):
                if len(group) < len(others) + 3:
                    continue
                design = np.column_stack([np.ones(len(group)), group[others].rank().to_numpy(dtype=float)])
                y = group[name].rank().to_numpy(dtype=float)
                beta, *_ = np.linalg.lstsq(design, y, rcond=None)
                parts.append(group.assign(_resid=y - design @ beta))
            joined = pd.concat(parts) if parts else merged.iloc[0:0].assign(_resid=[])
            residual[name] = float(daily_ic(joined["_resid"], joined[f"target_rank_{horizon}d"], joined["date"]).mean()) if len(joined) else None
        combined = merged[names].rank(pct=True).mean(axis=1)
        result = {"horizon": horizon, "rows": len(merged), "ic": ic, "ic_after_the_others": residual, "combined_ic": float(daily_ic(combined, merged[f"target_rank_{horizon}d"], merged["date"]).mean()),
                  "correlation": correlation.round(4).to_dict()}
        dev.emit(result, args.json, lambda data: "\n".join([f"{data['rows']} common rows, {data['horizon']}-session rank target"]
                 + [f"  {name}: IC {data['ic'][name]:+.4f}, left after the others {('-' if data['ic_after_the_others'].get(name) is None else format(data['ic_after_the_others'][name], '+.4f'))}" for name in data["ic"]]
                 + [f"  equal-weight combination: IC {data['combined_ic']:+.4f}"]))
        return dev.EXIT_OK
    signal = read_signal(Path(args.file))
    if (code := _check_or_fail(signal)) is not None:
        return code
    wide = signal.pivot(index="date", columns="ticker", values="score").reindex(index=prices.index, columns=prices.columns)
    if command == "neutralize":
        betas = rolling_betas(prices, market=args.market, window=args.window)
        out_rows = []
        for date in wide.index:  # wide shares the prices' dates, and so do the betas
            pair = pd.DataFrame({"s": wide.loc[date], "b": betas.loc[date]}).dropna()
            if len(pair) < 3 or pair["b"].nunique() < 2:
                continue
            slope, intercept = np.polyfit(pair["b"], pair["s"], 1)
            out_rows += [{"date": date, "ticker": ticker, "score": float(value - (intercept + slope * pair.at[ticker, "b"]))} for ticker, value in pair["s"].items()]
        out = pd.DataFrame(out_rows)
        target = Path(args.out or Path(args.file).with_name(Path(args.file).stem + "_neutral.csv"))
        out.to_csv(target, index=False)
        print(f"wrote {target}: {len(out)} rows, scores with their cross-sectional beta removed")
        return dev.EXIT_OK
    from evaluation.alpha_behaviour import rank_weights
    from evaluation.backtest_api import backtest
    from lab.run_evaluation import sharpe_block

    if args.top_n:
        ranks = wide.rank(axis=1, ascending=False)
        weights = (ranks <= args.top_n).astype(float).div(wide.notna().sum(axis=1).clip(upper=args.top_n).replace(0, np.nan), axis=0).fillna(0.0)
    else:
        weights = rank_weights(wide).fillna(0.0)
    periods = 365 if pd.to_datetime(prices.index).day_of_week.max() >= 5 else 252
    result = backtest(weights, prices, cost_model=cost_model(args.cost), fill="close", rebalance_every=args.rebalance, periods_per_year=periods)
    ledger = Path(args.ledger) if args.ledger else None
    trials = 1
    variance = None
    if ledger is not None:
        from evaluation.trial_ledger import append_trial, candidate_ids, read_ledger
        from lab.run_evaluation import trial_variance

        stats = result.stats()
        append_trial(ledger, trial_id=f"signal:{Path(args.file).stem}:{args.cost}:{args.rebalance}:{args.top_n}", track="signal", window="signal_backtest", role="candidate",
                     annualised_sharpe=float(stats.get("sharpe") or 0.0), n_obs=int(result.returns.notna().sum()), engine="aq signal backtest")
        trials = len(candidate_ids(read_ledger(ledger)))
        variance = trial_variance(ledger)
    block = sharpe_block(result.returns, trials_n=trials, trial_variance=variance)
    report = {"stats": result.stats(), "judged": block, "turnover_mean": float(result.turnover.mean()), "costs_annual": float(result.costs.mean() * periods)}
    dev.emit(report, args.json, lambda data: "\n".join([f"{key}: {value}" for key, value in data["stats"].items()]
             + [f"PSR {data['judged'].get('psr')}, DSR {data['judged'].get('dsr')} at N={data['judged'].get('trials_n')}, minimum track record {data['judged'].get('min_track_record_days')} days",
                f"mean turnover {data['turnover_mean']:.3f}, costs {data['costs_annual']:.2%} a year"]))
    return dev.EXIT_OK


def rolling_betas(prices, *, market: str | None, window: int):
    """Each date's beta of every ticker to the market over the trailing `window` rows (only rows up to that date)."""
    returns = prices.pct_change(fill_method=None)
    bench = returns[market] if market else returns.mean(axis=1)
    minimum = max(20, window // 2)
    variance = bench.rolling(window, min_periods=minimum).var()
    return returns.rolling(window, min_periods=minimum).cov(bench).div(variance.where(variance > 0), axis=0)


def dev_safe(data: Any) -> Any:
    from json_safety import sanitize_json_finite

    return sanitize_json_finite(json.loads(json.dumps(data, default=str)))


def _render_signal_eval(data: Mapping[str, Any]) -> str:
    lines = ["decay: " + ", ".join(f"{h}d {value:+.4f}" for h, value in data["decay"].items() if value == value)]
    lines.append(f"half-life: {data['half_life_sessions'] if data['half_life_sessions'] is not None else '-'} sessions")
    lines.append("quintiles (next-day return): " + ", ".join(f"Q{k} {v:+.5f}" for k, v in data["quintile_mean_return_1d"].items()))
    for split, by_horizon in (data["report"].get("splits") or {}).items():
        for horizon, stats in by_horizon.items():
            if isinstance(stats, dict) and "mean_ic" in stats:
                lines.append(f"{split} {horizon}: IC {stats['mean_ic']:+.4f} over {stats['num_dates']} dates (HAC t {stats['hac_t']:.2f}, 95% CI {stats.get('ci95')})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------


def cmd_features(args: argparse.Namespace) -> int:
    from features import feature_registry

    if args.features_command == "list":
        rows = feature_registry.catalog()
        data = {"features": rows, "sets": {name: list(names) for name, names in feature_registry.SETS.items()},
                "production_only_groups": list(feature_registry.PRODUCTION_ONLY_GROUPS) if args.all else []}
        dev.emit(data, args.json, lambda value: "\n".join([f"{row['name']:<16} {row['group']:<11} {row['lookback']:>4}  {row['description']}" for row in value["features"]]
                 + [f"sets: {', '.join(f'{name} ({len(names)})' for name, names in value['sets'].items())}"]
                 + ([f"production-only groups (need inputs a close table lacks): {', '.join(value['production_only_groups'])}"] if value["production_only_groups"] else [])))
        return dev.EXIT_OK
    prices = _closes(args.prices)
    try:
        names = feature_registry.resolve(args.set if args.features_command == "build" else args.name)
    except KeyError as error:
        return _fail(str(error.args[0]), dev.EXIT_USAGE)
    if args.features_command == "build":
        long = feature_registry.build_long(prices, names)
        if args.dry_run:
            print(f"would write {len(long)} rows x {len(names)} features ({', '.join(names)})")
            return dev.EXIT_OK
        out = Path(args.out)
        long.to_csv(out, index=False)
        print(f"wrote {out}: {len(long)} rows, features {', '.join(names)}")
        return dev.EXIT_OK
    return inspect_feature(prices, names[0], args)


def inspect_feature(prices, name: str, args: argparse.Namespace) -> int:
    import pandas as pd

    from evaluation.research_harness import ic_summary
    from evaluation.signal_tools import ic_decay
    from features import feature_registry
    from lab.run_evaluation import daily_ic, half_life

    horizons = [int(part) for part in str(args.horizons).split(",") if part.strip()]
    wide = feature_registry.build_wide(prices, [name])[name]
    targets = signal_targets(prices, horizons)
    long = wide.stack(future_stack=True).rename("value").reset_index()
    long.columns = ["date", "ticker", "value"]
    frame = targets.merge(long.astype({"date": str, "ticker": str}), on=["date", "ticker"], how="inner")
    by_horizon = {}
    for horizon in horizons:
        series = daily_ic(frame["value"], frame[f"target_rank_{horizon}d"], frame["date"])
        by_horizon[horizon] = ic_summary(dict(series.items()), horizon=horizon, bootstrap_draws=200)
    decay = {int(k): float(v) for k, v in ic_decay(wide, prices, horizons=(1, 5, 10, 20, 60)).items()}
    yearly = daily_ic(frame["value"], frame[f"target_rank_{max(horizons)}d"], frame["date"])
    others = [other for other in feature_registry.SETS["core"] if other != name]
    other_tables = feature_registry.build_wide(prices, others)
    overlap = {other: float(pd.concat([wide.stack(future_stack=True), table.stack(future_stack=True)], axis=1).dropna().corr(method="spearman").iloc[0, 1]) for other, table in other_tables.items()}
    result = {"feature": name, "spec": next(row for row in feature_registry.catalog() if row["name"] == name), "ic": {h: {k: v for k, v in s.items() if not isinstance(v, (list, dict))} for h, s in by_horizon.items()},
              "decay": decay, "half_life_sessions": half_life(decay), "ic_by_year": {year: float(values.mean()) for year, values in yearly.groupby(pd.Index(yearly.index).str[:4])},
              "overlap": dict(sorted(overlap.items(), key=lambda item: -abs(item[1])))}
    if args.html:
        from lab import report_html as rh

        Path(args.html).write_text(rh.page(f"Feature {name}", [("IC by year", rh.svg_bars(result["ic_by_year"])), ("Decay", rh.svg_bars({f"{h}d": v for h, v in decay.items()})),
                                                              ("Overlap with the core set", rh.svg_bars(result["overlap"]))]), encoding="utf-8")
        print(f"wrote {args.html}")
    dev.emit(result, args.json, lambda data: "\n".join([f"{name}: {data['spec']['description']}"]
             + [f"  {h}-session IC {stats.get('mean_ic')}, HAC t {stats.get('hac_t')}" for h, stats in data["ic"].items()]
             + ["  decay: " + ", ".join(f"{h}d {v:+.4f}" for h, v in data["decay"].items() if v == v), f"  half-life: {data['half_life_sessions']}"]
             + ["  most overlapping: " + ", ".join(f"{k} {v:+.2f}" for k, v in list(data["overlap"].items())[:3])]))
    return dev.EXIT_OK


# ---------------------------------------------------------------------------
# overfitting calculators
# ---------------------------------------------------------------------------


def _returns_file(path: str):
    import pandas as pd

    frame = pd.read_csv(path)
    column = next((name for name in frame.columns if name.lower() in {"return", "returns", "ret"}), frame.columns[-1])
    return pd.to_numeric(frame[column], errors="coerce").dropna().to_numpy()


def cmd_overfit(args: argparse.Namespace) -> int:
    command = args.overfit_command
    if command == "pbo":
        import pandas as pd

        from evaluation.pbo import probability_of_backtest_overfitting

        matrix = pd.read_csv(args.trials).select_dtypes("number")
        result = probability_of_backtest_overfitting(matrix.to_numpy(dtype=float), blocks=args.blocks)
        result = {key: value for key, value in result.items() if key != "lambda_quantiles"}
        dev.emit(result, args.json, lambda data: f"PBO {data.get('pbo')} over {data.get('num_trials')} trials and {data.get('num_combinations')} combinations")
        return dev.EXIT_OK
    if command == "hurdle":
        from evaluation.backtest_statistics import expected_max_sharpe

        value = expected_max_sharpe(args.trials, args.trial_variance)
        dev.emit({"hurdle_sharpe": value, "trials": args.trials, "trial_variance": args.trial_variance}, args.json,
                 lambda data: f"a winner of {data['trials']} unskilled trials is expected to show Sharpe {data['hurdle_sharpe']}")
        return dev.EXIT_OK
    if command == "haircut":
        from evaluation.overfitting import haircut_sharpe

        value = haircut_sharpe(args.sharpe, args.obs, args.trials, method=args.method)
        dev.emit(value, args.json, lambda data: f"haircut Sharpe {data['haircut_sharpe']:.3f} from {data['sharpe']} (t {data['t_stat']:.2f}, p {data['p_value']:.4f}, adjusted p {data['adjusted_p_value']:.4f})")
        return dev.EXIT_OK
    returns = _returns_file(args.returns)
    if command == "psr":
        from evaluation.backtest_statistics import probabilistic_sharpe_ratio

        value = probabilistic_sharpe_ratio(returns, args.benchmark_sharpe)
        dev.emit({"psr": value, "observations": int(len(returns))}, args.json, lambda data: f"PSR {data['psr']} over {data['observations']} observations")
        return dev.EXIT_OK
    if command == "mintrl":
        from evaluation.overfitting import minimum_track_record_length

        value = minimum_track_record_length(returns, target_sharpe=args.target_sharpe, confidence=args.confidence, periods_per_year=args.periods)
        dev.emit({"min_track_record": value, "observations_now": int(len(returns))}, args.json, lambda data: f"minimum track record {data['min_track_record']} observations (have {data['observations_now']})")
        return dev.EXIT_OK
    from evaluation.alpha_proof import deflated_sharpe_from_inputs

    trials, variance = args.trials, args.trial_variance
    if args.from_ledger:
        from evaluation.trial_ledger import project_deflation_inputs

        inputs = project_deflation_inputs(ROOT_DIR / "ml" / "evaluation")
        trials, variance = inputs["N"], inputs["var"]
    if trials is None or variance is None:
        return _fail("dsr needs --trials and --trial-variance (or --from-ledger)", dev.EXIT_USAGE)
    result = deflated_sharpe_from_inputs(returns, num_trials=trials, trial_variance=variance, annualization=args.periods)
    dev.emit(result, args.json, lambda data: f"DSR {data.get('value')} at N={trials} (hurdle Sharpe {data.get('expected_max_sharpe_annual')})")
    return dev.EXIT_OK


# ---------------------------------------------------------------------------
# lab
# ---------------------------------------------------------------------------


def _overrides(items: Sequence[str] | None) -> dict:
    from lab.spec import merge, parse_override

    out: dict = {}
    for item in items or []:
        out = merge(out, parse_override(item))
    return out


def cmd_lab(args: argparse.Namespace) -> int:
    from lab import run_registry

    command = args.lab_command
    if command == "init":
        folder = Path(args.directory)
        created = run_registry.init_lab(folder)
        print(f"lab at {folder}: " + (", ".join(created) if created else "already set up"))
        print(f"next: cd {folder}; aq data sample --out data; aq dataset build --prices data/closes.csv --out data/dataset.csv; aq lab new first --template multitask")
        return dev.EXIT_OK
    try:
        lab_dir = _lab_dir(args)
    except FileNotFoundError as error:
        return _fail(str(error))
    try:
        return _lab_command(command, args, lab_dir)
    except (FileNotFoundError, KeyError, ValueError, FileExistsError) as error:
        return _fail(f"aq lab {command}: {error.args[0] if error.args else error}", dev.EXIT_FAIL)
    except RuntimeError as error:
        return _fail(f"aq lab {command}: {error}")


def _lab_command(command: str, args: argparse.Namespace, lab_dir: Path) -> int:
    from lab import model_templates, run_evaluation, run_registry, trainer

    project_ledger = PROJECT_LEDGER if getattr(args, "project_ledger", False) else None
    if command == "new":
        written = model_templates.new_model(lab_dir, args.name, args.template, force=args.force)
        print("wrote " + ", ".join(written))
        print(f"next: aq lab train {args.name}")
        return dev.EXIT_OK
    if command == "train":
        if args.engine == "production":
            return train_production(args, lab_dir)
        seeds = [int(part) for part in args.seeds.split(",")] if args.seeds else None
        record = trainer.train_run(lab_dir, args.model, overrides=_overrides(args.set), seeds=seeds, folds=args.folds, resume=args.resume, dry_run=args.dry_run,
                                   project_ledger=project_ledger, project_config=ROOT_DIR / "config.json" if args.project_ledger else None)
        if record.get("dry_run"):
            dev.emit(record, args.json, lambda data: "\n".join(f"{key}: {value}" for key, value in data.items() if key != "dry_run"))
            return dev.EXIT_OK
        dev.emit(record, args.json, lambda data: f"run {data['id']}: out-of-sample IC {data['metrics']['oof_ic_mean']} (seed spread {data['metrics']['oof_ic_seed_std']}), N {data['trials_n']}\n"
                 f"next: aq lab eval {data['id']} --book")
        return dev.EXIT_OK
    if command == "runs":
        dev.emit(run_registry.list_runs(lab_dir), args.json, run_registry.render_runs)
        return dev.EXIT_OK
    if command == "show":
        run_dir = run_registry.find_run(lab_dir, args.run)
        dev.emit(run_registry.read_run(run_dir), args.json, lambda data: json.dumps(dev_safe(data), indent=1))
        return dev.EXIT_OK
    if command == "eval":
        run_dir = run_registry.find_run(lab_dir, args.run)
        if args.holdout:
            if not args.i_understand_this_spends_it:
                return _fail("--holdout reads the sealed holdout once and for good: add --i-understand-this-spends-it", dev.EXIT_USAGE)
            spend_holdout(lab_dir, run_dir, project=args.project_ledger)
        report = run_evaluation.evaluate_run(run_dir, lab_dir=lab_dir, book=args.book, cost_bps=args.cost_bps)
        if args.html:
            Path(args.html).write_text(run_evaluation.render_eval_html(report), encoding="utf-8")
            print(f"wrote {args.html}")
        dev.emit(report, args.json, run_evaluation.render_eval)
        return dev.EXIT_OK
    if command == "compare":
        runs = [run_registry.find_run(lab_dir, key) for key in args.runs]
        report = run_evaluation.compare_runs(runs, baseline=args.baseline)
        if args.html:
            from lab import report_html as rh

            Path(args.html).write_text(rh.page("Lab leaderboard", [("Out-of-sample IC", rh.table([[row["run"], row["ic"], row["days"], row["diff"], row["t_hac"]] for row in report["leaderboard"]],
                                                                                                  ["run", "IC", "days", "vs best", "HAC t"]))]), encoding="utf-8")
            print(f"wrote {args.html}")
        dev.emit(report, args.json, run_evaluation.render_compare)
        return dev.EXIT_OK
    if command == "card":
        run_dir = run_registry.find_run(lab_dir, args.run)
        text = run_evaluation.model_card(run_dir, run_evaluation.evaluate_run(run_dir, lab_dir=lab_dir, book=True))
        out = Path(args.out) if args.out else run_dir / "MODEL_CARD.md"
        out.write_text(text, encoding="utf-8")
        print(text if not args.out else f"wrote {out}")
        return dev.EXIT_OK
    if command == "sweep":
        from lab import sweep

        grid = sweep.parse_grid(args.grid)
        state = sweep.run_sweep(lab_dir, args.model, grid, train=lambda lab, model, **kw: trainer.train_run(lab, model, project_ledger=project_ledger, **kw),
                                random_k=args.random, seed=args.seed, max_trials=args.max_trials, trials_now=trainer.ledger_count(lab_dir, project_ledger))
        dev.emit(state, args.json, lambda data: "\n".join([f"{len(data['points'])} points; PBO {(data.get('pbo') or {}).get('value')}"]
                 + [f"  {item['status']:<9} IC {item['oof_ic']}  {item['point']}" for item in data["points"]]
                 + [f"best: {data['best']['point']} (IC {data['best']['oof_ic']})" if data.get("best") else "no finished point"]))
        return dev.EXIT_OK
    run_dir = run_registry.find_run(lab_dir, args.run)
    from lab import explain

    if command == "explain":
        report = explain.explain_run(run_dir)
        dev.emit(report, args.json, lambda data: explain.render_mapping("permutation importance (IC drop, out of sample)", data["importance"]) + "\n"
                 + explain.render_mapping("by group", data["groups"]) + "\n" + explain.render_mapping("each feature's own IC", data["feature_ic"]))
        return dev.EXIT_OK
    if command == "ablate":
        report = explain.ablate_run(lab_dir, run_dir, train=lambda lab, model, **kw: trainer.train_run(lab, model, project_ledger=project_ledger, **kw))
        dev.emit(report, args.json, lambda data: f"base IC {data['base_oof_ic']}\n" + "\n".join(f"  without {group}: IC {row['oof_ic']} (change {row['change']})" for group, row in data["groups"].items()))
        return dev.EXIT_OK
    if command == "seeds":
        report = explain.seed_stability(lab_dir, run_dir, seeds=args.seeds, train=lambda lab, model, **kw: trainer.train_run(lab, model, project_ledger=project_ledger, **kw))
        dev.emit(report, args.json, lambda data: f"{data['seeds']} seeds: IC mean {data['mean']}, std {data['std']}, range {data['range']}" + (" UNSTABLE" if data["unstable"] else ""))
        return dev.EXIT_OK
    from lab import model_export

    card = run_evaluation.model_card(run_dir, run_evaluation.evaluate_run(run_dir, lab_dir=lab_dir, book=True))
    out = Path(args.out) if args.out else lab_dir / f"{args.name}.zip"
    result = model_export.export_run(run_dir, out, card=card)
    dev.emit(result, args.json, lambda data: f"wrote {data['zip']} (sha256 {data['sha256'][:16]}...): aq models install {args.name} --from {data['zip']}")
    return dev.EXIT_OK


def spend_holdout(lab_dir: Path, run_dir: Path, *, project: bool) -> None:
    """Record the one read of the holdout before anything opens it; a second read raises."""
    import datetime as _datetime

    from evaluation.research_cells import record_holdout_read
    from evaluation.research_round import HOLDOUT_LEDGER, holdouts_spent

    ledger = ROOT_DIR / HOLDOUT_LEDGER if project else lab_dir / "holdout_ledger.jsonl"
    cells = ("lab",) if not project else ("crypto", "equity")
    spent = [cell for cell in holdouts_spent(ledger) if cell in cells]
    if spent:
        raise PermissionError(f"holdout {spent} already spent (R-ADMIT1): it cannot back a second candidate")
    record_holdout_read(ledger, candidate=run_dir.name, cells=cells, digest=run_registry_digest(run_dir), created_at=_datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds"))


def run_registry_digest(run_dir: Path) -> str:
    import hashlib

    return hashlib.sha256((run_dir / "run.json").read_bytes()).hexdigest()


def train_production(args: argparse.Namespace, lab_dir: Path) -> int:
    """The real trainers on the project dataset, copied into a lab run so lab eval and compare judge them the same way."""
    if (missing := dev.needs_checkout()) is not None:
        return missing
    import shutil

    from lab import run_registry

    trainer_script = {"multitask": "train_multitask.py", "tcn": "train_sequence.py"}.get(args.production_kind)
    run_id = run_registry.new_run_id(f"production_{args.production_kind}")
    version = f"lab-{run_id}"
    seed = int((args.seeds or "7").split(",")[0])
    command = [sys.executable, trainer_script, "--version-id", version, "--seed", str(seed), "--memory-profile", args.memory_profile,
               *(["--ranking-objective", args.objective] if args.objective else []), *(["--resume"] if args.resume and trainer_script == "train_sequence.py" else [])]
    if args.dry_run:
        print(" ".join(command))
        return dev.EXIT_OK
    code = dev.run_live(command)
    if code != 0:
        return code
    source = ROOT_DIR / "ml" / "versions" / version
    run_dir = lab_dir / "runs" / run_id
    shutil.copytree(source, run_dir / "production", dirs_exist_ok=True)
    run_registry.write_run(run_dir, {"model": f"production_{args.production_kind}", "template": "production", "status": "finished", "seeds": [seed],
                                     "dataset": str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"), "target": "target_rank_20d", "engine": trainer_script})
    print(f"run {run_id}: the trainer's outputs are in {run_dir / 'production'}; score them with aq stack lab-baseline --ml-dir {source}")
    return dev.EXIT_OK


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------


def cmd_dataset(args: argparse.Namespace) -> int:
    from lab import lab_dataset

    command = args.dataset_command
    if command == "build":
        prices = _closes(args.prices)
        splits = lab_dataset.parse_splits(args.splits) if args.splits else None
        frame = lab_dataset.build_dataset(prices, features=args.features, targets=[int(part) for part in args.targets.split(",")], splits=splits)
        if args.dry_run:
            dev.emit(lab_dataset.dataset_info(frame), args.json, lambda data: f"would write {data['rows']} rows, {len(data['features'])} features, splits {list(data['splits'])}")
            return dev.EXIT_OK
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(out, index=False)
        print(f"wrote {out}: {len(frame)} rows, {len(lab_dataset.feature_columns(frame))} features, splits {sorted(frame['split'].unique())}")
        return dev.EXIT_OK
    import pandas as pd

    frame = pd.read_csv(args.file, dtype={"date": str, "ticker": str}, low_memory=False)
    if command == "info":
        dev.emit(lab_dataset.dataset_info(frame), args.json, lambda data: "\n".join(
            [f"{data['rows']} rows, {data['dates']} dates, {data['tickers']} tickers, {len(data['features'])} features"]
            + [f"  {split}: {row['rows']} rows, {row['start']} .. {row['end']}" for split, row in data["splits"].items()]
            + [f"  targets: {', '.join(data['targets'])}", f"  sealed holdout rows: {data['holdout_rows']}"]
            + [f"  {name}: {share:.1%} missing" for name, share in data["features"].items() if share > 0.2]))
        return dev.EXIT_OK
    report = lab_dataset.leakage_report(lab_dataset.seal(frame), target=args.target)
    dev.emit(report, args.json, lambda data: f"flagged: {', '.join(data['flagged']) or 'nothing'}")
    return dev.EXIT_GATE if report.get("flagged") else dev.EXIT_OK


# ---------------------------------------------------------------------------
# the installed stack (owner research)
# ---------------------------------------------------------------------------


def stack_inspect(ml_dir: Path) -> dict:
    from evaluation.head_audit import load_head_metrics
    from retraining.artifact_pins import artifact_problems

    metrics = load_head_metrics(ml_dir)
    schema_path = ml_dir / "feature_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.exists() else {}
    models = {}
    for name, data in metrics.items():
        if not isinstance(data, dict):
            continue
        heads = {}
        for split in ("train", "validation", "backtest"):
            for key, value in (data.get(split) or {}).items():
                if key.endswith("_ic") and isinstance(value, dict) and value.get("mean_ic") is not None:
                    heads.setdefault(key.removesuffix("_ic"), {})[split] = round(float(value["mean_ic"]), 4)
        if heads or data.get("version_id"):
            models[name] = {"version": data.get("version_id"), "trained_at": str(data.get("trained_at") or "")[:19], "best_epoch": data.get("best_epoch"), "heads": heads}
    return {"ml_dir": str(ml_dir), "models": models, "features": len(schema.get("model_input_names") or schema.get("feature_names") or []),
            "pins": artifact_problems(ml_dir, ml_dir / "artifact_pins.json") or "ok"}


def cmd_stack(args: argparse.Namespace) -> int:
    ml_dir = Path(args.ml_dir) if args.ml_dir else ROOT_DIR / "ml"
    if not ml_dir.is_dir():
        return _fail("no ml/ folder: the project's models are private; aq models lists the published examples")
    if args.stack_command == "inspect":
        data = stack_inspect(ml_dir)
        dev.emit(data, args.json, lambda value: "\n".join([f"{value['ml_dir']}: {value['features']} model inputs, pins {value['pins'] if value['pins'] == 'ok' else 'FAILING: ' + '; '.join(value['pins'])}"]
                 + [f"  {name} {row['version']} trained {row['trained_at']}: " + ", ".join(f"{head} {splits.get('validation')}/{splits.get('backtest')}" for head, splits in list(row["heads"].items())[:6])
                    for name, row in value["models"].items()]))
        return dev.EXIT_OK
    return stack_scored(args, ml_dir)


def stack_scores(ml_dir: Path, *, split: str | None, max_dates: int | None):
    """The live blend's score on the project dataset's non-holdout rows (validation and backtest unless `split`)."""
    import aq_cli
    from lab import lab_dataset

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    dataset = lab_dataset.seal(aq_cli._read_dataset_rows(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"), window=lab_dataset.holdout_window(config))
    dataset = dataset[dataset["split"].isin([split] if split else ["validation", "backtest"])].copy()
    if max_dates:
        keep = sorted(dataset["date"].unique())[-max_dates:]
        dataset = dataset[dataset["date"].isin(keep)].copy()
    raw, _ = aq_cli._blend_raw_scores_for_dataset(dataset, config, 30, ml_dir=ml_dir)
    dataset["score"] = raw
    classes, _ = aq_cli._universe_asset_metadata(config)
    dataset["asset_class"] = dataset["ticker"].map(classes).fillna("other")
    return dataset


def stack_scored(args: argparse.Namespace, ml_dir: Path) -> int:
    import pandas as pd

    from lab.run_evaluation import daily_ic, half_life

    dataset = stack_scores(ml_dir, split=args.split, max_dates=args.max_dates)
    target = f"target_{args.head}" if not args.head.startswith("target_") else args.head
    if args.stack_command == "decay":
        groups = {"class": "asset_class", "year": None, "split": "split"}
        out: dict[str, Any] = {"rows": len(dataset)}
        ic = daily_ic(dataset["score"], dataset[target], dataset["date"])
        out["rolling"] = ic.rolling(args.window, min_periods=max(5, args.window // 3)).mean().dropna().round(4).to_dict()
        decay = {h: float(daily_ic(dataset["score"], dataset[f"target_return_{h}d"], dataset["date"]).mean()) for h in (1, 5, 20) if f"target_return_{h}d" in dataset.columns}
        out["decay"], out["half_life_sessions"] = decay, half_life(decay)
        if args.by == "year":
            out["by"] = {year: float(values.mean()) for year, values in ic.groupby(pd.Index(ic.index).str[:4])}
        else:
            column = groups[args.by]
            out["by"] = {str(name): float(daily_ic(part["score"], part[target], part["date"]).mean()) for name, part in dataset.groupby(column)}
        if args.html:
            from lab import report_html as rh

            Path(args.html).write_text(rh.page("Installed stack: IC decay", [(f"IC by {args.by}", rh.svg_bars(out["by"])),
                                                                             ("Rolling IC", rh.svg_lines([pd.Series(out["rolling"])], label="Rolling IC"))]), encoding="utf-8")
            print(f"wrote {args.html}")
        dev.emit(out, args.json, lambda data: f"{data['rows']} rows; half-life {data['half_life_sessions']} sessions; decay {data['decay']}\n"
                 + "\n".join(f"  {name}: IC {value:+.4f}" for name, value in data["by"].items()))
        return dev.EXIT_OK
    if args.stack_command == "attrib":
        import aq_cli
        from evaluation.feature_quality_audit import permutation_ic_drop

        config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
        features = [name for name in json.loads((ml_dir / "feature_schema.json").read_text(encoding="utf-8")).get("model_input_names", []) if name in dataset.columns][: args.max_features]

        def predict(frame):
            raw, _ = aq_cli._blend_raw_scores_for_dataset(frame, config, 30, ml_dir=ml_dir)
            return raw

        by_class = {}
        for name, part in dataset.groupby("asset_class"):
            by_class[str(name)] = permutation_ic_drop(part.reset_index(drop=True), features, predict, target=target, min_names=3)
        dev.emit(by_class, args.json, lambda data: "\n".join(f"{name}: " + ", ".join(f"{f} {v:+.4f}" for f, v in sorted(((f, v) for f, v in drops.items() if v is not None), key=lambda item: -item[1])[:5])
                                                             for name, drops in data.items()))
        return dev.EXIT_OK
    from lab import run_registry

    lab_dir = _lab_dir(args)
    run_dir = lab_dir / "runs" / run_registry.new_run_id("installed_stack")
    run_dir.mkdir(parents=True)
    dataset[["date", "ticker", "split", "score"]].rename(columns={"score": f"score_{args.head}"}).to_csv(run_dir / "scores.csv", index=False)
    dataset_path = run_dir / "dataset.csv"
    keep = ["date", "ticker", "split", *[column for column in dataset.columns if column.startswith("target_")]]
    dataset[keep].to_csv(dataset_path, index=False)
    run_registry.write_run(run_dir, {"model": "installed_stack", "template": "installed", "status": "finished", "dataset": str(dataset_path), "target": target,
                                     "seeds": [], "features": [], "metrics": {}, "trials_n": None, "ml_dir": str(ml_dir)})
    print(f"registered the installed stack as lab run {run_dir.name}: aq lab compare {run_dir.name} <your run>")
    return dev.EXIT_OK


# ---------------------------------------------------------------------------
# trials
# ---------------------------------------------------------------------------


def cmd_trials(args: argparse.Namespace) -> int:
    from evaluation import trial_ledger

    if args.trials_command == "add":
        ledger = Path(args.ledger) if args.ledger else PROJECT_LEDGER
        if args.dry_run:
            print(f"would record {args.trial_id} ({args.role}, Sharpe {args.sharpe}, {args.obs} observations) in {ledger}")
            return dev.EXIT_OK
        trial_ledger.append_trial(ledger, trial_id=args.trial_id, track=args.track, window=args.window, role=args.role, annualised_sharpe=args.sharpe, n_obs=args.obs,
                                  engine="aq trials add", detail={"note": args.note} if args.note else None)
        print(f"recorded {args.trial_id} ({args.role}) in {ledger}")
        return dev.EXIT_OK
    evaluation_dir = Path(args.evaluation_dir) if args.evaluation_dir else ROOT_DIR / "ml" / "evaluation"
    if not evaluation_dir.is_dir():
        return _fail(f"no {evaluation_dir}: the trial ledgers live under ml/evaluation in the project's checkout")
    inputs = trial_ledger.project_deflation_inputs(evaluation_dir, window=args.window if args.trials_command == "dsr" else None)
    if args.trials_command == "count":
        dev.emit(inputs, args.json, lambda data: f"N = {data['N']} ({data['legacy']} legacy trials, {data['ledger_candidates']} ledger candidates)"
                 + "".join(f"\n  {name}: {count}" for name, count in data["by_ledger"].items()))
        return dev.EXIT_OK
    if args.trials_command == "list":
        rows = [entry for path in sorted(evaluation_dir.rglob("trial_ledger.jsonl")) for entry in trial_ledger.read_ledger(path) if not args.phase or args.phase in str(path)]
        dev.emit(rows[-args.limit:], args.json, lambda data: "\n".join(f"{row.get('role', '?'):<12} {row.get('window', '?'):<18} Sharpe {row.get('annualised_sharpe')}  {row.get('trial_id')}" for row in data))
        return dev.EXIT_OK
    from evaluation.backtest_statistics import expected_max_sharpe

    hurdle = expected_max_sharpe(inputs["N"], inputs["var"]) if inputs["var"] else None
    result = {"N": inputs["N"], "trial_variance": inputs["var"], "hurdle_sharpe": hurdle}
    if args.returns:
        from evaluation.alpha_proof import deflated_sharpe_from_inputs

        result["dsr"] = deflated_sharpe_from_inputs(_returns_file(args.returns), num_trials=inputs["N"], trial_variance=inputs["var"], annualization=args.periods).get("value")
    dev.emit(result, args.json, lambda data: f"at N = {data['N']} (variance {data['trial_variance']}), a new candidate must beat Sharpe {data['hurdle_sharpe']}"
             + (f"; this one's DSR is {data['dsr']}" if "dsr" in data else ""))
    return dev.EXIT_OK


# ---------------------------------------------------------------------------
# Lean runs (owner)
# ---------------------------------------------------------------------------


def run_summary(run_dir: Path) -> dict:
    """A backtests/<run> folder's headline numbers from its result JSON's statistics, the README pin, the frozen config."""
    stats: dict[str, Any] = {}
    result_id = None
    for path in sorted(run_dir.glob("*.json")):
        if path.name.endswith(("-summary.json", "_summary.json")) or path.name in {"config.json"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("statistics"), dict) and data["statistics"]:
            stats, result_id = data["statistics"], path.stem
            break
    pin_path = ROOT_DIR / "ml" / "evaluation" / "readme_lean_run.json"
    pin = json.loads(pin_path.read_text(encoding="utf-8")).get("run") if pin_path.exists() else None
    frozen = ROOT_DIR / "ml" / "evaluation" / "run_configs" / f"{run_dir.name}.json"
    keys = ("Sharpe Ratio", "Net Profit", "Compounding Annual Return", "Drawdown", "Total Orders", "Start Equity", "End Equity", "Total Fees")
    return {"run": run_dir.name, "result_id": result_id, "pinned": pin == run_dir.name, "frozen_config": frozen.exists(), "statistics": {key: stats.get(key) for key in keys if key in stats},
            "all_statistics": stats}


def engine_log_verdict(run_dir: Path) -> str:
    log = run_dir / "log.txt"
    if not log.exists():
        return "no engine log (log.txt)"
    text = log.read_text(encoding="utf-8", errors="replace")
    if "Algorithm Id:" in text and "completed" in text.lower():
        return "completed" + (" (teardown timed out after the statistics were saved)" if "PythonInitializer.Shutdown()" in text and "timed out" in text.lower() else "")
    if "Runtime Error" in text or "Error" in text:
        return "errored (see log.txt)"
    return "unknown"


def cmd_runs(args: argparse.Namespace) -> int:
    root = ROOT_DIR / "backtests"
    folders = sorted([path for path in root.iterdir() if path.is_dir()], key=lambda folder: folder.stat().st_mtime, reverse=True) if root.is_dir() else []
    if args.runs_command == "list":
        rows = [run_summary(path) for path in folders[: args.limit]]
        for row in rows:
            row.pop("all_statistics")
        dev.emit(rows, args.json, lambda data: "\n".join(f"{row['run']}{' *pin' if row['pinned'] else ''}  Sharpe {row['statistics'].get('Sharpe Ratio', '-'):<7} net {row['statistics'].get('Net Profit', '-'):<9} "
                                                         f"DD {row['statistics'].get('Drawdown', '-'):<7} orders {row['statistics'].get('Total Orders', '-')}{'' if row['frozen_config'] else '  (no frozen config)'}" for row in data)
                 or "no runs in backtests/")
        return dev.EXIT_OK
    names = {path.name: path for path in folders}
    if args.runs_command == "show":
        if args.run not in names:
            return _fail(f"no run {args.run!r} in backtests/ (aq runs list)", dev.EXIT_USAGE)
        data = run_summary(names[args.run]) | {"engine_log": engine_log_verdict(names[args.run])}
        dev.emit(data, args.json, lambda value: "\n".join([f"{value['run']} ({value['engine_log']})"] + [f"  {key}: {item}" for key, item in value["all_statistics"].items()]))
        return dev.EXIT_OK
    missing = [run for run in (args.run_a, args.run_b) if run not in names]
    if missing:
        return _fail(f"no run {missing[0]!r} in backtests/", dev.EXIT_USAGE)
    a, b = run_summary(names[args.run_a]), run_summary(names[args.run_b])
    rows = {key: [a["all_statistics"].get(key), b["all_statistics"].get(key)] for key in sorted(set(a["all_statistics"]) | set(b["all_statistics"]))}
    configs = [ROOT_DIR / "ml" / "evaluation" / "run_configs" / f"{run}.json" for run in (args.run_a, args.run_b)]
    config_diff = dev.leaf_diff(json.loads(configs[0].read_text(encoding="utf-8")), json.loads(configs[1].read_text(encoding="utf-8"))) if all(path.exists() for path in configs) else None
    data = {"a": args.run_a, "b": args.run_b, "statistics": rows, "config_diff": config_diff}
    dev.emit(data, args.json, lambda value: "\n".join([f"{'statistic':<32} {value['a']:<22} {value['b']}"] + [f"{key:<32} {pair[0]!s:<22} {pair[1]}" for key, pair in value["statistics"].items() if pair[0] != pair[1]]
             + ["config: " + ("no frozen config for one of them" if value["config_diff"] is None else dev.render_leaf_diff(value["config_diff"]))]))
    return dev.EXIT_OK


# ---------------------------------------------------------------------------
# maintainers: api-diff, release check, health
# ---------------------------------------------------------------------------


def api_surface_at(ref: str | None) -> dict[str, list[str]] | None:
    path = "tests/data/aether_quant_api.json"
    if ref is None:
        return json.loads((ROOT_DIR / path).read_text(encoding="utf-8"))
    code, text = dev.run_capture(["git", "show", f"{ref}:{path}"])
    return json.loads(text) if code == 0 else None


def api_diff(old: Mapping[str, Sequence[str]], new: Mapping[str, Sequence[str]]) -> dict:
    """Names added and removed per module, and the semver bump it implies (removed -> major, added -> minor, else patch)."""
    added = {module: sorted(set(new.get(module, [])) - set(old.get(module, []))) for module in sorted(set(new) | set(old))}
    removed = {module: sorted(set(old.get(module, [])) - set(new.get(module, []))) for module in sorted(set(new) | set(old))}
    added = {module: names for module, names in added.items() if names}
    removed = {module: names for module, names in removed.items() if names}
    return {"added": added, "removed": removed, "bump": "major" if removed else "minor" if added else "patch"}


def latest_tag() -> str | None:
    code, out = dev.run_capture(["git", "describe", "--tags", "--abbrev=0"])
    return out.strip() if code == 0 and out.strip() else None


def cmd_api_diff(args: argparse.Namespace) -> int:
    ref = args.ref or latest_tag()
    if ref is None:
        return _fail("no tag to compare with: give a ref (aq api-diff HEAD~10)")
    old = api_surface_at(ref)
    if old is None:
        return _fail(f"git has no tests/data/aether_quant_api.json at {ref}")
    report = api_diff(old, api_surface_at(None)) | {"against": ref}
    dev.emit(report, args.json, lambda data: "\n".join([f"against {data['against']}: suggested bump {data['bump']}"]
             + [f"  + {module}.{name}" for module, names in data["added"].items() for name in names]
             + [f"  - {module}.{name}" for module, names in data["removed"].items() for name in names]))
    return dev.EXIT_GATE if report["removed"] else dev.EXIT_OK


def implied_bump(previous: str | None, version: str) -> str:
    def parts(text: str) -> tuple[int, int, int]:
        numbers = [int(part) for part in re.findall(r"\d+", text)[:3]]
        return tuple([*numbers, 0, 0, 0][:3])

    if previous is None:
        return "major"
    old, new = parts(previous), parts(version)
    return "major" if new[0] > old[0] else "minor" if new[1] > old[1] else "patch"


def release_checks(version: str) -> list[dict]:
    import tempfile

    checks = []
    _, porcelain = dev.run_capture(["git", "status", "--porcelain"])
    checks.append(dev._check("clean tree", "ok" if not porcelain.strip() else "fail", f"{len(porcelain.splitlines())} changed file(s)", "commit first"))
    _, branch = dev.run_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    checks.append(dev._check("on main", "ok" if branch.strip() == "main" else "fail", branch.strip(), "git switch main"))
    if dev.shutil.which("gh"):
        _, sha = dev.run_capture(["git", "rev-parse", "HEAD"])
        runs = dev.ci_runs(sha.strip())
        verdict = dev.summarize_runs(runs)["verdict"] if runs is not None else "unknown"
        checks.append(dev._check("CI of HEAD", "ok" if verdict == "green" else "fail", verdict, "aq ci status --watch"))
    changelog = (ROOT_DIR / "docs" / "about" / "changelog.md").read_text(encoding="utf-8") if (ROOT_DIR / "docs" / "about" / "changelog.md").exists() else ""
    checks.append(dev._check("docs changelog", "ok" if changelog.strip() else "fail", "docs/about/changelog.md", "write the highlights"))
    tag = latest_tag()
    old = api_surface_at(tag) if tag else None
    if old is not None:
        bump = api_diff(old, api_surface_at(None))["bump"]
        implied = implied_bump(tag, version)
        order = {"patch": 0, "minor": 1, "major": 2}
        checks.append(dev._check("version vs API", "ok" if order[implied] >= order[bump] else "fail", f"{tag} -> {version} is a {implied} bump; the API needs {bump}", "pick a bigger version"))
    with tempfile.TemporaryDirectory() as folder:
        code, out = dev.run_capture([sys.executable, "-m", "build", "--wheel", "--outdir", folder], timeout=900)
        checks.append(dev._check("wheel builds", "ok" if code == 0 else "fail", out.strip().splitlines()[-1][:160] if out.strip() else "", "python -m pip install build"))
        wheels = sorted(Path(folder).glob("*.whl"))
        if code == 0 and wheels and (ROOT_DIR / "scripts" / "wheel_smoke.py").exists():
            # as CI's wheel-smoke job: the wheel alone, imported from outside the checkout (an editable install would hide gaps)
            site = Path(folder) / "site-packages"
            code, out = dev.run_capture([sys.executable, "-m", "pip", "install", "--no-deps", "--quiet", "--target", str(site), str(wheels[0])], timeout=900)
            if code == 0:
                environment = {**os.environ, "PYTHONPATH": str(site)}
                code, out = dev.run_capture([sys.executable, str(ROOT_DIR / "scripts" / "wheel_smoke.py")], cwd=Path(folder), env=environment, timeout=900)
            checks.append(dev._check("wheel smoke", "ok" if code == 0 else "fail", (out.strip().splitlines() or [""])[-1][:160], "python scripts/wheel_smoke.py, outside the checkout"))
    checks.append(dev._check("SBOM and signing", "manual", "release.yml builds the SBOM, signs and attests on the tag"))
    checks.append(dev._check("tag", "manual", f"git tag {version} && git push origin {version}  (publishes PyPI, Docker, the example models)"))
    return checks


def cmd_release(args: argparse.Namespace) -> int:
    if (missing := dev.needs_checkout()) is not None:
        return missing
    checks = release_checks(args.version)
    marks = {"ok": "✓", "fail": "✗", "manual": "·"}
    dev.emit(checks, args.json, lambda data: "\n".join(f"{marks.get(item['status'], '?')} {item['name']}: {item['detail']}" for item in data))
    return dev.EXIT_GATE if any(check["status"] == "fail" for check in checks) else dev.EXIT_OK


SUBSYSTEMS = ("aether_quant", "analyzer", "audit", "data_pipeline", "evaluation", "execution", "experience", "experts", "features", "inference", "lab", "liquidity", "moe", "monitoring",
              "notifications", "performance", "portfolio", "regime", "retraining", "risk", "topology", "scripts", "tests")


def health_report(root: Path = ROOT_DIR) -> dict:
    """Lines of code per subsystem, tests, coverage per subsystem, the gates' backlogs, open Problems, Dependabot PR count."""
    loc = {name: sum(len(path.read_text(encoding="utf-8", errors="replace").splitlines()) for path in (root / name).rglob("*.py") if "__pycache__" not in path.parts)
           for name in SUBSYSTEMS if (root / name).is_dir()}
    loc["top-level"] = sum(len(path.read_text(encoding="utf-8", errors="replace").splitlines()) for path in root.glob("*.py"))
    tests = sorted((root / "tests").glob("test_*.py"))
    coverage: dict[str, float] = {}
    report_path = root / "coverage-report" / "coverage.json"
    if report_path.exists():
        files = json.loads(report_path.read_text(encoding="utf-8")).get("files", {})
        totals: dict[str, list[int]] = {}
        for name, entry in files.items():
            head = name.replace("\\", "/").split("/")[0] if "/" in name.replace("\\", "/") else "top-level"
            summary = entry.get("summary", {})
            pair = totals.setdefault(head, [0, 0])
            pair[0] += summary.get("covered_lines", 0)
            pair[1] += summary.get("num_statements", 0)
        coverage = {name: round(100.0 * covered / statements, 2) if statements else 100.0 for name, (covered, statements) in sorted(totals.items())}
    backlogs = {}
    for script, pattern in (("formal_inventory.py", r"BACKLOG_CEILING = (\d+)"), ("library_gate.py", r"LEGACY_CEILING = (\d+)")):
        path = root / "scripts" / script
        if path.exists():
            match = re.search(pattern, path.read_text(encoding="utf-8"))
            backlogs[script.removesuffix(".py")] = int(match.group(1)) if match else None
    problems_path = root / "development" / "Problems.md"
    statuses: dict[str, int] = {}
    if problems_path.exists():
        for problem in dev.parse_problems(problems_path.read_text(encoding="utf-8")):
            statuses[problem["status"]] = statuses.get(problem["status"], 0) + 1
    exclusions = len(re.findall(r'^\s*"[A-Z]+\d*",\s*#', (root / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE)) if (root / "pyproject.toml").exists() else None
    return {"loc": loc, "loc_total": sum(loc.values()), "test_files": len(tests), "coverage_by_subsystem": coverage, "backlog_ceilings": backlogs, "problems": statuses,
            "ruff_ignores": exclusions}


def cmd_health(args: argparse.Namespace) -> int:
    import datetime as _datetime

    data = health_report()
    history = ROOT_DIR / "development" / "health_history.jsonl"
    previous = None
    if history.exists():
        lines = [line for line in history.read_text(encoding="utf-8").splitlines() if line.strip()]
        previous = json.loads(lines[-1]) if lines else None
    if args.history:
        row = {"date": _datetime.date.today().isoformat(), "loc_total": data["loc_total"], "test_files": data["test_files"], "backlog_ceilings": data["backlog_ceilings"], "problems": data["problems"]}
        with history.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        data["trend"] = None if previous is None else {"since": previous["date"], "loc_total": data["loc_total"] - previous["loc_total"], "test_files": data["test_files"] - previous["test_files"]}
    dev.emit(data, args.json, lambda value: "\n".join([f"{value['loc_total']} lines of Python, {value['test_files']} test files"]
             + [f"  {name:<14} {lines:>7} lines" + (f"  coverage {value['coverage_by_subsystem'][name]}%" if name in value["coverage_by_subsystem"] else "") for name, lines in sorted(value["loc"].items(), key=lambda item: -item[1])]
             + [f"backlog ceilings: {value['backlog_ceilings']}", f"problems: {value['problems']}", f"ruff ignores: {value['ruff_ignores']}"]
             + ([f"since {value['trend']['since']}: {value['trend']['loc_total']:+} lines, {value['trend']['test_files']:+} test files"] if value.get("trend") else [])))
    return dev.EXIT_OK


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def register(subparsers) -> None:
    p_ = dev._parser
    data = p_(subparsers, "data", "Price data: fetch (keyless), the bundled sample, a first look, an HTML page, file manifests and their diff",
             "aq data sample --out data", "aq data explore data/closes.csv --out explore.html", "aq data diff manifest_pc.json manifest_codespace.json")
    data_sub = data.add_subparsers(dest="data_command", required=True, parser_class=type(data))
    fetch = p_(data_sub, "fetch", "Daily closes of Coinbase coins (public candles, no key), cached", "aq data fetch --coins BTC,ETH,SOL --start 2022-01-01 --out closes.csv")
    fetch.add_argument("--coins", required=True, help="Comma list, e.g. BTC,ETH")
    fetch.add_argument("--start", default="2021-01-01", help="First date (default 2021-01-01)")
    fetch.add_argument("--end", default=None, help="Last date (default: the last closed bar)")
    fetch.add_argument("--out", required=True, help="closes.csv or closes.parquet")
    sample = p_(data_sub, "sample", "Write the bundled sample's closes to DIR/closes.csv", "aq data sample --out data")
    sample.add_argument("--out", required=True, help="A folder")
    info = p_(data_sub, "info", "Shape, dates, calendar, and per ticker its span, missing share and longest gap", "aq data info closes.csv --json")
    info.add_argument("file")
    dev.add_json_flag(info)
    explore = p_(data_sub, "explore", "A one-file HTML page: growth, return moments, correlations, rolling volatility, gaps", "aq data explore closes.csv --out explore.html")
    explore.add_argument("file")
    explore.add_argument("--out", default=None, help="The page (default: FILE with .html)")
    manifest = p_(data_sub, "manifest", "Size and sha256 of every file under a data root", "aq data manifest --root data --out manifest.json")
    manifest.add_argument("--root", default="data", help="The folder (default data)")
    manifest.add_argument("--out", default=None, help="Write here instead of printing")
    diff = p_(data_sub, "diff", "Compare two manifests, or one with a folder (exit 3 on any difference)", "aq data diff manifest_codespace.json --root data")
    diff.add_argument("manifest_a")
    diff.add_argument("manifest_b", nargs="?", default=None)
    diff.add_argument("--root", default="data", help="Without MANIFEST_B: the folder to compare (default data)")
    dev.add_json_flag(diff)
    data.set_defaults(func=cmd_data)

    signal = p_(subparsers, "signal", "Any signal CSV (date, ticker, score): check it, evaluate it on prices, compare signals, neutralize, backtest",
               "aq signal check my_signal.csv", "aq signal eval my_signal.csv --prices closes.csv --html report.html", "aq signal backtest my_signal.csv --cost coinbase")
    signal_sub = signal.add_subparsers(dest="signal_command", required=True, parser_class=type(signal))
    check = p_(signal_sub, "check", "Columns, dates, duplicates, finite scores, names per date (exit 1 on an error)", "aq signal check my_signal.csv")
    check.add_argument("file")
    check.add_argument("--min-names", type=int, default=2, help="Warn on dates with fewer scored names (default 2)")
    dev.add_json_flag(check)
    for name, help_text, example in (("eval", "IC by horizon (HAC t, bootstrap CI), decay, half-life, quintile returns", "aq signal eval s.csv --prices closes.csv"),
                                     ("compare", "Each signal's IC, what is left after the others, their correlation, an equal-weight blend", "aq signal compare a.csv b.csv --prices closes.csv"),
                                     ("neutralize", "Remove each date's cross-sectional beta from the scores", "aq signal neutralize s.csv --prices closes.csv --out s_neutral.csv"),
                                     ("backtest", "A cost-aware long-only book on the scores, with PSR, DSR at N and the minimum track record", "aq signal backtest s.csv --prices closes.csv --top-n 3")):
        sub = p_(signal_sub, name, help_text, example)
        if name == "compare":
            sub.add_argument("files", nargs="+")
        else:
            sub.add_argument("file")
        sub.add_argument("--prices", default=None, help="Closes CSV (default: the bundled sample)")
        sub.add_argument("--horizons", default="5,20", help="Comma list of horizons (default 5,20)")
        sub.add_argument("--min-names", type=int, default=3, help="Names a date needs to count (default 3)")
        if name == "eval":
            sub.add_argument("--html", default=None, metavar="FILE", help="Also write an HTML page")
        if name == "neutralize":
            sub.add_argument("--market", default=None, help="A ticker as the market (default: the equal-weight mean)")
            sub.add_argument("--window", type=int, default=120, help="Beta window in rows (default 120)")
            sub.add_argument("--out", default=None, help="Output CSV (default: FILE_neutral.csv)")
        if name == "backtest":
            sub.add_argument("--top-n", type=int, default=0, help="Hold the top N names equally (default: rank weights over all)")
            sub.add_argument("--cost", default="coinbase", help="coinbase, ib_equity or bps:N (default coinbase)")
            sub.add_argument("--rebalance", type=int, default=5, help="Rebalance every N rows (default 5)")
            sub.add_argument("--ledger", default=None, help="Count this backtest as a trial in this ledger (JSONL)")
        if name != "neutralize":
            dev.add_json_flag(sub)
    signal.set_defaults(func=cmd_signal)

    features = p_(subparsers, "features", "The features the lab builds from closes: list, build a table, inspect one", "aq features list", "aq features inspect ret_20 --html f.html")
    features_sub = features.add_subparsers(dest="features_command", required=True, parser_class=type(features))
    flist = p_(features_sub, "list", "Every buildable feature and the named sets", "aq features list --json")
    flist.add_argument("--all", action="store_true", help="Also name the production-only groups")
    dev.add_json_flag(flist)
    build = p_(features_sub, "build", "Long table date, ticker, features (each uses closes up to its date only)", "aq features build --set core --out features.csv")
    build.add_argument("--prices", default=None, help="Closes CSV (default: the bundled sample)")
    build.add_argument("--set", default="core", help="A set (example, momentum, core, all) or a comma list (default core)")
    build.add_argument("--out", default="features.csv", help="Output CSV (default features.csv)")
    dev.add_dry_run_flag(build)
    finspect = p_(features_sub, "inspect", "One feature: IC by horizon, decay, half-life, IC by year, overlap with the core set", "aq features inspect vol_20")
    finspect.add_argument("name")
    finspect.add_argument("--prices", default=None, help="Closes CSV (default: the bundled sample)")
    finspect.add_argument("--horizons", default="5,20", help="Comma list (default 5,20)")
    finspect.add_argument("--html", default=None, metavar="FILE", help="Also write an HTML page")
    dev.add_json_flag(finspect)
    features.set_defaults(func=cmd_features)

    overfit = p_(subparsers, "overfit", "Overfitting statistics as calculators: PBO, PSR, DSR, the hurdle a winner must beat, haircut Sharpe, minimum track record",
                "aq overfit pbo trials.csv", "aq overfit hurdle --trials 258 --trial-variance 0.3", "aq overfit dsr --returns r.csv --from-ledger")
    overfit_sub = overfit.add_subparsers(dest="overfit_command", required=True, parser_class=type(overfit))
    pbo = p_(overfit_sub, "pbo", "Probability of backtest overfitting over a returns table, one column per trial", "aq overfit pbo trials.csv --blocks 16")
    pbo.add_argument("trials", help="CSV of daily returns, one column per trial")
    pbo.add_argument("--blocks", type=int, default=16, help="CSCV blocks (default 16)")
    psr = p_(overfit_sub, "psr", "Probabilistic Sharpe ratio of a returns series", "aq overfit psr --returns r.csv")
    psr.add_argument("--returns", required=True, help="CSV with a return column")
    psr.add_argument("--benchmark-sharpe", type=float, default=0.0, help="Per-period benchmark Sharpe (default 0)")
    dsr = p_(overfit_sub, "dsr", "Deflated Sharpe ratio of a returns series at N trials", "aq overfit dsr --returns r.csv --trials 258 --trial-variance 0.3")
    dsr.add_argument("--returns", required=True, help="CSV with a return column")
    dsr.add_argument("--trials", type=int, default=None, help="N")
    dsr.add_argument("--trial-variance", type=float, default=None, help="Variance of the trials' annual Sharpes")
    dsr.add_argument("--from-ledger", action="store_true", help="Take N and the variance from the project's trial ledgers")
    dsr.add_argument("--periods", type=float, default=252.0, help="Periods a year (default 252; 365 for crypto)")
    hurdle = p_(overfit_sub, "hurdle", "The Sharpe the best of N unskilled trials is expected to show", "aq overfit hurdle --trials 258 --trial-variance 0.3")
    hurdle.add_argument("--trials", type=int, required=True)
    hurdle.add_argument("--trial-variance", type=float, required=True)
    haircut = p_(overfit_sub, "haircut", "Haircut Sharpe for multiple testing", "aq overfit haircut --sharpe 1.2 --obs 1000 --trials 258")
    haircut.add_argument("--sharpe", type=float, required=True, help="Annual Sharpe")
    haircut.add_argument("--obs", type=int, required=True, help="Observations")
    haircut.add_argument("--trials", type=int, required=True)
    haircut.add_argument("--method", default="bhy", choices=["bonferroni", "holm", "bhy"], help="Adjustment (default bhy)")
    mintrl = p_(overfit_sub, "mintrl", "Minimum track record before the Sharpe beats a target at a confidence", "aq overfit mintrl --returns r.csv")
    mintrl.add_argument("--returns", required=True)
    mintrl.add_argument("--target-sharpe", type=float, default=0.0, help="Annual target (default 0)")
    mintrl.add_argument("--confidence", type=float, default=0.95, help="Default 0.95")
    mintrl.add_argument("--periods", type=int, default=252, help="Periods a year (default 252)")
    for sub in (pbo, psr, dsr, hurdle, haircut, mintrl):
        dev.add_json_flag(sub)
    overfit.set_defaults(func=cmd_overfit)

    lab = p_(subparsers, "lab", "The model lab: create, train, evaluate, compare, sweep, explain and export models (networks or linear) on any dataset",
            "aq lab init mylab", "aq lab new m1 --template multitask", "aq lab train m1 --seeds 1,2,3", "aq lab eval latest --book --html eval.html")
    lab_sub = lab.add_subparsers(dest="lab_command", required=True, parser_class=type(lab))
    init = p_(lab_sub, "init", "Create a lab folder: lab.toml, models/, runs/, data/", "aq lab init mylab")
    init.add_argument("directory")

    def lab_parser(name: str, help_text: str, *examples: str) -> argparse.ArgumentParser:
        sub = p_(lab_sub, name, help_text, *examples)
        sub.add_argument("--lab", default=None, help="The lab folder (default: the nearest lab.toml above here)")
        return sub

    new = lab_parser("new", "A model folder from a template: model.py, config.toml, a shape test", "aq lab new m1 --template tcn")
    new.add_argument("name")
    new.add_argument("--template", required=True, choices=["mlp", "multitask", "tcn", "linear"], help="mlp, multitask, tcn (production networks) or linear (numpy)")
    new.add_argument("--force", action="store_true", help="Overwrite an existing model folder")
    train = lab_parser("train", "Train a model per seed; record the run, its out-of-sample scores, weights, pins and one ledger trial per seed",
                       "aq lab train m1", "aq lab train m1 --seeds 1,2,3 --folds annual", "aq lab train m1 --set train.lr=3e-4 --dry-run")
    train.add_argument("model")
    train.add_argument("--seeds", default=None, help="Comma list (default: the config's)")
    train.add_argument("--folds", default="split", choices=["split", "annual"], help="split: train/validation/backtest; annual: an expanding walk-forward by year")
    train.add_argument("--set", action="append", metavar="KEY=VALUE", help="Override the config for this run, e.g. train.lr=3e-4 (repeatable)")
    train.add_argument("--resume", nargs="?", const="latest", default=None, metavar="RUN_ID", help="Continue a stopped run")
    train.add_argument("--engine", default="lab", choices=["lab", "production"], help="production: the real trainers on the project dataset (source checkout)")
    train.add_argument("--production-kind", default="multitask", choices=["multitask", "tcn"], help="With --engine production: which trainer")
    train.add_argument("--objective", default=None, help="With --engine production: the ranking objective")
    train.add_argument("--memory-profile", default="standard", choices=["standard", "low"], help="With --engine production: the trainer's profile")
    train.add_argument("--project-ledger", action="store_true", help="Also count the trials in the project's ledger and seal the project's holdout window")
    dev.add_dry_run_flag(train)
    dev.add_json_flag(train)
    runs = lab_parser("runs", "Every run, newest first: status, model, IC with its seed spread, N", "aq lab runs --json")
    dev.add_json_flag(runs)
    show = lab_parser("show", "One run's record", "aq lab show latest")
    show.add_argument("run", help="A run id, a unique prefix, or latest")
    dev.add_json_flag(show)
    evaluate = lab_parser("eval", "IC by split and year, decay, half-life, quintiles, the overfit gap, and with --book a cost-aware book judged at N",
                          "aq lab eval latest --book", "aq lab eval latest --html eval.html")
    evaluate.add_argument("run")
    evaluate.add_argument("--book", action="store_true", help="Also a quintile long-short book after costs, with PSR and DSR at N")
    evaluate.add_argument("--cost-bps", type=float, default=10.0, help="Per-side cost for --book (default 10)")
    evaluate.add_argument("--html", default=None, metavar="FILE", help="Also write an HTML page")
    evaluate.add_argument("--holdout", action="store_true", help="Spend the sealed holdout on this run (once, recorded first)")
    evaluate.add_argument("--i-understand-this-spends-it", action="store_true", help="Required with --holdout")
    evaluate.add_argument("--project-ledger", action="store_true", help="With --holdout: the project's holdout ledger")
    dev.add_json_flag(evaluate)
    compare = lab_parser("compare", "A leaderboard on the rows every run scored, each run tested against the best (HAC t, bootstrap CI)",
                         "aq lab compare RUN_A RUN_B --baseline momentum_20")
    compare.add_argument("runs", nargs="+")
    compare.add_argument("--baseline", default=None, help="Add a baseline: momentum_20, momentum_60, reversal_5 or a feature column")
    compare.add_argument("--html", default=None, metavar="FILE", help="Also write an HTML page")
    dev.add_json_flag(compare)
    card = lab_parser("card", "A Markdown model card from the run's own numbers", "aq lab card latest --out MODEL_CARD.md")
    card.add_argument("run")
    card.add_argument("--out", default=None, help="Default: the run's MODEL_CARD.md")
    sweep = lab_parser("sweep", "Train every grid point (each a counted trial, failures too), resumable, then the sweep's PBO",
                       'aq lab sweep m1 --grid "lr=1e-3,3e-4 hidden=[64],[128]"', 'aq lab sweep m1 --grid "dropout=0,0.1,0.2" --random 2 --max-trials 50')
    sweep.add_argument("model")
    sweep.add_argument("--grid", required=True, help="Space-separated key=v1,v2 items")
    sweep.add_argument("--random", type=int, default=None, metavar="K", help="Only K points drawn at random")
    sweep.add_argument("--seed", type=int, default=7, help="The draw's seed (default 7)")
    sweep.add_argument("--max-trials", type=int, default=None, help="Refuse a sweep that would push N past this")
    sweep.add_argument("--project-ledger", action="store_true", help="Also count the trials in the project's ledger")
    dev.add_json_flag(sweep)
    for name, help_text, example in (("explain", "Out-of-sample permutation importance per feature and group, and each feature's own IC", "aq lab explain latest"),
                                     ("ablate", "Retrain without each feature group; the IC each group carries", "aq lab ablate latest"),
                                     ("seeds", "Retrain with N seeds; IC mean, spread and range (flags an unstable model)", "aq lab seeds latest --seeds 5")):
        sub = lab_parser(name, help_text, example)
        sub.add_argument("run")
        if name == "seeds":
            sub.add_argument("--seeds", type=int, default=5, help="How many seeds (default 5)")
        if name != "explain":
            sub.add_argument("--project-ledger", action="store_true", help="Also count the trials in the project's ledger")
        dev.add_json_flag(sub)
    export = lab_parser("export", "Package a run as an aq models zip (numpy forward pass, no torch to score it)", "aq lab export latest --name my-model")
    export.add_argument("run")
    export.add_argument("--name", required=True, help="The model's name for aq models")
    export.add_argument("--out", default=None, help="The zip (default: LAB/NAME.zip)")
    dev.add_json_flag(export)
    lab.set_defaults(func=cmd_lab)

    dataset = p_(subparsers, "dataset", "Lab datasets: build one from closes (features, rank targets, purged splits), describe one, audit it for leakage",
                "aq dataset build --prices closes.csv --out data/dataset.csv", "aq dataset info data/dataset.csv", "aq dataset leakage data/dataset.csv")
    dataset_sub = dataset.add_subparsers(dest="dataset_command", required=True, parser_class=type(dataset))
    dbuild = p_(dataset_sub, "build", "Features, forward rank targets and split labels in the production dataset's columns", "aq dataset build --features core --targets 5,20 --out d.csv")
    dbuild.add_argument("--prices", default=None, help="Closes CSV (default: the bundled sample)")
    dbuild.add_argument("--features", default="core", help="A set or comma list (default core; aq features list)")
    dbuild.add_argument("--targets", default="5,20", help="Comma list of horizons (default 5,20)")
    dbuild.add_argument("--splits", default=None, help="NAME:START..END,... (default 60/20/20 by date); a holdout split is sealed")
    dbuild.add_argument("--out", default="dataset.csv", help="Output CSV (default dataset.csv)")
    dev.add_dry_run_flag(dbuild)
    dev.add_json_flag(dbuild)
    dinfo = p_(dataset_sub, "info", "Rows, dates, tickers, splits, features with their missing share, targets, sealed rows", "aq dataset info d.csv --json")
    dinfo.add_argument("file")
    dev.add_json_flag(dinfo)
    leak = p_(dataset_sub, "leakage", "Tail NaN, label shuffle, single-feature IC, asset prior (exit 3 when something is flagged)", "aq dataset leakage d.csv")
    leak.add_argument("file")
    leak.add_argument("--target", default="target_rank_20d", help="Default target_rank_20d")
    dev.add_json_flag(leak)
    dataset.set_defaults(func=cmd_dataset)

    stack = p_(subparsers, "stack", "The installed model stack (owner research): what is installed, how its IC decays by class/year, what it uses, a lab baseline",
              "aq stack inspect", "aq stack decay --by class --html decay.html", "aq stack lab-baseline --lab mylab")
    stack_sub = stack.add_subparsers(dest="stack_command", required=True, parser_class=type(stack))
    sinspect = p_(stack_sub, "inspect", "Models, heads with their validation/backtest IC, inputs, pins", "aq stack inspect --json")
    sinspect.add_argument("--ml-dir", default=None, help="Another model folder, e.g. ml/versions/<id>")
    dev.add_json_flag(sinspect)
    for name, help_text, example in (("decay", "Rolling and grouped IC of the live blend, with its half-life (never the holdout)", "aq stack decay --by year"),
                                     ("attrib", "Permutation importance of the inputs per asset class", "aq stack attrib --max-dates 40"),
                                     ("lab-baseline", "Register the installed stack's scores as a lab run, for aq lab compare", "aq stack lab-baseline --lab mylab")):
        sub = p_(stack_sub, name, help_text, example)
        sub.add_argument("--ml-dir", default=None, help="Another model folder")
        sub.add_argument("--head", default="rank_20d", help="Target head (default rank_20d)")
        sub.add_argument("--split", default=None, choices=["train", "validation", "backtest"], help="One split (default validation and backtest)")
        sub.add_argument("--max-dates", type=int, default=None, help="Only the last N dates (a small machine)")
        if name == "decay":
            sub.add_argument("--by", default="class", choices=["class", "year", "split"], help="Group by (default class)")
            sub.add_argument("--window", type=int, default=60, help="Rolling window in dates (default 60)")
            sub.add_argument("--html", default=None, metavar="FILE", help="Also write an HTML page")
        if name == "attrib":
            sub.add_argument("--max-features", type=int, default=30, help="At most this many inputs (default 30)")
        if name == "lab-baseline":
            sub.add_argument("--lab", default=None, help="The lab folder")
        else:
            dev.add_json_flag(sub)
    stack.set_defaults(func=cmd_stack)

    trials = p_(subparsers, "trials", "The trial ledgers: N, the deflated-Sharpe hurdle at N, the trials, adding one", "aq trials count", "aq trials dsr --returns r.csv")
    trials_sub = trials.add_subparsers(dest="trials_command", required=True, parser_class=type(trials))
    tcount = p_(trials_sub, "count", "N and where it comes from", "aq trials count --json")
    tlist = p_(trials_sub, "list", "The last trials of every ledger", "aq trials list --phase v6610 --limit 20")
    tlist.add_argument("--phase", default=None, help="Only ledgers whose path contains this")
    tlist.add_argument("--limit", type=int, default=50, help="At most this many (default 50)")
    tdsr = p_(trials_sub, "dsr", "The Sharpe a new candidate must beat at the current N, and a returns series' DSR", "aq trials dsr --returns r.csv --periods 365")
    tdsr.add_argument("--window", default=None, help="Only this window's trials for the variance")
    tdsr.add_argument("--returns", default=None, help="CSV with a return column")
    tdsr.add_argument("--periods", type=float, default=252.0, help="Periods a year (default 252)")
    tadd = p_(trials_sub, "add", "Record a manual trial (it counts toward N when its role is candidate)", "aq trials add --trial-id my_idea --role candidate --sharpe 0.4 --obs 500")
    tadd.add_argument("--trial-id", required=True)
    tadd.add_argument("--role", required=True, choices=["candidate", "verification", "placebo", "plumbing"])
    tadd.add_argument("--sharpe", type=float, required=True, help="Annualised Sharpe")
    tadd.add_argument("--obs", type=int, required=True, help="Observations")
    tadd.add_argument("--track", default="manual", help="Default manual")
    tadd.add_argument("--window", default="manual", help="The window it was judged on (default manual)")
    tadd.add_argument("--note", default=None)
    tadd.add_argument("--ledger", default=None, help="Default ml/evaluation/v671/trial_ledger.jsonl")
    dev.add_dry_run_flag(tadd)
    for sub in (tcount, tlist, tdsr):
        sub.add_argument("--evaluation-dir", default=None, help="Default ml/evaluation")
        dev.add_json_flag(sub)
    trials.set_defaults(func=cmd_trials)

    runs_parser = p_(subparsers, "runs", "Lean runs in backtests/: list them, show one with its engine-log verdict, diff two with their frozen configs",
                    "aq runs list", "aq runs show 2026-11-20_12-07-55", "aq runs diff RUN_A RUN_B")
    runs_sub = runs_parser.add_subparsers(dest="runs_command", required=True, parser_class=type(runs_parser))
    rlist = p_(runs_sub, "list", "Newest first: Sharpe, net profit, drawdown, orders, the README pin, a frozen config", "aq runs list --limit 5")
    rlist.add_argument("--limit", type=int, default=15, help="Default 15")
    dev.add_json_flag(rlist)
    rshow = p_(runs_sub, "show", "Every statistic of one run and its engine-log verdict (rule 7)", "aq runs show 2026-11-20_12-07-55")
    rshow.add_argument("run")
    dev.add_json_flag(rshow)
    rdiff = p_(runs_sub, "diff", "The statistics that differ, and the configs' leaf diff", "aq runs diff A B --json")
    rdiff.add_argument("run_a")
    rdiff.add_argument("run_b")
    dev.add_json_flag(rdiff)
    runs_parser.set_defaults(func=cmd_runs)

    apid = p_(subparsers, "api-diff", "The library's public names added and removed since a tag, and the semver bump that implies (exit 3 on a removal)",
             "aq api-diff", "aq api-diff v6.6.0 --json")
    apid.add_argument("ref", nargs="?", default=None, help="A tag or commit (default: the latest tag)")
    dev.add_json_flag(apid)
    apid.set_defaults(func=cmd_api_diff)

    release = p_(subparsers, "release", "Before tagging: tree, branch, CI, changelog, version against the API, wheel build and smoke (never tags)",
                "aq release check v6.7.1")
    release_sub = release.add_subparsers(dest="release_command", required=True, parser_class=type(release))
    rcheck = p_(release_sub, "check", "Every pre-tag check (exit 3 on a failure)", "aq release check v6.7.1 --json")
    rcheck.add_argument("version")
    dev.add_json_flag(rcheck)
    release.set_defaults(func=cmd_release)

    health = p_(subparsers, "health", "Maintainer dashboard: code size, tests, coverage per subsystem, gate ceilings, Problems, with a trend", "aq health", "aq health --history")
    health.add_argument("--history", action="store_true", help="Append today's row to development/health_history.jsonl and show the change")
    dev.add_json_flag(health)
    health.set_defaults(func=cmd_health)
