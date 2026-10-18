"""Assemble the R-MODEL9 candidates for scripts/v610_research.py (V6.1.0).

From scripts/model_candidate_research.py's `model_ic.json` this writes, for every candidate:
- a model directory the as-live harness can score (`ml/versions/v610_cand_<name>/`: the first member's exports, schemas
  and training metrics, `model_weights.json` for the legacy signal's threshold, and `multitask_ensemble/` /
  `sequence_ensemble/` with every member's export - `phase_v2.model_ensemble` reads them as main.py will),
- R-HEAD for the decision heads (`rank_signal.heads` with a positive weight): a head passes when at least half of the
  candidate's members rate it `promotable` or `watchlist` on their backtest promotion gate (the installed models keep
  the owner's 2026-10-13 watchlist decision for their rank heads, Problems.md #162),
- the heads that pass R-HEAD on the model of each kind (R-HEAD2's H1 candidates),
- the inference latency ratio against the installed single models (the members' batched forward passes on the same
  rows; R-MODEL9 clause 5),
- whether R-MODEL9's IC clauses pass (only those candidates get book scores and a legacy-probability file).

    python scripts/prepare_v610_candidates.py --model-ic ml/evaluation/v610/model_ic.json --dataset ml/datasets/validation_dataset.csv
        [--out ml/evaluation/v610/candidates.json] [--rule r-model10 --prefix v620_cand_]

V6.2.0: `--rule r-model10` applies R-MODEL10's IC clauses (scripts/v620_research.model10_checks: the resampled-ensemble
yardstick from model_candidate_research --bootstrap) instead of R-MODEL9's; `--prefix` names the candidate directories.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

PASSING = {"promotable", "watchlist"}
OWNER_WATCHLIST_HEADS = {"rank_5d", "rank_20d", "residual_rank_5d", "residual_rank_20d"}
RANK_HEADS = ("rank_5d", "rank_20d", "sector_neutral_rank_20d", "residual_rank_5d", "residual_rank_20d")
FILES = {
    "multitask": ("multitask_model.json", "multitask_feature_schema.json", "multitask_training_metrics.json"),
    "sequence": ("sequence_model.json", "sequence_feature_schema.json", "sequence_training_metrics.json"),
}


def head_status(member_dirs: list[Path], kind: str, head: str) -> bool:
    statuses = []
    for directory in member_dirs:
        path = directory / FILES[kind][2]
        metrics = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        quality = (metrics.get("backtest", {}) or {}).get(f"{head}_ranking_quality") or {}
        statuses.append(quality.get("quality_status") in PASSING)
    return bool(statuses) and sum(statuses) * 2 >= len(statuses)


def build_candidate_dir(name: str, members: dict[str, list[str]], prefix: str = "v610_cand_") -> Path:
    target = ROOT_DIR / "ml" / "versions" / f"{prefix}{name}"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(ROOT_DIR / "ml" / "model_weights.json", target / "model_weights.json")
    for kind, dirs in members.items():
        first = ROOT_DIR / dirs[0]
        for filename in FILES[kind]:
            if (first / filename).exists():
                shutil.copy2(first / filename, target / filename)
        ensemble = target / f"{kind}_ensemble"
        ensemble.mkdir()
        for index, directory in enumerate(dirs):
            shutil.copy2(ROOT_DIR / directory / FILES[kind][0], ensemble / f"member_{index:02d}.json")
    return target


def latency_ratio(members: dict[str, list[str]], frame, window: int) -> float:
    """Batched forward-pass time of the members against the installed single models on the same rows."""
    from evaluation.model_predictions import predict_heads_ensemble

    def timed(kind: str, dirs: list[Path]) -> float:
        schema = json.loads((dirs[0] / FILES[kind][1]).read_text(encoding="utf-8"))
        exports = [json.loads((directory / FILES[kind][0]).read_text(encoding="utf-8")) for directory in dirs]
        started = time.perf_counter()
        predict_heads_ensemble(frame, exports, schema["model_input_names"], ["rank_20d"], model_kind=kind,
                               sequence_feature_schema=schema if kind == "sequence" else None, configured_window_size=window,
                               batched=True)
        return time.perf_counter() - started

    ml = ROOT_DIR / "ml"
    base = sum(timed(kind, [ml]) for kind in members)
    candidate = sum(timed(kind, [ROOT_DIR / item for item in dirs]) for kind, dirs in members.items())
    return candidate / base if base > 0 else 1.0


def main() -> int:
    import pandas as pd
    from v610_research import model_ic_checks

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-ic", default=str(ROOT_DIR / "ml" / "evaluation" / "v610" / "model_ic.json"))
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "validation_dataset.csv"))
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v610" / "candidates.json"))
    parser.add_argument("--rule", choices=("r-model9", "r-model10"), default="r-model9")
    parser.add_argument("--prefix", default="v610_cand_")
    args = parser.parse_args()
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    model_ic = json.loads(Path(args.model_ic).read_text(encoding="utf-8"))
    window = int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30))
    decision_heads = [head for head, weight in config["phase_v2"]["rank_signal"]["heads"].items() if weight > 0]
    sample = pd.read_csv(args.dataset, nrows=3000)
    out: dict = {}
    for name, entry in model_ic["candidates"].items():
        members = entry["members"]
        if name == "installed":
            passing = sorted(OWNER_WATCHLIST_HEADS | {h for h in RANK_HEADS if head_status([ROOT_DIR / "ml"], "multitask", h)})
            out[name] = {"ml_dir": None, "ensemble": False, "passing_heads": passing, "decision_heads_pass_r_head": True}
            continue
        member_dirs = {kind: [ROOT_DIR / item for item in dirs] for kind, dirs in members.items()}
        passing = sorted({
            head for head in RANK_HEADS if any(head_status(dirs, kind, head) for kind, dirs in member_dirs.items())
        })
        if args.rule == "r-model10":
            from v620_research import model10_checks

            ic = model10_checks(model_ic, name)
        else:
            ic = model_ic_checks(model_ic, name)  # every retrained candidate, the control's seed ensemble included, vs installed
        spec = {
            "members": members, "passing_heads": passing,
            "decision_heads_pass_r_head": all(head in passing for head in decision_heads),
            "ic_checks": ic, "ic_pass": bool(ic) and all(value for key, value in ic.items() if key != "yardstick"),
        }
        if spec["ic_pass"]:
            spec["ml_dir"] = str(build_candidate_dir(name, members, args.prefix).relative_to(ROOT_DIR)).replace("\\", "/")
            spec["ensemble"] = any(len(dirs) > 1 for dirs in members.values())
            spec["latency_ratio"] = latency_ratio(members, sample, window)
        out[name] = spec
        print(name, json.dumps({k: v for k, v in spec.items() if k != "members"}), flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
