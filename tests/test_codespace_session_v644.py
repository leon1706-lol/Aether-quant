"""Static checks of scripts/codespace_session_v644.sh and scripts/v644_make_configs.py (V6.4.4): the session is one Codespace
lifetime that cannot run in the suite, so these pin its guards - rules hashed before any score, the manifest and data checks,
the as-of dataset, the two-stage grid, the smoke pass, the walk-forward that restores config.json, and no broad cleanup."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION = (ROOT / "scripts" / "codespace_session_v644.sh").read_bytes().decode("utf-8")
sys.path.insert(0, str(ROOT / "scripts"))


def test_session_is_lf_resumable_and_never_pkills():
    assert "\r\n" not in SESSION
    assert 'marker() { [ "${RESUME:-0}" = "1" ]' in SESSION
    assert "pkill -f" not in SESSION


def test_rules_models_and_data_are_checked_before_spending_hours():
    first_fit = SESSION.index("S1 full-split dataset")
    for guard in ("rules.json does not match rules.sha256", "MANIFEST MISMATCH", "data_append_guard.py verify",
                  "factor_file_backfill --audit"):
        assert SESSION.index(guard) < first_fit


def test_dataset_uses_the_asof_config_and_keeps_the_models():
    assert '--config-path "${OUT}/configs/base_asof.json"' in SESSION
    assert "the dataset build changed the installed models" in SESSION


def test_grid_is_two_stage_with_seed_one_first():
    assert "for grid_id in M0 M1 M2 M3 M4 M5 M6; do fit \"${grid_id}\" 1; done" in SESSION
    assert SESSION.index("--stages priors stage1") < SESSION.index('fit "${grid_id}" 2')


def test_smoke_runs_before_the_chain_and_walk_forward_restores_the_config():
    assert SESSION.index("--smoke") < SESSION.index("S4b the research chain")
    assert "cp /tmp/aq_v644_config.json.orig config.json" in SESSION
    assert "config.json was not restored" in SESSION
    assert "--stages c6 --wf-candidate" in SESSION


def test_no_broad_ml_cleanup_that_would_prune_version_folders():
    assert "aq_cli.py clean ml" not in SESSION and "aq clean ml" not in SESSION.replace("`aq clean ml --apply` would", "")


def test_session_ends_with_the_suite_and_a_pack_without_datasets():
    assert "codespace_run_tests.sh" in SESSION
    assert "--exclude='*full_dataset.csv'" in SESSION and "ALL_DONE" in SESSION


def test_candidate_configs_share_the_base_and_differ_only_as_registered(tmp_path):
    from v644_make_configs import GRID, write_configs

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    shas = write_configs(base, tmp_path)
    assert set(shas) == {"base_asof", *GRID}
    for grid_id in GRID:
        config = json.loads((tmp_path / f"{grid_id}.json").read_text(encoding="utf-8"))
        assert config["phase1"]["target"]["ranking"]["beta_estimation"] == "asof"
        assert config["phase_v2"]["rank_signal"]["model_priority"] == ["multitask"]
        tracked = config["phase_v2"]["retraining"]["walk_forward"]["tracked_metrics"]
        assert tracked[-1]["artifact"] == "multitask_training_metrics.json"
    m6 = json.loads((tmp_path / "M6.json").read_text(encoding="utf-8"))
    assert m6["phase1"]["features"]["cross_sectional_inputs"]["mode"] == "append"
    m0 = json.loads((tmp_path / "M0.json").read_text(encoding="utf-8"))
    assert m0["phase1"]["features"]["cross_sectional_inputs"]["enabled"] is False


def test_r_model13_continuation_needs_its_rule_and_the_finished_session_and_shares_the_memo():
    text = (ROOT / "scripts" / "codespace_session_v644b.sh").read_bytes().decode("utf-8")
    assert "\r\n" not in text and "pkill -f" not in text
    assert text.index("no r_model13_rule.json") < text.index("R13-S1")
    assert text.index("R-MODEL12 session has not finished") < text.index("R13-S1")
    assert "--memo ${OUT}/research.memo.json --centred" in text
    assert "cp /tmp/aq_v644b_config.json.orig config.json" in text and "aq clean ml" not in text


def test_centred_targets_remove_the_group_size_artifact():
    """A percentile rank in a group of n names averages (n+1)/2n: after centring every (date, group) mean is 0."""
    import pandas as pd
    from v644_research import CENTRED_SUFFIX, add_centred_targets

    config = {"phase1": {"universe": {"assets": [{"ticker": "B1", "asset_class": "bond"}, {"ticker": "B2", "asset_class": "bond"},
                                                   {"ticker": "E1", "security_type": "equity"}, {"ticker": "E2", "security_type": "equity"},
                                                   {"ticker": "E3", "security_type": "equity"}]},
                         "target": {"ranking": {"separate_rank_groups": {"bond": ["bond"]}}}}}
    frame = pd.DataFrame({"date": ["d"] * 5, "ticker": ["B1", "B2", "E1", "E2", "E3"],
                          "target_rank_20d": [0.5, 1.0, 1 / 3, 2 / 3, 1.0], "target_sector_neutral_rank_20d": [1.0] * 5})
    out = add_centred_targets(frame, config)
    assert list(out["_rank_group"]) == ["bond", "bond", "main", "main", "main"]
    sums = out.groupby("_rank_group")["target_rank_20d" + CENTRED_SUFFIX].sum()
    assert abs(sums).max() < 1e-6
    assert out["target_rank_20d" + CENTRED_SUFFIX].tolist()[0] < 0 < out["target_rank_20d" + CENTRED_SUFFIX].tolist()[1]


def test_r_model13_chain_reads_the_shared_memo(tmp_path):
    """`--memo` points R-MODEL13 at R-MODEL12's memo (the same as-live runs); the first Codespace launch crashed reading it."""
    import argparse
    import json

    from v644_research import Chain644

    memo = tmp_path / "shared.memo.json"
    memo.write_text(json.dumps({"key": {"summary": {}}}), encoding="utf-8")
    args = argparse.Namespace(out=str(tmp_path / "r13.json"), memo=str(memo), centred=True, smoke=False,
                              dataset=str(tmp_path / "none.csv"), asof_labels=str(tmp_path / "none.parquet"), max_phases=2)
    chain = Chain644(args)
    assert chain.memo == {"key": {"summary": {}}} and chain.memo_path == memo and chain.tag == "_r13"
