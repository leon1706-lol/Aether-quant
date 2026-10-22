"""Freeze a Lean run's config (V6.4.0): a base config plus the rule-adopted changes, written where the DinD runner and the
run-folder tools read it (`ml/evaluation/run_configs/<name>.json`), with its sha256 printed for the Changelog's Freeze bullet.

    python scripts/freeze_run_config.py --base ml/evaluation/run_configs/v640_bt5.json --adopted ml/evaluation/v640/adopted_changes.json \\
        --name v640_bt6 [--lean-window 2023-07-01 2026-10-16]

`--adopted` is `scripts/v640_research.py`'s `adopted_changes.json`: its `config` (dotted keys under `phase_v2`) and `patch` (dotted keys
from the config root) are applied; items listed in `needs_live_path` must already be built in `main.py` (the script refuses
otherwise, so a run never freezes a setting live code does not read).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v610_research import apply_dotted  # noqa: E402
from v640_research import patch_config  # noqa: E402

BUILT_LIVE_PATHS: set[str] = {"graduates_off"}  # extend as an adopted item's live path lands (direction_overlay, tranches, ...)


def freeze(base: dict, adopted: dict, lean_window: tuple[str, str] | None = None) -> dict:
    """The base config with the adopted changes applied; raises when an adopted item has no live path yet."""
    unbuilt = sorted(set(adopted.get("needs_live_path") or []) - BUILT_LIVE_PATHS)
    if unbuilt:
        raise ValueError(f"adopted items without a live path in main.py: {unbuilt}")
    config = patch_config(apply_dotted(base, adopted.get("config") or {}), adopted.get("patch") or {})
    if adopted.get("graduates_off"):  # L9: the crypto graduates are no book candidates (`class_weight_caps.crypto.core_only`)
        config["phase_v2"]["class_weight_caps"]["crypto"]["core_only"] = True
    if lean_window:
        config["runtime"]["lean_window_override"] = {"start": lean_window[0], "end": lean_window[1]}
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True)
    parser.add_argument("--adopted", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--lean-window", nargs=2, default=None, metavar=("START", "END"))
    parser.add_argument("--allow-unbuilt", action="store_true", help="freeze even when an adopted item has no live path (research only)")
    args = parser.parse_args()
    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    adopted = json.loads(Path(args.adopted).read_text(encoding="utf-8"))
    if args.allow_unbuilt:
        adopted = {**adopted, "needs_live_path": []}
    config = freeze(base, adopted, tuple(args.lean_window) if args.lean_window else None)
    text = json.dumps(config, indent=4)
    out = ROOT_DIR / "ml" / "evaluation" / "run_configs" / f"{args.name}.json"
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{out}\nsha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
