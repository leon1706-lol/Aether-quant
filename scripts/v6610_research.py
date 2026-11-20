"""V6.6.10: the multi-asset push, from rules to the 70/30 decision (R-LOSS1, R-ALPHA1, R-BOOK2, R-INSTALL3, R-FLIP1).
The rules and verdicts live in `evaluation/multi_asset_round.py`; this script only reads and writes the evidence files.

    python scripts/v6610_research.py rules                  # once: rules.json and its hash (then scripts/vault_record.py)
    python scripts/v6610_research.py loss-train --variant L2 [--seed 0]   # R-LOSS1: one variant's sequence model (low profile, resumable)
    python scripts/v6610_research.py loss-score --variant L2 [--seed 0]   # its per-class validation IC, a ledger row
    python scripts/v6610_research.py loss-gate              # loss_scores.json (+ loss_verification.json) -> loss_verdict.json
    python scripts/v6610_research.py alpha --scores ml_a1=FILE ...   # R-ALPHA1: alpha_behaviour.json on the selection window
    python scripts/v6610_research.py g7-scores              # R-INSTALL3: the retrained models' scores on the verification window
    python scripts/v6610_research.py install3-ic            # ml_a1 of the retrained against the installed models -> retrain_compare.json
    python scripts/v6610_research.py book2-rules            # R-BOOK2's list from R-ALPHA1, written once (then the vault) before any score
    python scripts/v6610_research.py book2 score|placebo|gate|pbo|report|freeze   # R-BOOK2's stages on g0007's walk-forward scores
    python scripts/v6610_research.py bt-r1                  # BT-R1: the shipped blend (b03 unchanged) on the retrained scores + its run config
    python scripts/v6610_research.py install3 --new-ic X --installed-ic Y --lean-stats s.json --completed --log-clean
    python scripts/v6610_research.py flip --survivor ID --holdout h.json --lean-stats s.json --completed --log-clean --compare-report c.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation import model_book_round as rnd  # noqa: E402
from evaluation import multi_asset_round as mar  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v6610"


def cmd_rules(args) -> int:
    digest = rnd.write_rules(OUT, mar.rules_payload(written=datetime.date.today().isoformat()))
    print(f"rules.json written; sha256 {digest}")
    return 0


def cmd_loss_gate(args) -> int:
    rnd.check_rules(OUT)
    scores = rnd.read_json(OUT / "loss_scores.json", {})
    verification = rnd.read_json(OUT / "loss_verification.json", [])
    verdict = mar.loss_verdict(scores, verification)
    rnd.write_json(OUT / "loss_verdict.json", verdict)
    print(json.dumps(verdict, indent=1))
    return 0


RUN = "v6610_g0007"
LEDGER = OUT / "trial_ledger.jsonl"  # the phase's own ledger, beside v650/v669's


def loss_version(variant: str, seed: int) -> str:
    return f"v6610_loss_{variant}_s{seed}"


def loss_train_command(variant: str, seed: int, *, run: str = RUN, python: str = sys.executable, resume: bool = False) -> list[str]:
    """R-LOSS1: one variant's sequence model on the retrained stack's own dataset, under the low memory profile."""
    base = ROOT / "ml" / "versions" / f"{run}_base"
    return [
        python, str(ROOT / "train_sequence.py"), "--version-id", loss_version(variant, seed), "--dataset-path", str(base / "full_dataset.csv"),
        "--feature-schema-path", str(base / "feature_schema.json"), "--ranking-objective", mar.LOSS_TRIALS[variant], "--seed", str(seed),
        "--memory-profile", "low", "--log-peak-memory", str(OUT / "loss_peaks.jsonl"), *(["--resume"] if resume else []),
    ]


def cmd_loss_train(args) -> int:
    import subprocess

    rnd.check_rules(OUT)
    checkpoint = ROOT / "ml" / "versions" / loss_version(args.variant, args.seed) / "checkpoint.pt"
    return subprocess.run(loss_train_command(args.variant, args.seed, run=args.run, resume=checkpoint.exists()), cwd=str(ROOT), check=False).returncode


def cmd_loss_score(args) -> int:
    """R-LOSS1's score of one trained variant on the validation window, written to loss_scores.json (seed 0) or loss_verification.json
    (the verification seeds), with a ledger row."""
    from evaluation.model_predictions import predict_heads
    from evaluation.trial_ledger import append_trial
    from retraining.slicing import read_csv_float32
    from train import asset_class_by_ticker_from_config

    rnd.check_rules(OUT)
    base = ROOT / "ml" / "versions" / f"{args.run}_base"
    version = ROOT / "ml" / "versions" / loss_version(args.variant, args.seed)
    export = json.loads((version / "sequence_model.json").read_text(encoding="utf-8"))
    schema = json.loads((version / "sequence_feature_schema.json").read_text(encoding="utf-8"))
    frame = read_csv_float32(base / "full_dataset.csv").sort_values(["ticker", "date"]).reset_index(drop=True)
    frame["date"] = frame["date"].astype(str).str[:10]
    mask = (frame["split"] == "validation").to_numpy()
    heads = predict_heads(frame, export, schema["model_input_names"], ["rank_20d"], model_kind="sequence", sequence_feature_schema=schema,
                          configured_window_size=int(schema.get("window_size", 30)), row_mask=mask, batched=True)
    rows = frame.loc[mask, ["date", "ticker", "target_rank_20d"]].rename(columns={"target_rank_20d": "target"})
    rows["prediction"] = heads["rank_20d"][mask]
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    score = mar.loss_score(rows, asset_class_by_ticker_from_config(config))
    role = "candidate" if args.seed == 0 else "verification"
    if args.seed == 0:
        scores = rnd.read_json(OUT / "loss_scores.json", {})
        scores[args.variant] = score
        rnd.write_json(OUT / "loss_scores.json", scores)
    else:
        verification = rnd.read_json(OUT / "loss_verification.json", [])
        rnd.write_json(OUT / "loss_verification.json", [*verification, {**score, "variant": args.variant, "seed": args.seed}])
    append_trial(args.ledger or LEDGER, trial_id=f"v6610_{args.variant}_s{args.seed}", track="R-LOSS1", window="v6610_validation", role=role,
                 annualised_sharpe=None, n_obs=score["dates"], detail={"class_ic": score["class_ic"], "hac_t": score["hac_t"], "phase": "v6610"})
    print(json.dumps({args.variant: score}, indent=1, default=str))
    return 0


def market_beta(known, window: int = 60):
    """Each name's rolling beta to the equal-weight market return, as known at the session."""
    returns = known.pct_change(fill_method=None)
    market = returns.mean(axis=1)
    covariance = returns.rolling(window, min_periods=window).cov(market)
    return covariance.div(market.rolling(window, min_periods=window).var(), axis=0)


def alpha_factors(panel) -> dict:
    """R-ALPHA1's factors: momentum 12-1, low volatility, carry (forex; 0 where a class has none) and market beta."""
    from evaluation.model_book_research import low_volatility_score, momentum_12_1

    known = panel.known
    carry = panel.extras.get("fx_carry")
    carry = (carry.reindex(index=known.index, columns=known.columns) if carry is not None else known * float("nan")).fillna(0.0)
    return {"momentum_12_1": momentum_12_1(known), "low_volatility": low_volatility_score(known), "carry": carry, "market_beta": market_beta(known)}


def score_panel(sources: dict, *, end: str):
    """The research panel (forex on, as the installed config holds it) and each named score file aligned to its sessions through
    `load_score_table`, the one alignment every model-book reader uses. The round context keeps only ml_a1 and the tables built from it."""
    from evaluation import model_book_research as research
    from evaluation.premia_research import build_context

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    config["phase_v2"]["forex_risk"]["enabled"] = True
    panel = build_context(ROOT, config, respect_disabled_classes=True).panel
    sessions, universe = list(panel.known.index), research.universe_tickers(config)
    return panel, {name: research.load_score_table(path, sessions, panel.asset_class, universe=universe, end=end) for name, path in sources.items()}


def cmd_alpha(args) -> int:
    """R-ALPHA1: each score table's alpha report on the selection window (diagnostic: it selects nothing and counts no trial)."""
    from evaluation.alpha_behaviour import alpha_report
    from evaluation.model_book_research import SELECTION

    rnd.check_rules(OUT)
    sources = {name: Path(path) for name, path in (item.split("=", 1) for item in args.scores)}
    panel, tables = score_panel(sources, end=SELECTION[2])
    window = slice(SELECTION[0], SELECTION[2])
    closes = panel.known.loc[window]
    factors = {name: table.loc[window] for name, table in alpha_factors(panel).items()}
    reports = {name: alpha_report(tables[name].loc[window], closes, groups=panel.asset_class, factors=factors, horizon=20) for name in sources}
    rnd.write_json(OUT / "alpha_behaviour.json", reports)
    print(json.dumps({name: {"ic_20": report["term_structure"][20], "half_life": report["half_life_sessions"], "residual_ic": report["residual_ic"]}
                      for name, report in reports.items()}, indent=1, default=str))
    return 0


V669 = ROOT / "ml" / "evaluation" / "v669"
BT_R1 = OUT / "bt_r1"
SCORE_TABLES = ("ml_a1", "ml_a2", "ml_a3")
ROUND_FILES = ("rules.json", "rules.sha256", "freeze.json", "freeze.sha256")


def g7_exports(run: str = RUN) -> dict:
    """The retrained stack's final multitask and sequence models (export, feature schema), as `installed_score_tables` reads them."""
    exports = {}
    for kind, folder, model, schema in (("multitask", "mt", "multitask_model.json", "multitask_feature_schema.json"),
                                        ("sequence", "seq", "sequence_model.json", "sequence_feature_schema.json")):
        version = ROOT / "ml" / "versions" / f"{run}_{folder}"
        exports[kind] = (json.loads((version / model).read_text(encoding="utf-8")), json.loads((version / schema).read_text(encoding="utf-8")))
    return exports


OVERLAP_TOLERANCE = 1e-4  # both files are read as float32


def window_overlap(base, window, names, *, start: str, end: str) -> dict:
    """The proof a window built later (`scripts/splice_holdout_dataset.py --build` with the retrain's own scaler) continues the retrain's
    dataset: on every (date, ticker) both hold in [start, end], each model input agrees within OVERLAP_TOLERANCE. Refuses otherwise."""
    import numpy as np

    keys = ["date", "ticker"]
    left = base[(base["date"] >= start) & (base["date"] <= end)].set_index(keys)[names]
    right = window[(window["date"] >= start) & (window["date"] <= end)].set_index(keys)[names]
    shared = left.index.intersection(right.index)
    if not len(shared):
        raise SystemExit(f"the window file shares no row with the retrain's dataset in {start}..{end}: nothing proves its scaling")
    a, b = left.loc[shared].to_numpy(dtype=float), right.loc[shared].to_numpy(dtype=float)
    both_missing = np.isnan(a) & np.isnan(b)
    gap = np.where(both_missing, 0.0, np.abs(a - b))
    worst = float(np.nanmax(np.where(np.isnan(gap), np.inf, gap)))
    if worst > OVERLAP_TOLERANCE:
        column = names[int(np.argmax(np.nanmax(np.where(np.isnan(gap), np.inf, gap), axis=0)))]
        raise SystemExit(f"the window file differs from the retrain's dataset by {worst} (column {column}) on {len(shared)} shared rows")
    return {"rows": int(len(shared)), "max_abs_diff": worst, "window": [start, end]}


def cmd_g7_scores(args) -> int:
    """R-INSTALL3: the retrained models' score tables on the verification window, defined exactly as the installed models' were (V6.6.9),
    from the retrain's own dataset (its scaler and universe). Written as scores/g7_a1..a3.csv."""
    import pandas as pd

    from evaluation import model_book_research as research
    from evaluation.dataset_io import read_dataset_columns

    rnd.check_rules(OUT)
    exports = g7_exports(args.run)
    names = sorted({name for _export, schema in exports.values() for name in schema["model_input_names"]})
    dataset = read_dataset_columns(ROOT / "ml" / "versions" / f"{args.run}_base" / "full_dataset.csv", ["date", "ticker", *names], start=args.context_start)
    if args.window_dataset:
        window = read_dataset_columns(Path(args.window_dataset), ["date", "ticker", *names], start=args.context_start)
        print(json.dumps({"overlap": window_overlap(dataset, window, names, start=args.check_from, end=args.seam)}))
        dataset = pd.concat([dataset[dataset["date"] <= args.seam], window[window["date"] > args.seam]], ignore_index=True)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    tables = research.installed_score_tables(dataset, exports, start=research.VERIFICATION[0], end=research.VERIFICATION[1], universe=research.universe_tickers(config))
    (OUT / "scores").mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        destination = OUT / "scores" / f"g7_{name[-2:]}.csv"
        table.sort_values(["date", "ticker"]).to_csv(destination, index=False, lineterminator="\n", float_format="%.6f")
        print(f"{destination.name}: {len(table)} rows {table['date'].min()}..{table['date'].max()}, {table['ticker'].nunique()} tickers")
    return 0


def class_mean_ic(diagnostics: dict, horizon: int = 20) -> float | None:
    """R-INSTALL3's number: the mean over the four classes of the non-overlapping rank IC at `horizon`; None when a class has none."""
    values = [diagnostics.get(f"{name}_{horizon}d", {}).get("mean_ic") for name in mar.CLASSES]
    return None if any(value is None for value in values) else float(sum(values) / len(values))


def cmd_install3_ic(args) -> int:
    """R-INSTALL3's first clause: ml_a1 of the retrained models against the installed models' on the verification window, both read through
    the same score-table alignment and the same IC (`rank_ic_diagnostics`, every 20th session). Written to retrain_compare.json."""
    from evaluation import model_book_research as research

    rnd.check_rules(OUT)
    sources = {"g7_a1": OUT / "scores" / "g7_a1.csv", "inst_a1": V669 / "scores" / "inst_a1.csv"}
    panel, tables = score_panel(sources, end=research.VERIFICATION[1])
    report = {}
    for name in sources:
        diagnostics = research.rank_ic_diagnostics(tables[name], panel.known, panel.asset_class, horizons=(5, 20),
                                                   start=research.VERIFICATION[0], end=research.VERIFICATION[1])
        report[name] = {"class_mean_ic_20d": class_mean_ic(diagnostics), "class_mean_ic_5d": class_mean_ic(diagnostics, 5), "diagnostics": diagnostics}
    report["window"] = list(research.VERIFICATION)
    report["new_ic"], report["installed_ic"] = report["g7_a1"]["class_mean_ic_20d"], report["inst_a1"]["class_mean_ic_20d"]
    rnd.write_json(OUT / "retrain_compare.json", report)
    print(json.dumps({"new_ic": report["new_ic"], "installed_ic": report["installed_ic"],
                      "by_class": {name: {key: value["mean_ic"] for key, value in report[name]["diagnostics"].items() if key.endswith("_20d")} for name in sources}}, indent=1))
    return 0


def cmd_bt_r1(args) -> int:
    """BT-R1's weight file and run config: the shipped 70/30 blend, b03 frozen in V6.6.9 and unchanged (its rules and freeze copied with their
    hashes, its share and phase kept), on the retrained models' scores: the walk-forward tables to 2023-06-30, the final models' after it."""
    import hashlib
    import shutil

    from evaluation import model_book_research as research
    from evaluation.premia_research import phase_offsets

    rnd.check_rules(OUT)
    BT_R1.mkdir(parents=True, exist_ok=True)
    for name in ROUND_FILES:
        shutil.copyfile(V669 / name, BT_R1 / name)
    frozen = rnd.check_freeze(BT_R1)
    spec = rnd.candidate_spec(frozen)
    share = float(rnd.read_json(V669 / "blend_blend.json")["model_share"])
    phase_index = phase_offsets(spec.rebalance_every).index(rnd.read_json(V669 / "verification.json")["median_phase"])
    walk = ROOT / "ml" / "cycle" / f"retrain_{args.run}" / "scores"
    sources = {
        name: rnd.combine_score_files(walk / f"{name}.csv", OUT / "scores" / f"g7_{name[-2:]}.csv", OUT / "scores" / f"g7_long_{name[-2:]}.csv",
                                      last_selection=research.SELECTION[2])
        for name in SCORE_TABLES
    }
    context = rnd.load_round_context(ROOT, sources)
    summary = rnd.blend_stage(context, BT_R1, name="blend", start=research.VERIFICATION[0], end=research.VERIFICATION[1], share=share, phase_index=phase_index)
    sys.path.insert(0, str(ROOT / "scripts"))
    from v650_instrument import RUN_CONFIGS, target_path_config

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    base["phase_v2"]["forex_risk"]["enabled"] = True
    base["phase_v2"]["target_weights"]["uses_model"] = True
    weights = BT_R1 / "weights" / "blend.csv"
    config = target_path_config(base, weights_path=weights.relative_to(ROOT).as_posix(), weights_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),
                                window=research.VERIFICATION)
    RUN_CONFIGS.mkdir(parents=True, exist_ok=True)
    (RUN_CONFIGS / "v6610_bt_r1.json").write_text(json.dumps(config, indent=4), encoding="utf-8", newline="\n")
    print(json.dumps({**summary, "run_config": "ml/evaluation/run_configs/v6610_bt_r1.json", "pin_offline_sharpe": rnd.read_json(V669 / "blend_blend.json")["sharpe"]}, indent=1))
    return 0


BOOK2 = OUT / "book2"
BOOK2_CODE_FILES = (
    "portfolio/book_optimizer.py", "portfolio/premia_signals.py", "portfolio/target_weights.py", "portfolio/model_book.py",
    "evaluation/target_weights_engine.py", "evaluation/premia_research.py", "evaluation/model_book_research.py", "evaluation/model_book_round.py",
    "evaluation/multi_asset_round.py", "main.py",
)


def cmd_book2_rules(args) -> int:
    """R-BOOK2's list, written once with its hash before any of its scores (then scripts/vault_record.py). The R-ALPHA1 numbers it was drawn
    from go in with it."""
    alpha = rnd.read_json(OUT / "alpha_behaviour.json")
    if alpha is None:
        raise SystemExit("run `alpha` first: the list is drawn from R-ALPHA1")
    basis = {name: {"ic_20": report["term_structure"]["20"]["mean_ic"], "half_life": report["half_life_sessions"], "residual_ic": report["residual_ic"]["mean_ic"]}
             for name, report in alpha.items()}
    digest = rnd.write_rules(BOOK2, mar.book2_rules_payload(written=datetime.date.today().isoformat(), alpha=basis))
    print(f"book2/rules.json written; sha256 {digest}")
    return 0


def book2_context(run: str = RUN):
    """The selection-window context on the kept model's walk-forward scores (R-LOSS1 kept L0: g0007's own)."""
    from evaluation import model_book_research as research

    walk = ROOT / "ml" / "cycle" / f"retrain_{run}" / "scores"
    return rnd.load_round_context(ROOT, {name: walk / f"{name}.csv" for name in SCORE_TABLES}, end=research.SELECTION[2])


def cmd_book2(args) -> int:
    """R-BOOK2's stages over its own list: score (controls too), placebo, gate, pbo, report, freeze (a survivor only)."""
    pool, controls = mar.book2_trials(), mar.book2_controls()
    stage = args.stage
    if stage == "score":
        rnd.score_stage(book2_context(args.run), BOOK2, specs=[*pool, *controls], control_ids=[spec.id for spec in controls], ids=args.only, force=args.force)
    elif stage == "placebo":
        rnd.placebo_stage(book2_context(args.run), BOOK2, draws=args.draws, only=args.only, force=args.force, pool=pool)
    elif stage == "gate":
        print(json.dumps(rnd.gate_stage(BOOK2, pool=pool), indent=1))
    elif stage == "pbo":
        print(json.dumps(rnd.pbo_stage(BOOK2, root=ROOT, pool=pool), indent=1))
    elif stage == "report":
        print(json.dumps({key: value for key, value in rnd.report_stage(BOOK2, name="r_book2.json", survivors_only=True).items() if key != "trials"}, indent=1, default=str))
    else:
        path, digest = rnd.freeze_stage(BOOK2, root=ROOT, code_files=BOOK2_CODE_FILES, report_name="r_book2.json", specs=[*pool, *controls])
        print(f"{path.name} written; sha256 {digest}")
    return 0


def _lean(args) -> dict | None:
    """The Lean run's statistics file {"sharpe", "volatility", "max_drawdown"} with the two facts its engine log shows."""
    if not args.lean_stats:
        return None
    return {**rnd.read_json(Path(args.lean_stats)), "completed": args.completed, "log_clean": args.log_clean}


def cmd_install3(args) -> int:
    rnd.check_rules(OUT)
    verdict = mar.install3_verdict(new_ic=args.new_ic, installed_ic=args.installed_ic, lean=_lean(args))
    rnd.write_json(OUT / "r_install3.json", verdict)
    print(json.dumps(verdict, indent=1))
    return 0


def cmd_flip(args) -> int:
    rnd.check_rules(OUT)
    holdout = rnd.read_json(Path(args.holdout)) if args.holdout else None
    compare = rnd.read_json(Path(args.compare_report)) if args.compare_report else None
    parity = rnd.lean_summary(compare, completed=args.completed, engine_log_clean=args.log_clean) if compare else None
    verdict = mar.flip_verdict(survivor=args.survivor, holdout=holdout, lean=_lean(args), parity=parity)
    rnd.write_json(OUT / "r_flip1.json", verdict)
    print(json.dumps(verdict, indent=1))
    return 0


def _lean_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lean-stats", default=None, help="the Lean run's {sharpe, volatility, max_drawdown}")
    parser.add_argument("--completed", action="store_true")
    parser.add_argument("--log-clean", action="store_true")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rules")
    commands.add_parser("loss-gate")
    for name in ("loss-train", "loss-score"):
        loss = commands.add_parser(name)
        loss.add_argument("--variant", required=True, choices=sorted(mar.LOSS_TRIALS))
        loss.add_argument("--seed", type=int, default=0)
        loss.add_argument("--run", default=RUN, help="the stack retrain whose dataset the variants train on")
        loss.add_argument("--ledger", default=None, help=argparse.SUPPRESS)
    alpha = commands.add_parser("alpha")
    alpha.add_argument("--scores", nargs="+", required=True, metavar="NAME=FILE", help="score tables (date,ticker,score), e.g. ml_a1=ml/cycle/retrain_<id>/scores/ml_a1.csv")
    g7 = commands.add_parser("g7-scores")
    g7.add_argument("--context-start", default="2023-03-01", help="the first dataset row read (a sequence window reads 30 bars before its row)")
    g7.add_argument("--run", default=RUN)
    g7.add_argument("--window-dataset", default=None, help="rows after --seam, built with the retrain's own scaler (splice_holdout_dataset.py --build --scaler-stats ...)")
    g7.add_argument("--seam", default="2025-06-29", help="the retrain dataset's last date; the window file's rows after it are used")
    g7.add_argument("--check-from", default="2025-06-02", help="the overlap guard compares both files from here to --seam")
    commands.add_parser("install3-ic")
    commands.add_parser("book2-rules")
    book2 = commands.add_parser("book2")
    book2.add_argument("stage", choices=["score", "placebo", "gate", "pbo", "report", "freeze"])
    book2.add_argument("--only", nargs="*", default=None)
    book2.add_argument("--force", action="store_true")
    book2.add_argument("--draws", type=int, default=100)
    book2.add_argument("--run", default=RUN)
    bt = commands.add_parser("bt-r1")
    bt.add_argument("--run", default=RUN)
    install3 = commands.add_parser("install3")
    install3.add_argument("--new-ic", type=float, default=None)
    install3.add_argument("--installed-ic", type=float, default=None)
    _lean_flags(install3)
    flip = commands.add_parser("flip")
    flip.add_argument("--survivor", default=None)
    flip.add_argument("--holdout", default=None)
    flip.add_argument("--compare-report", default=None, help="scripts/v650_instrument.py compare's report (Lean against the engine)")
    _lean_flags(flip)
    args = parser.parse_args(argv)
    handler = {"rules": cmd_rules, "loss-gate": cmd_loss_gate, "loss-train": cmd_loss_train, "loss-score": cmd_loss_score, "alpha": cmd_alpha, "install3": cmd_install3, "flip": cmd_flip,
               "g7-scores": cmd_g7_scores, "install3-ic": cmd_install3_ic, "bt-r1": cmd_bt_r1, "book2-rules": cmd_book2_rules, "book2": cmd_book2}[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
