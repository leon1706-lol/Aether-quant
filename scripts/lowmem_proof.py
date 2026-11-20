"""Proof that the stack trains on a small machine (V6.6.10): a synthetic dataset the size of the real one, the multitask and sequence
trainers under `--memory-profile low`, and each one's measured peak memory against a budget.

    python scripts/lowmem_proof.py                          # 280k rows x 254 columns, one epoch each, budget 2.6 GB
    python scripts/lowmem_proof.py --rows 2000 --budget-gb 2.6

CI's `lowmem-proof` job runs it on a free runner; a peak above the budget, or a trainer that fails, exits 1. The data is random: this
proves memory, not skill. Nothing outside `--work` and `ml/versions/lowmem_proof_*` is written, and those versions are removed after.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("target_direction", "target_return_1d", "target_volatility_next_day", "target_direction_5d", "target_direction_20d", "target_rank_5d", "target_rank_20d",
           "target_sector_neutral_rank_20d", "target_residual_rank_5d", "target_residual_rank_20d", "target_beta_neutral_rank_20d", "target_return_5d", "target_return_20d")
STAGES = ("multitask", "sequence")


def write_dataset(path: Path, *, rows: int, features: int, columns: int, tickers: int, seed: int = 0) -> list[str]:
    """Writes the CSV one date at a time (never the whole frame) and returns the model input names. Splits by date: 62% train,
    15% validation, 15% backtest, the rest holdout."""
    import pandas as pd

    rng = np.random.default_rng(seed)
    names = [f"f{i:03d}" for i in range(features)]
    fillers = [f"x{i:03d}" for i in range(max(0, columns - features - len(TARGETS) - 5))]
    dates = max(2, rows // tickers)
    ticker_names = [f"T{i:03d}" for i in range(tickers)]
    path.parent.mkdir(parents=True, exist_ok=True)
    for day in range(dates):
        fraction = day / dates
        split = "train" if fraction < 0.62 else "validation" if fraction < 0.77 else "backtest" if fraction < 0.92 else "holdout"
        block = {"date": str(np.datetime64("2014-01-01") + np.timedelta64(day, "D")), "ticker": ticker_names, "split": split, "training_eligible": True, "security_type": "equity"}
        block.update({name: rng.normal(size=tickers).astype(np.float32) for name in [*names, *fillers]})
        ranks = rng.permutation(tickers) / max(tickers - 1, 1)
        for target in TARGETS:
            block[target] = (rng.random(tickers) > 0.5).astype(float) if "direction" in target else (ranks if "rank" in target else rng.normal(0, 0.02, tickers))
        pd.DataFrame(block).to_csv(path, mode="a", header=day == 0, index=False)
    return names


def write_config(path: Path, *, epochs: int) -> None:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    retraining = config["phase_v2"]["retraining"]
    for block in ("multitask_training", "sequence_training"):
        retraining[block].update({"epochs": epochs, "patience": epochs, "min_best_epoch": 1})
    retraining["multitask_training"]["swa"] = {"enabled": False}
    retraining["sequence_training"]["swa"] = {"enabled": False}
    config["phase1"]["features"]["cross_sectional_inputs"] = {"enabled": False}
    config["phase1"]["target"]["ranking"]["net_performance"] = {"enabled": False}
    config["phase1"]["target"]["ranking"]["purged_cv"] = {"enabled": False}
    path.write_text(json.dumps(config), encoding="utf-8")


def stage_command(stage: str, *, work: Path, version: str, python: str = sys.executable) -> list[str]:
    return [python, str(ROOT / f"train_{stage}.py"), "--version-id", version, "--config-path", str(work / "config.json"), "--dataset-path", str(work / "dataset.csv"),
            "--feature-schema-path", str(work / "feature_schema.json"), "--memory-profile", "low", "--log-peak-memory", str(work / "peaks.jsonl")]


def verdict(peaks: Sequence[dict], codes: dict[str, int], budget_gb: float) -> dict:
    """Every stage ran (exit 0), wrote its peak, and stayed within the budget; a peak that can't be read fails rather than passes."""
    by_stage = {row["stage"]: row.get("peak_gb") for row in peaks}
    failed = {stage: f"exit {code}" for stage, code in codes.items() if code != 0}
    for stage in codes:
        peak = by_stage.get(stage)
        if stage not in failed and (peak is None or peak > budget_gb):
            failed[stage] = "no peak recorded" if peak is None else f"peak {peak} GB > {budget_gb} GB"
    return {"ok": not failed, "budget_gb": budget_gb, "peaks_gb": by_stage, "failed": failed}


def main(argv: list[str] | None = None, *, runner: Callable = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=280_000)
    parser.add_argument("--features", type=int, default=66)
    parser.add_argument("--columns", type=int, default=254)
    parser.add_argument("--tickers", type=int, default=104)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--budget-gb", type=float, default=2.6)
    parser.add_argument("--work", default=None, help="working folder (default: a temporary one, removed after)")
    args = parser.parse_args(argv)
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="aq_lowmem_"))
    version = f"lowmem_proof_{work.name}"
    try:
        names = write_dataset(work / "dataset.csv", rows=args.rows, features=args.features, columns=args.columns, tickers=args.tickers)
        (work / "feature_schema.json").write_text(json.dumps({"model_input_names": names, "feature_names": names, "scaled_feature_names": names}), encoding="utf-8")
        write_config(work / "config.json", epochs=args.epochs)
        codes = {stage: runner(stage_command(stage, work=work, version=version), cwd=str(ROOT), check=False).returncode for stage in STAGES}
        peaks_path = work / "peaks.jsonl"
        peaks = [json.loads(line) for line in peaks_path.read_text(encoding="utf-8").splitlines()] if peaks_path.exists() else []
        result = verdict(peaks, codes, args.budget_gb)
    finally:
        shutil.rmtree(ROOT / "ml" / "versions" / version, ignore_errors=True)
        if not args.work:
            shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(result, indent=1))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
