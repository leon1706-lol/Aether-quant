"""scripts/v6610_research.py: each subcommand reads the evidence files and writes the verdict its rule makes (V6.6.10). The verdicts are tested in test_multi_asset_round.py."""

from __future__ import annotations

import json

import pytest

from script_loader import load_script, run_script


@pytest.fixture
def driver(monkeypatch, tmp_path):
    module = load_script("v6610_research")
    monkeypatch.setattr(module, "OUT", tmp_path / "v6610")
    return module


def _score(ic, t=2.5):
    return {"class_ic": {"equity": ic, "bond": ic, "forex": ic, "crypto": ic}, "hac_t": t}


def test_rules_are_written_once_and_guard_every_verdict(driver, capsys):
    with pytest.raises(FileNotFoundError):
        driver.main(["loss-gate"])
    assert driver.main(["rules"]) == 0 and "sha256" in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        driver.main(["rules"])
    (driver.OUT / "rules.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="changed"):
        driver.main(["install3"])


def test_loss_gate_writes_the_kept_model(driver, capsys):
    driver.main(["rules"])
    (driver.OUT / "loss_scores.json").write_text(json.dumps({"L0": _score(0.0), "L2": _score(0.05)}), encoding="utf-8")
    assert driver.main(["loss-gate"]) == 0
    assert json.loads((driver.OUT / "loss_verdict.json").read_text(encoding="utf-8"))["kept"] == "L0"
    (driver.OUT / "loss_verification.json").write_text(json.dumps([_score(0.04), _score(0.04)]), encoding="utf-8")
    driver.main(["loss-gate"])
    assert json.loads((driver.OUT / "loss_verdict.json").read_text(encoding="utf-8"))["kept"] == "L2"
    assert '"verified": true' in capsys.readouterr().out


def test_install3_and_flip_read_the_lean_files(driver, tmp_path):
    driver.main(["rules"])
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"sharpe": 0.7, "volatility": 0.08, "max_drawdown": 0.1}), encoding="utf-8")
    assert driver.main(["install3", "--new-ic", "0.03", "--installed-ic", "0.02", "--lean-stats", str(stats), "--completed", "--log-clean"]) == 0
    assert json.loads((driver.OUT / "r_install3.json").read_text(encoding="utf-8"))["install"] is True
    driver.main(["install3"])
    assert json.loads((driver.OUT / "r_install3.json").read_text(encoding="utf-8"))["failed"] == ["ic", "lean_run", "sharpe", "drawdown"]

    holdout, compare = tmp_path / "h.json", tmp_path / "c.json"
    holdout.write_text(json.dumps({"sharpe": 0.5, "max_drawdown": 0.1, "volatility": 0.08}), encoding="utf-8")
    compare.write_text(json.dumps({"corr_lag0": 0.97, "annual_gap_bps": 40}), encoding="utf-8")
    flags = ["--survivor", "k01", "--holdout", str(holdout), "--lean-stats", str(stats), "--completed", "--log-clean", "--compare-report", str(compare)]
    assert driver.main(["flip", *flags]) == 0
    assert json.loads((driver.OUT / "r_flip1.json").read_text(encoding="utf-8"))["flip"] is True
    driver.main(["flip"])
    assert json.loads((driver.OUT / "r_flip1.json").read_text(encoding="utf-8"))["failed"] == ["a", "b", "c", "d"]


def test_runs_as_a_script(monkeypatch, capsys):
    assert run_script("v6610_research", ["--help"], monkeypatch) == 0
    assert "R-FLIP1" in capsys.readouterr().out


def _panel(with_carry=True):
    import types

    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(0)
    index = [str(day.date()) for day in pd.bdate_range("2018-01-01", "2023-08-31")]
    tickers = [f"T{i}" for i in range(8)]
    known = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(index), 8)), axis=0)), index=index, columns=tickers)
    score = known.pct_change(20)
    extras = {"ml_a1": score}
    if with_carry:
        extras["fx_carry"] = pd.DataFrame({"T0": 0.01}, index=index)
    asset_class = {ticker: ("forex" if ticker == "T0" else "equity") for ticker in tickers}
    return types.SimpleNamespace(known=known, extras=extras, asset_class=asset_class)


def test_the_alpha_stage_writes_one_report_per_table(driver, monkeypatch, capsys):

    driver.main(["rules"])
    panel = _panel()
    monkeypatch.setattr(driver, "score_panel", lambda sources, end: (panel, dict.fromkeys(sources, panel.extras["ml_a1"])))
    assert driver.main(["alpha", "--scores", "ml_a1=unused.csv"]) == 0
    report = json.loads((driver.OUT / "alpha_behaviour.json").read_text(encoding="utf-8"))
    assert set(report) == {"ml_a1"} and set(report["ml_a1"]["premia"]["betas"]) == {"momentum_12_1", "low_volatility", "carry", "market_beta"}
    assert '"ic_20"' in capsys.readouterr().out
    factors = driver.alpha_factors(_panel(with_carry=False))
    assert (factors["carry"] == 0.0).all().all() and factors["market_beta"].iloc[-1].notna().all()


def test_loss_train_runs_the_low_profile_trainer_and_resumes_a_checkpoint(driver, monkeypatch, tmp_path):
    import subprocess

    driver.main(["rules"])
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: seen.append(command) or type("R", (), {"returncode": 0})())
    assert driver.main(["loss-train", "--variant", "L3"]) == 0
    command = seen[-1]
    assert command[command.index("--ranking-objective") + 1] == "ls_sharpe" and "--resume" not in command and "low" in command
    checkpoint = tmp_path / "ml" / "versions" / driver.loss_version("L3", 0) / "checkpoint.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"x")
    driver.main(["loss-train", "--variant", "L3"])
    assert "--resume" in seen[-1]


def test_loss_score_scores_a_trained_variant_and_records_it(driver, monkeypatch, tmp_path, capsys):
    import shutil
    import sys

    import train_sequence
    from trainer_fakes import write_world

    driver.main(["rules"])
    root = tmp_path / "repo"
    paths = write_world(root)
    base = root / "ml" / "versions" / "v6610_g0007_base"
    base.mkdir(parents=True)
    shutil.copy(paths["dataset"], base / "full_dataset.csv")
    shutil.copy(paths["schema"], base / "feature_schema.json")
    monkeypatch.setattr(train_sequence, "ML_DIR", root / "ml")
    for seed in (0, 1):
        monkeypatch.setattr(sys, "argv", ["train_sequence", "--version-id", driver.loss_version("L2", seed), "--config-path", str(paths["config"]),
                                          "--dataset-path", str(base / "full_dataset.csv"), "--feature-schema-path", str(base / "feature_schema.json"), "--seed", str(seed)])
        assert train_sequence.main() == 0
    monkeypatch.setattr(driver, "ROOT", root)
    ledger = tmp_path / "ledger.jsonl"
    assert driver.main(["loss-score", "--variant", "L2", "--ledger", str(ledger)]) == 0
    assert driver.main(["loss-score", "--variant", "L2", "--seed", "1", "--ledger", str(ledger)]) == 0
    assert "L2" in json.loads((driver.OUT / "loss_scores.json").read_text(encoding="utf-8"))
    assert json.loads((driver.OUT / "loss_verification.json").read_text(encoding="utf-8"))[0]["seed"] == 1
    roles = [json.loads(line)["role"] for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert roles == ["candidate", "verification"] and '"class_ic"' in capsys.readouterr().out


def _verification_panel(tables):
    import types

    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(1)
    index = [str(day.date()) for day in pd.bdate_range("2023-06-01", "2024-06-28")]
    classes = ("equity", "bond", "forex", "crypto")
    tickers = [f"{name[0].upper()}{i}" for name in classes for i in range(5)]
    known = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(index), len(tickers))), axis=0)), index=index, columns=tickers)
    forward = known.shift(-20) / known - 1.0
    extras = {"g7_a1": forward + rng.normal(0, 0.02, forward.shape), "inst_a1": pd.DataFrame(rng.normal(size=known.shape), index=index, columns=tickers)}
    asset_class = {ticker: classes[position // 5] for position, ticker in enumerate(tickers)}
    return types.SimpleNamespace(panel=types.SimpleNamespace(known=known, extras={name: extras[name] for name in tables}, asset_class=asset_class))


def test_install3_ic_compares_the_retrained_and_installed_a1_through_one_ic(driver, monkeypatch, capsys):
    driver.main(["rules"])
    monkeypatch.setattr(driver, "score_panel", lambda sources, end: (lambda ns: (ns.panel, ns.panel.extras))(_verification_panel(sources)))
    assert driver.main(["install3-ic"]) == 0
    report = json.loads((driver.OUT / "retrain_compare.json").read_text(encoding="utf-8"))
    assert report["new_ic"] > 0.5 > abs(report["installed_ic"]), "a score that knows the forward return ranks far above noise"
    assert report["window"] == ["2023-07-01", "2026-11-02"] and '"by_class"' in capsys.readouterr().out
    assert driver.class_mean_ic({"equity_20d": {"mean_ic": 0.1}}) is None


def test_g7_scores_score_the_retrained_models_on_their_own_dataset(driver, monkeypatch, tmp_path, capsys):
    import pandas as pd

    from evaluation import dataset_io
    from evaluation import model_book_research as research

    driver.main(["rules"])
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    for folder, model, schema in (("mt", "multitask_model.json", "multitask_feature_schema.json"), ("seq", "sequence_model.json", "sequence_feature_schema.json")):
        version = tmp_path / "ml" / "versions" / f"{driver.RUN}_{folder}"
        version.mkdir(parents=True)
        (version / model).write_text("{}", encoding="utf-8")
        (version / schema).write_text(json.dumps({"model_input_names": [f"f_{folder}"]}), encoding="utf-8")
    reads = []
    monkeypatch.setattr(dataset_io, "read_dataset_columns", lambda path, columns, start: reads.append((path, columns, start)) or pd.DataFrame())
    monkeypatch.setattr(research, "universe_tickers", lambda config: ["A"])
    table = pd.DataFrame({"date": ["2023-07-03"], "ticker": ["A"], "score": [0.5]})
    seen = {}
    monkeypatch.setattr(research, "installed_score_tables", lambda dataset, exports, **kwargs: seen.update(kwargs, kinds=sorted(exports)) or {"inst_a1": table, "inst_a2": table})
    assert driver.main(["g7-scores"]) == 0
    assert reads[0][0].parent.name == f"{driver.RUN}_base" and reads[0][1] == ["date", "ticker", "f_mt", "f_seq"] and reads[0][2] == "2023-03-01"
    assert seen["kinds"] == ["multitask", "sequence"] and seen["start"] == "2023-07-01" and seen["universe"] == ["A"]
    assert (driver.OUT / "scores" / "g7_a1.csv").exists() and "g7_a2.csv: 1 rows" in capsys.readouterr().out


def test_bt_r1_blends_the_frozen_b03_on_the_retrained_scores_and_writes_its_run_config(driver, monkeypatch, tmp_path, capsys):
    import hashlib
    import sys
    import types

    driver.main(["rules"])
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "BT_R1", driver.OUT / "bt_r1")
    v669 = tmp_path / "v669"
    v669.mkdir()
    monkeypatch.setattr(driver, "V669", v669)
    for name in ("rules", "freeze"):
        text = json.dumps({"candidate": "b03", "name": name})
        (v669 / f"{name}.json").write_text(text, encoding="utf-8")
        (v669 / f"{name}.sha256").write_text(hashlib.sha256(text.encode("utf-8")).hexdigest(), encoding="utf-8")
    (v669 / "blend_blend.json").write_text(json.dumps({"model_share": 0.3, "sharpe": 0.62}), encoding="utf-8")
    (v669 / "verification.json").write_text(json.dumps({"median_phase": 8}), encoding="utf-8")
    walk = tmp_path / "ml" / "cycle" / f"retrain_{driver.RUN}" / "scores"
    walk.mkdir(parents=True)
    (driver.OUT / "scores").mkdir(parents=True)
    for name in driver.SCORE_TABLES:
        (walk / f"{name}.csv").write_text("date,ticker,score\n2023-06-30,A,0.1\n2023-07-03,A,0.9\n", encoding="utf-8")
        (driver.OUT / "scores" / f"g7_{name[-2:]}.csv").write_text("date,ticker,score\n2023-07-03,A,0.2\n", encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"forex_risk": {"enabled": False}, "target_weights": {"uses_model": False}}}), encoding="utf-8")
    monkeypatch.setattr(driver.rnd, "candidate_spec", lambda frozen: types.SimpleNamespace(rebalance_every=20))
    monkeypatch.setattr(driver.rnd, "load_round_context", lambda root, sources: sources)
    blended = {}

    def fake_blend(context, out, **kwargs):
        blended.update(kwargs, sources=context)
        (out / "weights").mkdir(parents=True, exist_ok=True)
        (out / "weights" / "blend.csv").write_text("date,ticker,weight\n", encoding="utf-8")
        return {"sharpe": 0.6}

    monkeypatch.setattr(driver.rnd, "blend_stage", fake_blend)
    configs = tmp_path / "run_configs"
    monkeypatch.setitem(sys.modules, "v650_instrument", types.SimpleNamespace(RUN_CONFIGS=configs, target_path_config=lambda base, **kwargs: {**base, "run": kwargs}))
    assert driver.main(["bt-r1"]) == 0
    assert blended["share"] == 0.3 and blended["phase_index"] == 2 and blended["start"] == "2023-07-01"
    merged = blended["sources"]["ml_a1"].read_text(encoding="utf-8").splitlines()
    assert merged == ["date,ticker,score", "2023-06-30,A,0.100000", "2023-07-03,A,0.200000"], "walk-forward rows to the seam, the final models' after it"
    config = json.loads((configs / "v6610_bt_r1.json").read_text(encoding="utf-8"))
    assert config["phase_v2"]["target_weights"]["uses_model"] is True and config["phase_v2"]["forex_risk"]["enabled"] is True
    assert config["run"]["weights_path"] == "v6610/bt_r1/weights/blend.csv" and config["run"]["window"] == ["2023-07-01", "2026-11-02"]
    assert (driver.BT_R1 / "freeze.sha256").exists() and '"pin_offline_sharpe": 0.62' in capsys.readouterr().out


def test_a_window_file_continues_the_retrain_dataset_only_when_the_overlap_agrees(driver, monkeypatch, tmp_path, capsys):
    import numpy as np
    import pandas as pd

    from evaluation import dataset_io
    from evaluation import model_book_research as research

    base = pd.DataFrame({"date": ["2025-06-02", "2025-06-27", "2025-06-27"], "ticker": ["A", "A", "B"], "f": [0.1, 0.2, np.nan]})
    window = pd.DataFrame({"date": ["2025-06-27", "2025-06-27", "2025-07-01"], "ticker": ["A", "B", "A"], "f": [0.20001, np.nan, 0.3]})
    assert driver.window_overlap(base, window, ["f"], start="2025-06-02", end="2025-06-29") == {"rows": 2, "max_abs_diff": pytest.approx(1e-5), "window": ["2025-06-02", "2025-06-29"]}
    with pytest.raises(SystemExit, match="column f"):
        driver.window_overlap(base, window.assign(f=[0.5, 0.0, 0.3]), ["f"], start="2025-06-02", end="2025-06-29")
    with pytest.raises(SystemExit, match="no row"):
        driver.window_overlap(base, window, ["f"], start="2020-01-01", end="2020-02-01")

    driver.main(["rules"])
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    for folder, model, schema in (("mt", "multitask_model.json", "multitask_feature_schema.json"), ("seq", "sequence_model.json", "sequence_feature_schema.json")):
        version = tmp_path / "ml" / "versions" / f"{driver.RUN}_{folder}"
        version.mkdir(parents=True)
        (version / model).write_text("{}", encoding="utf-8")
        (version / schema).write_text(json.dumps({"model_input_names": ["f"]}), encoding="utf-8")
    monkeypatch.setattr(dataset_io, "read_dataset_columns", lambda path, columns, start: (window if path.name == "w.csv" else base).copy())
    monkeypatch.setattr(research, "universe_tickers", lambda config: ["A", "B"])
    used = {}
    monkeypatch.setattr(research, "installed_score_tables", lambda dataset, exports, **kwargs: used.update(dataset=dataset) or {})
    assert driver.main(["g7-scores", "--window-dataset", str(tmp_path / "w.csv")]) == 0
    assert used["dataset"]["date"].tolist() == ["2025-06-02", "2025-06-27", "2025-06-27", "2025-07-01"], "the retrain's rows to the seam, the window's after it"
    assert '"rows": 2' in capsys.readouterr().out


def test_score_panel_aligns_every_named_file_on_the_research_panel(driver, monkeypatch, tmp_path):
    import types

    from evaluation import model_book_research as research
    from evaluation import premia_research

    monkeypatch.setattr(driver, "ROOT", tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"forex_risk": {"enabled": False}}}), encoding="utf-8")
    panel = _panel()
    seen = {}
    monkeypatch.setattr(premia_research, "build_context", lambda root, config, respect_disabled_classes: seen.update(forex=config["phase_v2"]["forex_risk"]["enabled"]) or types.SimpleNamespace(panel=panel))
    monkeypatch.setattr(research, "universe_tickers", lambda config: ["T1"])
    monkeypatch.setattr(research, "load_score_table", lambda path, sessions, asset_class, universe, end: (path, len(sessions), universe, end))
    got_panel, tables = driver.score_panel({"ml_a2": "a2.csv", "g7_a1": "g.csv"}, end="2023-06-30")
    assert got_panel is panel and seen["forex"] is True
    assert tables == {"ml_a2": ("a2.csv", len(panel.known), ["T1"], "2023-06-30"), "g7_a1": ("g.csv", len(panel.known), ["T1"], "2023-06-30")}


def test_book2_rules_need_the_alpha_report_and_carry_its_numbers(driver, monkeypatch):
    monkeypatch.setattr(driver, "BOOK2", driver.OUT / "book2")
    with pytest.raises(SystemExit, match="run `alpha` first"):
        driver.main(["book2-rules"])
    driver.OUT.mkdir(parents=True, exist_ok=True)
    report = {"term_structure": {"20": {"mean_ic": 0.07}}, "half_life_sessions": 57.0, "residual_ic": {"mean_ic": 0.03}}
    (driver.OUT / "alpha_behaviour.json").write_text(json.dumps({"ml_a2": report}), encoding="utf-8")
    assert driver.main(["book2-rules"]) == 0
    rules = json.loads((driver.OUT / "book2" / "rules.json").read_text(encoding="utf-8"))
    assert rules["alpha_basis"] == {"ml_a2": {"ic_20": 0.07, "half_life": 57.0, "residual_ic": 0.03}} and rules["counted_trials"] == 9
    with pytest.raises(FileExistsError):
        driver.main(["book2-rules"])


def test_book2_stages_run_on_its_own_list(driver, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(driver, "BOOK2", tmp_path / "book2")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    contexts = []
    monkeypatch.setattr(driver.rnd, "load_round_context", lambda root, sources, end: contexts.append((sorted(sources), end)) or "context")
    calls = []
    monkeypatch.setattr(driver.rnd, "score_stage", lambda context, out, **kwargs: calls.append(("score", context, kwargs)))
    monkeypatch.setattr(driver.rnd, "placebo_stage", lambda context, out, **kwargs: calls.append(("placebo", context, kwargs)))
    monkeypatch.setattr(driver.rnd, "gate_stage", lambda out, **kwargs: {"survivors": [], "pool": [spec.id for spec in kwargs["pool"]]})
    monkeypatch.setattr(driver.rnd, "pbo_stage", lambda out, **kwargs: {"pbo": 0.4})
    monkeypatch.setattr(driver.rnd, "report_stage", lambda out, **kwargs: {"trials": {}, "install": {"candidate": None}, "name": kwargs["name"], "only": kwargs["survivors_only"]})
    monkeypatch.setattr(driver.rnd, "freeze_stage", lambda out, **kwargs: (out / "freeze.json", kwargs["report_name"]))
    assert driver.main(["book2", "score", "--only", "n01"]) == 0
    _, context, kwargs = calls[-1]
    assert context == "context" and contexts[-1] == (["ml_a1", "ml_a2", "ml_a3"], "2023-06-30")
    assert [spec.id for spec in kwargs["specs"]][-2:] == ["n00", "core"] and kwargs["control_ids"] == ["n00", "core"] and kwargs["ids"] == ["n01"]
    driver.main(["book2", "placebo", "--draws", "3"])
    assert calls[-1][2]["draws"] == 3 and len(calls[-1][2]["pool"]) == 9
    for stage in ("gate", "pbo", "report", "freeze"):
        assert driver.main(["book2", stage]) == 0
    out = capsys.readouterr().out
    assert '"n09"' in out and '"pbo": 0.4' in out and '"r_book2.json"' in out and '"only": true' in out and "freeze.json written; sha256 r_book2.json" in out
