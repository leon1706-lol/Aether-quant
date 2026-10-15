"""scripts/as_live_levers.py: the score cache key separates model directories (V6.0.0 `ml_dir`)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("as_live_levers", ROOT / "scripts" / "as_live_levers.py")
levers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(levers)


def test_scores_of_a_candidate_directory_never_share_the_installed_models_cache(tmp_path):
    dataset = tmp_path / "d.csv"
    dataset.write_text("x\n1\n", encoding="utf-8")
    config = {"phase_v2": {"rank_signal": {"heads": {"rank_20d": 1.0}}}}
    installed = levers._fingerprint(config, dataset)
    assert installed == levers._fingerprint(config, dataset, levers.ML_DIR)
    assert installed != levers._fingerprint(config, dataset, tmp_path / "ml" / "versions" / "candidate")
    assert installed != levers._fingerprint({"phase_v2": {"rank_signal": {"heads": {"rank_60d": 1.0}}}}, dataset)
