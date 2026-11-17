"""V6.6.9: the multi-asset model book, from rules to install (R-BOOK1, R-MIX1, R-INSTALL2). Logic lives in `evaluation/model_book_round.py`.

    python scripts/v669_book.py rules                 # once: writes rules.json and its hash (then record it: scripts/vault_record.py)
    python scripts/v669_book.py score [--only b02 ..] # 18 trials and 2 controls on the selection window
    python scripts/v669_book.py placebo --draws 100   # only for the trials that pass the Sharpe clauses
    python scripts/v669_book.py gate | pbo | diagnostics | report
    python scripts/v669_book.py freeze                # the candidate, before any row after 2023-06-30 exists
    python scripts/v669_book.py scores [--through D]  # the installed models' scores, 2023-07-01..2026-11-02 or D (needs the freeze)
    python scripts/v669_book.py verify                # the frozen candidate on the verification window
    python scripts/v669_book.py blend                 # blend.csv and blend_long.csv with the crypto sleeve
    python scripts/v669_book.py configs               # the three Lean run configs (v669_bt_a, _b, _l)
    python scripts/v669_book.py candidate [--out f]   # the blended book's definition (the in-Lean parity run reads it)
    python scripts/v669_book.py judge --lean-report r.json --completed --log-clean
    python scripts/v669_book.py install               # copies blend.csv into place when R-INSTALL2 says so
    python scripts/v669_book.py register              # adds the model book to the generations' registry as g0006
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation import model_book_research as research  # noqa: E402
from evaluation import model_book_round as rnd  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v669"
SELECTION_SCORES = ROOT / "ml" / "evaluation" / "v650" / "scores"
SCORES = OUT / "scores"
TABLES = ("ml_a1", "ml_a2", "ml_a3")
CODE_FILES = (
    "portfolio/book_optimizer.py", "portfolio/premia_signals.py", "portfolio/target_weights.py", "portfolio/model_book.py",
    "evaluation/target_weights_engine.py", "evaluation/premia_research.py", "evaluation/model_book_research.py", "evaluation/model_book_round.py", "main.py",
    "ml/artifact_pins.json",
)


def selection_context():
    return rnd.load_round_context(ROOT, {name: SELECTION_SCORES / f"{name}.csv" for name in TABLES}, end=research.SELECTION[2])


def long_sources() -> dict[str, Path]:
    """Score files over both windows: the walk-forward tables up to the seam, the installed models' rows after it."""
    paths = {}
    for name in TABLES:
        paths[name] = rnd.combine_score_files(
            SELECTION_SCORES / f"{name}.csv", SCORES / f"inst_{name[-2:]}.csv", SCORES / f"long_{name[-2:]}.csv", last_selection=research.SELECTION[2],
        )
    return paths


def cmd_rules(args) -> int:
    digest = rnd.write_rules(OUT, rnd.rules_payload(written=datetime.date.today().isoformat()))
    print(f"rules.json written; sha256 {digest}")
    return 0


def cmd_score(args) -> int:
    rnd.score_stage(selection_context(), OUT, ids=args.only, force=args.force)
    return 0


def cmd_placebo(args) -> int:
    rnd.placebo_stage(selection_context(), OUT, draws=args.draws, only=args.only, force=args.force, suffix=args.suffix, modes=args.modes)
    return 0


def cmd_gate(args) -> int:
    print(json.dumps(rnd.gate_stage(OUT), indent=1))
    return 0


def cmd_pbo(args) -> int:
    print(json.dumps(rnd.pbo_stage(OUT, root=ROOT), indent=1))
    return 0


def cmd_diagnostics(args) -> int:
    rnd.diagnostics_stage(selection_context(), OUT)
    return 0


def cmd_report(args) -> int:
    print(json.dumps(rnd.report_stage(OUT)["install"], indent=1))
    return 0


def cmd_freeze(args) -> int:
    path, digest = rnd.freeze_stage(OUT, root=ROOT, code_files=CODE_FILES)
    print(f"{path.name} written; sha256 {digest}")
    return 0


def cmd_scores(args) -> int:
    """The installed models' scores for the verification window. Refuses without a recorded freeze and on any model-file mismatch."""
    from evaluation.dataset_io import read_dataset_columns
    from retraining.artifact_pins import artifact_problems

    rnd.check_freeze(OUT)
    problems = artifact_problems(ROOT / "ml", ROOT / "ml" / "artifact_pins.json")
    if problems:
        raise SystemExit(f"the installed model files are not the pinned ones: {problems}")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    exports = {}
    names = set()
    for kind, (model, schema) in {"multitask": ("multitask_model.json", "multitask_feature_schema.json"), "sequence": ("sequence_model.json", "sequence_feature_schema.json")}.items():
        exports[kind] = (json.loads((ROOT / "ml" / model).read_text(encoding="utf-8")), json.loads((ROOT / "ml" / schema).read_text(encoding="utf-8")))
        names.update(exports[kind][1]["model_input_names"])
    # the sequence windows read 30 bars before the first scored row; start the read a quarter earlier
    dataset = read_dataset_columns(ROOT / "ml" / "datasets" / "full_dataset.csv", ["date", "ticker", *sorted(names)], start=args.context_start)
    tables = research.installed_score_tables(dataset, exports, start=research.VERIFICATION[0], end=args.through or research.VERIFICATION[1], universe=research.universe_tickers(config))
    SCORES.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.sort_values(["date", "ticker"]).to_csv(SCORES / f"{name}.csv", index=False, lineterminator="\n", float_format="%.6f")
        print(f"{name}: {len(table)} rows {table['date'].min()}..{table['date'].max()}, {table['ticker'].nunique()} tickers")
    long_sources()
    return 0


def cmd_verify(args) -> int:
    context = rnd.load_round_context(ROOT, long_sources())
    print(json.dumps({key: value for key, value in rnd.verify_stage(context, OUT).items() if key != "phases"}, indent=1))
    return 0


def cmd_blend(args) -> int:
    from evaluation.premia_research import phase_offsets

    frozen = rnd.check_freeze(OUT)
    verification = rnd.read_json(OUT / "verification.json")
    spec = rnd.candidate_spec(frozen)
    phase_index = phase_offsets(spec.rebalance_every).index(verification["median_phase"])
    if frozen["survivor"]:
        selection = rnd.read_json(OUT / "selection_scores.json")
        crypto = rnd.read_json(OUT / "crypto_volatility.json", {"volatility": 0.07})["volatility"]
        share = rnd.inverse_vol_share(float(selection[frozen["candidate"]]["volatility"]), float(crypto))
    else:
        share = research.NON_SURVIVOR_SHARE
    context = rnd.load_round_context(ROOT, long_sources())
    for name, window in (("blend", research.VERIFICATION), ("blend_long", (research.SELECTION[0], research.VERIFICATION[1]))):
        print(json.dumps(rnd.blend_stage(context, OUT, name=name, start=window[0], end=window[1], share=share, phase_index=phase_index), indent=1))
    return 0


def cmd_configs(args) -> int:
    """The Lean run configs: the model book alone and the blend over the verification window, and the blend over the long window. Each is the shipped
    config with the target-weights path on that file, `uses_model` and forex on (what the install sets), and the risk settings of the earlier runs."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from v650_instrument import RUN_CONFIGS, target_path_config

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    base["phase_v2"]["forex_risk"]["enabled"] = True
    base["phase_v2"]["target_weights"]["uses_model"] = True
    runs = {
        "v669_bt_a": ("model_book.csv", research.VERIFICATION), "v669_bt_b": ("blend.csv", research.VERIFICATION),
        "v669_bt_l": ("blend_long.csv", (research.SELECTION[0], research.VERIFICATION[1])),
    }
    RUN_CONFIGS.mkdir(parents=True, exist_ok=True)
    for name, (file, window) in runs.items():
        weights = OUT / "weights" / file
        config = target_path_config(base, weights_path=weights.relative_to(ROOT).as_posix(), weights_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(), window=window)
        (RUN_CONFIGS / f"{name}.json").write_text(json.dumps(config, indent=4), encoding="utf-8", newline="\n")
        print(f"{name}: {file} {window[0]}..{window[1]}")
    # the parity run (R-LEAN23): the same book, computed inside Lean from the models, over the same window
    parity = target_path_config(base, weights_path="", weights_sha256="", window=research.VERIFICATION)
    parity["phase_v2"]["target_weights"]["source"] = "model_book"
    parity["phase_v2"]["model_book"] = {"candidate_path": "ml/evaluation/v669/candidate_blend.json", "artifact_pins_path": "ml/artifact_pins.json"}
    (RUN_CONFIGS / "v669_bt_p.json").write_text(json.dumps(parity, indent=4), encoding="utf-8", newline="\n")
    print("v669_bt_p: computed in Lean from the models, " + research.VERIFICATION[0] + ".." + research.VERIFICATION[1])
    return 0


def cmd_judge(args) -> int:
    lean = None
    if args.lean_report:
        lean = rnd.lean_summary(json.loads(Path(args.lean_report).read_text(encoding="utf-8")), completed=args.completed, engine_log_clean=args.log_clean)
    print(json.dumps(rnd.judge_stage(OUT, lean=lean), indent=1))
    return 0


def _candidate_payload() -> dict:
    frozen = rnd.check_freeze(OUT)
    share = rnd.read_json(OUT / "blend_blend.json")["model_share"]
    pinned = rnd.read_json(OUT / "pinned_run.json", {}).get("run")
    return rnd.candidate_file(frozen, rnd.read_json(OUT / "verification.json"), share=share, pinned_run=pinned)


def cmd_candidate(args) -> int:
    """Writes the blended book's definition (both generations, the sizing, the phases) to `--out`: the file the in-Lean parity run and the daily tool read."""
    destination = Path(args.out) if args.out else OUT / "candidate_blend.json"
    destination.write_text(json.dumps(_candidate_payload(), indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"candidate written to {destination}")
    return 0


def cmd_register(args) -> int:
    """Registers the model book as generation g0006: installed if R-INSTALL2 says so, else a shadow observer."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import datetime

    from cycle_retrain import PROCEDURES, procedure_sha256

    frozen = rnd.check_freeze(OUT)
    verdict = rnd.read_json(OUT / "r_install2.json", {})
    stack = PROCEDURES["stack"]
    sha = procedure_sha256("stack", stack, b"".join((ROOT / trainer).read_bytes() for trainer in stack["trainers"]))
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    result = rnd.register_generation(
        ROOT / "ml" / "generations" / "registry.json", ROOT / "ml" / "generations" / "lifecycle.jsonl", frozen=frozen,
        freeze_sha256=(OUT / "freeze.sha256").read_text(encoding="utf-8").strip(), installed=bool(verdict.get("install")), procedure_sha256=sha,
        born=now.date().isoformat(), created_at=now.isoformat(),
    )
    if result["added"] and verdict.get("install"):
        share = rnd.read_json(OUT / "blend_blend.json")["model_share"]
        rnd.set_installed_shares(ROOT / "ml" / "generations" / "policy.json", {"g0001": round(1.0 - share, 10), rnd.GENERATION_ID: share})
    print(json.dumps(result))
    return 0


def cmd_install(args) -> int:
    verdict = rnd.read_json(OUT / "r_install2.json")
    if not verdict or not verdict["install"]:
        print(f"not installed: failed clauses {verdict['failed'] if verdict else 'no verdict yet'}")
        return 1
    source = OUT / "weights" / "blend.csv"
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    config_path = ROOT / "config.json"
    before = config_path.read_bytes()
    after = rnd.install_config_text(before.decode("utf-8"), weights_sha256=sha)
    shutil.copyfile(source, ROOT / "ml" / "target_weights.csv")
    config_path.write_bytes(after.encode("utf-8"))
    candidate_path = ROOT / "ml" / "target_weights_candidate.json"
    if candidate_path.exists():
        shutil.copyfile(candidate_path, OUT / "candidate_before_install.json")
    candidate_path.write_text(json.dumps(_candidate_payload(), indent=1) + "\n", encoding="utf-8", newline="\n")
    from retraining.artifact_pins import write_artifact_pins

    write_artifact_pins(ROOT / "ml", ROOT / "ml" / "artifact_pins.json")
    print(f"config.json sha256 {hashlib.sha256(before).hexdigest()[:16]} -> {hashlib.sha256(after.encode('utf-8')).hexdigest()[:16]}; weights sha256 {sha}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rules")
    commands.add_parser("configs")
    commands.add_parser("register")
    candidate = commands.add_parser("candidate")
    candidate.add_argument("--out", default=None)
    score = commands.add_parser("score")
    score.add_argument("--only", nargs="*", default=None)
    score.add_argument("--force", action="store_true")
    placebo = commands.add_parser("placebo")
    placebo.add_argument("--draws", type=int, default=100)
    placebo.add_argument("--only", nargs="*", default=None)
    placebo.add_argument("--force", action="store_true")
    placebo.add_argument("--suffix", default="", help="this process's own output files, so two can run at once; `gate` merges them")
    placebo.add_argument("--modes", nargs="*", default=None, help="only these nulls (asset_block, time_shift)")
    for name in ("gate", "pbo", "diagnostics", "report", "freeze", "verify", "blend", "install"):
        commands.add_parser(name)
    scores = commands.add_parser("scores")
    scores.add_argument("--context-start", default="2023-03-01")
    scores.add_argument("--through", default=None, help="score up to this date instead of the verification window's end (a daily decision)")
    judge = commands.add_parser("judge")
    judge.add_argument("--lean-report", default=None)
    judge.add_argument("--completed", action="store_true")
    judge.add_argument("--log-clean", action="store_true")
    args = parser.parse_args(argv)
    handler = {
        "rules": cmd_rules, "score": cmd_score, "placebo": cmd_placebo, "gate": cmd_gate, "pbo": cmd_pbo, "diagnostics": cmd_diagnostics,
        "report": cmd_report, "freeze": cmd_freeze, "scores": cmd_scores, "verify": cmd_verify, "blend": cmd_blend, "configs": cmd_configs, "register": cmd_register, "candidate": cmd_candidate, "judge": cmd_judge, "install": cmd_install,
    }[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
