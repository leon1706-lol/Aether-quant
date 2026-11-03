"""V6.4.4 cross-module regressions (round file): Codespace script hygiene found while preparing the phase."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shell_scripts_are_lf():
    """A tar push carries the working tree to the Codespace; a CRLF shell script fails there (`$'\r': command not
    found`). codespace_retrain_v580.sh had CRLF in the working tree despite `*.sh text eol=lf`."""
    offenders = [path.name for path in sorted((ROOT / "scripts").glob("*.sh")) if b"\r\n" in path.read_bytes()]
    assert offenders == []


def test_keepalive_holds_every_long_codespace_job():
    """The keepalive returned while a train.py / retrain / research job still ran, so the Codespace idled out under it."""
    text = (ROOT / "scripts" / "codespace_keepalive.sh").read_text(encoding="utf-8")
    pattern = text.split("PATTERN='", 1)[1].split("'", 1)[0].split("|")
    for token in ("train.py", "codespace_retrain_", "v644_research.py", "build_holdout_dataset.py", "train_multitask.py",
                  "codespace_session_"):
        assert token in pattern


def test_member_pass_resizes_false_keeps_held_weights_between_rebalances():
    """R-CAL5 candidate (V6.4.4): with `member_pass_resizes=False` the between-rebalance member pass enters and exits but
    never resizes a held member; the default (True) is the V6.1.0 behaviour."""
    import numpy as np
    import pandas as pd

    from evaluation.rank_book_simulator import simulate_rank_book

    rng = np.random.default_rng(4)
    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=25)]
    frame = pd.DataFrame([{"date": d, "ticker": f"T{i}", "pred": (i - 6) / 12 + rng.normal(0, 0.05),
                           "target_return_1d": rng.normal(0, 0.002), "close": 100.0} for d in dates for i in range(12)])

    def growing(*, symbol, date, base_weight, held_weight, **_):
        return base_weight * (1.0 + dates.index(date) / 100.0)  # the member chain's target drifts every session

    kwargs = dict(prediction_column="pred", forward_return_column="target_return_1d", ticker_column="ticker", date_column="date",
                  top_n=3, bottom_n=3, rebalance_every_bars=5, cost_bps_per_side=5.0, commission_bps=1.0, gross_exposure=1.0,
                  dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.5, min_universe_size=5,
                  member_weight_fn=growing, hold_positions_on_veto=True, mid_cycle_member_updates=True, log_weights=True)
    default = simulate_rank_book(frame, **kwargs)
    frozen = simulate_rank_book(frame, **kwargs, member_pass_resizes=False)
    explicit = simulate_rank_book(frame, **kwargs, member_pass_resizes=True)
    assert default.per_date_net_return == explicit.per_date_net_return

    def changes(result):
        return sum(1 for a, b in zip(result.weights_log, result.weights_log[1:])
                   for t in set(a) & set(b) if a[t] != b[t])

    assert changes(frozen) < changes(default)


def test_harness_score_cache_key_covers_ranked_inputs_and_the_seed_ensemble(tmp_path):
    """The as-live harness caches the live score per (config, dataset, models); its key read only `phase_v2.rank_signal`,
    so turning on ranked inputs or a seed ensemble with the same models returned the old cached scores. Default configs
    (both off) keep their old key."""
    import json
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from as_live_levers import _fingerprint

    dataset = tmp_path / "d.csv"
    dataset.write_text("x\n", encoding="utf-8")
    base = {"phase1": {"features": {"cross_sectional_inputs": {"enabled": False}}},
            "phase_v2": {"rank_signal": {"heads": {"rank_20d": 1.0}}, "model_ensemble": {"enabled": False}}}
    legacy = {"phase_v2": {"rank_signal": {"heads": {"rank_20d": 1.0}}}}
    assert _fingerprint(base, dataset, tmp_path) == _fingerprint(legacy, dataset, tmp_path)
    ranked = json.loads(json.dumps(base))
    ranked["phase1"]["features"]["cross_sectional_inputs"] = {"enabled": True, "mode": "replace"}
    ensemble = json.loads(json.dumps(base))
    ensemble["phase_v2"]["model_ensemble"] = {"enabled": True, "multitask_dir": "multitask_ensemble"}
    keys = {_fingerprint(config, dataset, tmp_path) for config in (base, ranked, ensemble)}
    assert len(keys) == 3
    (tmp_path / "multitask_ensemble").mkdir()
    (tmp_path / "multitask_ensemble" / "member_1.json").write_text("{}", encoding="utf-8")
    assert _fingerprint(ensemble, dataset, tmp_path) not in keys


def test_dev_requirements_carry_the_parquet_reader_the_research_chains_need():
    """The training Codespace installs only requirements/*.txt; the research chains write parquet (V6.4.4 session stopped
    on `Import pyarrow failed`)."""
    import re

    text = (ROOT / "requirements" / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"^pyarrow>=", text, re.M)


def test_run_history_labels_a_verdict_with_the_rule_its_file_records(tmp_path):
    """V6.4.4: R-LEAN16 reused lean_verdict's non-inferiority clauses, whose output says "rule": "R-LEAN13"; the README's
    run history then called BT11 "kept (R-LEAN13)". The file name / `reported_as` names the rule that was applied."""
    import json
    import sys

    sys.path.insert(0, str(ROOT))
    from generate_backtest_report import load_lean_verdicts, run_status

    phase = tmp_path / "v644"
    phase.mkdir()
    (phase / "r_lean16_bt11.json").write_text(json.dumps({"candidate": "run_b", "keep": True, "rule": "R-LEAN13"}), encoding="utf-8")
    (phase / "r_lean17_bt12.json").write_text(json.dumps({"candidate": "run_c", "keep": False, "rule": "R-LEAN14",
                                                          "reported_as": "R-LEAN17"}), encoding="utf-8")
    verdicts = load_lean_verdicts(tmp_path)
    assert run_status("run_b", None, verdicts) == "kept (R-LEAN16)"
    assert run_status("run_c", "run_c", verdicts) == "shipped (README pin), rejected (R-LEAN17)"
