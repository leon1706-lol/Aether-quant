"""aq_lab_cli.py: the model-lab, data, signal, research and maintainer commands, run through the real parser on the lab world."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import aq_cli
import aq_devtools as dev
import aq_lab_cli as cli
from lab_world import make_lab, planted_closes


def aq(*argv):
    args = aq_cli.build_parser().parse_args([str(part) for part in argv])
    return aq_cli.run_command(args, aq_cli.build_parser())


@pytest.fixture
def lab(tmp_path, monkeypatch):
    folder = make_lab(tmp_path / "lab")
    monkeypatch.chdir(folder)
    return folder


def _signal(path: Path, closes: pd.DataFrame, horizon: int = 20, sign: float = 1.0) -> Path:
    scores = (sign * (closes / closes.shift(horizon) - 1)).stack().rename("score").reset_index()
    scores.columns = ["date", "ticker", "score"]
    scores.dropna().to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


def test_data_sample_info_explore_manifest_and_diff(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert aq("data", "sample", "--out", "d") == 0 and (tmp_path / "d" / "closes.csv").exists() and (tmp_path / "d" / "README.txt").exists()
    assert aq("data", "info", "d/closes.csv") == 0 and "7-day calendar" in capsys.readouterr().out
    assert aq("data", "info", "d/closes.csv", "--json") == 0 and json.loads(capsys.readouterr().out)["tickers"] == 11
    assert aq("data", "explore", "d/closes.csv") == 0 and (tmp_path / "d" / "closes.html").exists()
    assert aq("data", "manifest", "--root", "d", "--out", "m.json") == 0 and len(json.loads((tmp_path / "m.json").read_text())["files"]) == 3
    assert aq("data", "manifest", "--root", "d") == 0 and '"files"' in capsys.readouterr().out
    assert aq("data", "diff", "m.json", "--root", "d") == 0 and "identical" in capsys.readouterr().out
    (tmp_path / "d" / "extra.txt").write_text("x", encoding="utf-8")
    (tmp_path / "d" / "README.txt").write_text("changed", encoding="utf-8")
    assert aq("data", "diff", "m.json", "--root", "d") == 3
    out = capsys.readouterr().out
    assert "only in B: extra.txt" in out and "differs:   README.txt" in out
    assert aq("data", "manifest", "--root", "d", "--out", "n.json") == 0
    assert aq("data", "diff", "m.json", "n.json", "--json") == 3 and json.loads(capsys.readouterr().out.split("\n", 1)[-1] or "{}") is not None


def test_data_fetch_writes_closes_and_says_what_failed(tmp_path, monkeypatch, capsys):
    import data_pipeline.public_candles as candles

    bars = {"BTCUSD": pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "open": 1.0, "high": 1.0, "low": 1.0, "close": [10.0, 11.0], "volume": 1.0})}
    monkeypatch.setattr(candles, "fetch_daily_bars", lambda tickers, start, end: (bars, ["DOGEUSD"]))
    monkeypatch.chdir(tmp_path)
    assert aq("data", "fetch", "--coins", "btc,DOGE", "--start", "2024-01-01", "--end", "2024-01-02", "--out", "c.csv") == 0
    out = capsys.readouterr()
    assert "no data for DOGEUSD" in out.err and "2 dates x 1 coins" in out.out and (tmp_path / "c.csv").exists()
    monkeypatch.setattr(candles, "fetch_daily_bars", lambda tickers, start, end: ({}, list(tickers)))
    assert aq("data", "fetch", "--coins", "BTC", "--out", "c.csv") == 1 and "no bars downloaded" in capsys.readouterr().err
    monkeypatch.setattr(candles, "fetch_daily_bars", lambda tickers, start, end: (bars, []))
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, path: (_ for _ in ()).throw(ImportError("pyarrow")))
    assert aq("data", "fetch", "--coins", "BTC", "--out", "c.parquet") == 1 and "pyarrow" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------


def test_signal_check_eval_compare_neutralize_and_backtest(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    closes = planted_closes()
    closes.to_csv("closes.csv", index_label="date")
    momentum = _signal(tmp_path / "mom.csv", closes)
    reversal = _signal(tmp_path / "rev.csv", closes, horizon=5, sign=-1.0)
    assert aq("signal", "check", momentum) == 0 and "ok:" in capsys.readouterr().out
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"date": ["2024-01-01", "2024-01-01"], "ticker": ["A", "A"], "score": [1.0, float("inf")]}).to_csv(bad, index=False)
    assert aq("signal", "check", bad, "--json") == 1 and len(json.loads(capsys.readouterr().out)["errors"]) == 2
    assert aq("signal", "eval", momentum, "--prices", "closes.csv", "--html", "s.html") == 0
    out = capsys.readouterr().out
    assert "decay:" in out and "validation h20: IC +" in out and (tmp_path / "s.html").exists()
    assert aq("signal", "eval", bad, "--prices", "closes.csv") == 1 and "has errors" in capsys.readouterr().err
    assert aq("signal", "compare", momentum, reversal, "--prices", "closes.csv") == 0 and "equal-weight combination" in capsys.readouterr().out
    assert aq("signal", "compare", momentum, bad, "--prices", "closes.csv") == 1
    thin = pd.read_csv(momentum)
    first = thin["date"].min()
    thin = thin[(thin["date"] != first) | thin["ticker"].isin(thin["ticker"].unique()[:2])]
    thin.to_csv(tmp_path / "thin.csv", index=False)
    assert aq("signal", "compare", tmp_path / "thin.csv", reversal, "--prices", "closes.csv", "--json") == 0, "a date with too few names is left out of the residual fit"
    capsys.readouterr()
    assert aq("signal", "compare", momentum, "--prices", "closes.csv", "--json") == 0 and json.loads(capsys.readouterr().out)["ic_after_the_others"] == {}
    assert aq("signal", "neutralize", momentum, "--prices", "closes.csv", "--window", "40") == 0 and (tmp_path / "mom_neutral.csv").exists()
    assert aq("signal", "neutralize", momentum, "--prices", "closes.csv", "--market", "C0", "--out", "n.csv") == 0
    assert aq("signal", "neutralize", bad, "--prices", "closes.csv") == 1
    assert aq("signal", "backtest", momentum, "--prices", "closes.csv", "--top-n", "3", "--cost", "bps:5", "--ledger", "t.jsonl") == 0
    assert "PSR" in capsys.readouterr().out and len((tmp_path / "t.jsonl").read_text().splitlines()) == 1
    assert aq("signal", "backtest", momentum, "--prices", "closes.csv", "--cost", "ib_equity", "--json") == 0 and "judged" in json.loads(capsys.readouterr().out)
    assert aq("signal", "backtest", bad, "--prices", "closes.csv") == 1
    with pytest.raises(ValueError, match="coinbase, ib_equity or bps"):
        cli.cost_model("free")
    assert cli.cost_model("coinbase") is not None


def test_signal_tools_on_the_bundled_sample_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from aether_quant.samples import load_sample_prices

    momentum = _signal(tmp_path / "mom.csv", load_sample_prices("close"))
    assert aq("signal", "eval", momentum, "--horizons", "20", "--json") == 0 and "decay" in json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# features and overfitting calculators
# ---------------------------------------------------------------------------


def test_features_list_build_and_inspect(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    planted_closes().to_csv("closes.csv", index_label="date")
    assert aq("features", "list") == 0 and "rsi_14" in capsys.readouterr().out
    assert aq("features", "list", "--all", "--json") == 0 and "macro" in json.loads(capsys.readouterr().out)["production_only_groups"]
    assert aq("features", "build", "--prices", "closes.csv", "--set", "example", "--dry-run") == 0 and "would write" in capsys.readouterr().out
    assert aq("features", "build", "--prices", "closes.csv", "--set", "ret_5,vol_20", "--out", "f.csv") == 0 and (tmp_path / "f.csv").exists()
    assert aq("features", "build", "--set", "nope") == 2 and "unknown feature" in capsys.readouterr().err
    assert aq("features", "inspect", "ret_20", "--prices", "closes.csv", "--html", "f.html") == 0
    out = capsys.readouterr().out
    assert "20-session IC" in out and "most overlapping" in out and (tmp_path / "f.html").exists()
    assert aq("features", "inspect", "vol_20", "--prices", "closes.csv", "--json") == 0 and json.loads(capsys.readouterr().out)["feature"] == "vol_20"


def test_the_overfitting_calculators(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rng = np.random.default_rng(4)
    pd.DataFrame(rng.normal(0.0005, 0.01, (300, 5))).to_csv("trials.csv", index=False)
    pd.DataFrame({"returns": rng.normal(0.001, 0.01, 300)}).to_csv("r.csv", index=False)
    pd.DataFrame({"x": rng.normal(0.001, 0.01, 300)}).to_csv("x.csv", index=False)
    assert aq("overfit", "pbo", "trials.csv", "--blocks", "8") == 0 and "PBO" in capsys.readouterr().out
    assert aq("overfit", "psr", "--returns", "r.csv") == 0 and "PSR" in capsys.readouterr().out
    assert aq("overfit", "dsr", "--returns", "x.csv", "--trials", "100", "--trial-variance", "0.3") == 0 and "DSR" in capsys.readouterr().out
    assert aq("overfit", "dsr", "--returns", "r.csv") == 2 and "--trials" in capsys.readouterr().err
    assert aq("overfit", "hurdle", "--trials", "258", "--trial-variance", "0.41", "--json") == 0 and json.loads(capsys.readouterr().out)["hurdle_sharpe"] > 1
    assert aq("overfit", "haircut", "--sharpe", "1.2", "--obs", "1000", "--trials", "258") == 0 and "haircut Sharpe" in capsys.readouterr().out
    assert aq("overfit", "mintrl", "--returns", "r.csv", "--target-sharpe", "0.5") == 0 and "minimum track record" in capsys.readouterr().out
    from evaluation import trial_ledger

    monkeypatch.setattr(trial_ledger, "project_deflation_inputs", lambda folder: {"N": 50, "var": 0.4})
    assert aq("overfit", "dsr", "--returns", "r.csv", "--from-ledger", "--periods", "365") == 0 and "N=50" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the lab
# ---------------------------------------------------------------------------


def test_lab_init_new_train_runs_show_eval_compare_card_export(lab, tmp_path, capsys):
    assert aq("lab", "init", tmp_path / "other") == 0 and "next: cd" in capsys.readouterr().out
    assert aq("lab", "new", "lin2", "--template", "linear") == 0 and "models/lin2/model.py" in capsys.readouterr().out
    assert aq("lab", "new", "lin2", "--template", "linear") == 1 and "--force" in capsys.readouterr().err
    assert aq("lab", "train", "lin", "--dry-run") == 0 and "features:" in capsys.readouterr().out
    assert aq("lab", "train", "lin", "--seeds", "1,2") == 0 and "out-of-sample IC" in capsys.readouterr().out
    assert aq("lab", "train", "lin2", "--set", "model.ridge=50", "--json") == 0 and json.loads(capsys.readouterr().out)["status"] == "finished"
    assert aq("lab", "runs") == 0 and "lin2" in capsys.readouterr().out
    assert aq("lab", "runs", "--json") == 0 and len(json.loads(capsys.readouterr().out)) == 2
    assert aq("lab", "show", "latest") == 0 and '"model": "lin2"' in capsys.readouterr().out
    assert aq("lab", "show", "latest", "--json") == 0
    assert aq("lab", "eval", "latest", "--book", "--html", tmp_path / "e.html") == 0 and "quintile book after costs" in capsys.readouterr().out
    runs = [row["id"] for row in json.loads((lambda: (aq("lab", "runs", "--json"), capsys.readouterr().out)[1])())]
    assert aq("lab", "compare", *runs, "--baseline", "momentum_20", "--html", tmp_path / "c.html") == 0 and "momentum_20" in capsys.readouterr().out
    assert aq("lab", "card", "latest") == 0 and "# Model card" in capsys.readouterr().out
    assert aq("lab", "card", "latest", "--out", tmp_path / "card.md") == 0 and (tmp_path / "card.md").exists()
    assert aq("lab", "export", "latest", "--name", "lab-demo") == 0 and (lab / "lab-demo.zip").exists()
    assert aq("lab", "show", "nonexistent") == 1 and "no run matches" in capsys.readouterr().err


def test_lab_sweep_explain_ablate_and_seeds(lab, capsys):
    assert aq("lab", "sweep", "lin", "--grid", "ridge=0.1,10", "--max-trials", "50") == 0 and "PBO" in capsys.readouterr().out
    assert aq("lab", "explain", "latest") == 0 and "permutation importance" in capsys.readouterr().out
    assert aq("lab", "ablate", "latest", "--json") == 0 and "groups" in json.loads(capsys.readouterr().out)
    assert aq("lab", "seeds", "latest", "--seeds", "2") == 0 and "2 seeds" in capsys.readouterr().out
    assert aq("lab", "sweep", "lin", "--grid", "ridge=1,2,3,4", "--max-trials", "2") == 1 and "max-trials" in capsys.readouterr().err


def test_the_holdout_is_spent_once_and_only_when_asked(lab, tmp_path, capsys, monkeypatch):
    assert aq("lab", "train", "lin") == 0
    capsys.readouterr()
    assert aq("lab", "eval", "latest", "--holdout") == 2 and "--i-understand-this-spends-it" in capsys.readouterr().err
    assert aq("lab", "eval", "latest", "--holdout", "--i-understand-this-spends-it") == 0
    assert (lab / "holdout_ledger.jsonl").exists()
    assert aq("lab", "eval", "latest", "--holdout", "--i-understand-this-spends-it") == 1 and "already spent" in capsys.readouterr().err
    monkeypatch.setattr(cli, "ROOT_DIR", tmp_path)
    assert aq("lab", "eval", "latest", "--holdout", "--i-understand-this-spends-it", "--project-ledger") == 0
    assert (tmp_path / "ml" / "generations" / "holdout_ledger.jsonl").exists()


def test_lab_commands_outside_a_lab_and_their_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert aq("lab", "runs") == 1 and "no lab here" in capsys.readouterr().err
    make_lab(tmp_path / "lab2", models={"ff": "mlp"})
    monkeypatch.setitem(sys.modules, "torch", None)
    assert aq("lab", "train", "ff", "--lab", tmp_path / "lab2") == 1 and "aether-quant[train]" in capsys.readouterr().err


def test_the_production_engine_runs_the_real_trainer_and_files_its_outputs(lab, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: None)
    monkeypatch.setattr(cli, "ROOT_DIR", tmp_path)
    assert aq("lab", "train", "x", "--engine", "production", "--production-kind", "tcn", "--objective", "listnet", "--resume", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "train_sequence.py" in out and "--ranking-objective listnet" in out and "--resume" in out

    def fake_live(command, **kwargs):
        version = command[command.index("--version-id") + 1]
        folder = tmp_path / "ml" / "versions" / version
        folder.mkdir(parents=True)
        (folder / "multitask_model.json").write_text("{}", encoding="utf-8")
        return 0

    monkeypatch.setattr(dev, "run_live", fake_live)
    assert aq("lab", "train", "x", "--engine", "production") == 0 and "aq stack lab-baseline" in capsys.readouterr().out
    run = next(path for path in (lab / "runs").iterdir() if "production_multitask" in path.name)
    assert (run / "production" / "multitask_model.json").exists() and json.loads((run / "run.json").read_text())["template"] == "production"
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: 9)
    assert aq("lab", "train", "x", "--engine", "production") == 9
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: 1)
    assert aq("lab", "train", "x", "--engine", "production") == 1


def test_a_runtime_error_in_the_lab_is_one_line(lab, monkeypatch, capsys):
    from lab import trainer

    monkeypatch.setattr(trainer, "train_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cuda gone")))
    assert aq("lab", "train", "lin") == 1 and "aq lab train: cuda gone" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------


def test_dataset_build_info_and_leakage(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    planted_closes().to_csv("closes.csv", index_label="date")
    assert aq("dataset", "build", "--prices", "closes.csv", "--features", "example", "--dry-run") == 0 and "would write" in capsys.readouterr().out
    splits = "train:2020-01-02..2020-12-31,validation:2021-01-01..2021-06-30,holdout:2021-07-01..2021-12-31"
    assert aq("dataset", "build", "--prices", "closes.csv", "--features", "example", "--splits", splits, "--out", "d/data.csv") == 0
    assert "holdout" in capsys.readouterr().out
    assert aq("dataset", "info", "d/data.csv") == 0 and "sealed holdout rows:" in capsys.readouterr().out
    assert aq("dataset", "info", "d/data.csv", "--json") == 0 and json.loads(capsys.readouterr().out)["holdout_rows"] > 0
    code = aq("dataset", "leakage", "d/data.csv", "--json")
    assert code in (0, 3) and "flagged" in json.loads(capsys.readouterr().out)
    frame = pd.read_csv("d/data.csv")
    frame["leak"] = frame["target_rank_20d"]
    frame.to_csv("d/leak.csv", index=False)
    assert aq("dataset", "leakage", "d/leak.csv") == 3 and "leak" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the installed stack (owner research)
# ---------------------------------------------------------------------------


def _fake_ml(tmp_path):
    ml = tmp_path / "ml"
    ml.mkdir()
    metrics = {"version_id": "v1", "trained_at": "2026-10-12T11:17:41.6", "best_epoch": 4,
               "validation": {"rank_20d_ic": {"mean_ic": 0.0123456}, "rank_5d_ic": {"mean_ic": None}, "note": "x"}, "backtest": {"rank_20d_ic": {"mean_ic": 0.05}}}
    (ml / "multitask_training_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (ml / "feature_schema.json").write_text(json.dumps({"model_input_names": ["ret_5", "vol_20"]}), encoding="utf-8")
    return ml


def test_stack_inspect_reads_the_installed_models(tmp_path, monkeypatch, capsys):
    ml = _fake_ml(tmp_path)
    assert aq("stack", "inspect", "--ml-dir", ml) == 0
    out = capsys.readouterr().out
    assert "multitask v1" in out and "rank_20d 0.0123/0.05" in out and "2 model inputs" in out and "FAILING" in out, "no pins file is a failing pin check"
    assert aq("stack", "inspect", "--ml-dir", ml, "--json") == 0 and json.loads(capsys.readouterr().out)["models"]["multitask"]["best_epoch"] == 4
    assert aq("stack", "inspect", "--ml-dir", tmp_path / "none") == 1 and "private" in capsys.readouterr().err
    (ml / "topology_training_metrics.json").write_text("[1, 2]", encoding="utf-8")
    assert "topology" not in cli.stack_inspect(ml)["models"], "a metrics file that is not an object is skipped"


def test_stack_decay_attrib_and_lab_baseline_score_the_live_blend(tmp_path, monkeypatch, capsys):
    ml = _fake_ml(tmp_path)
    closes = planted_closes()
    from lab import lab_dataset

    dataset = lab_dataset.build_dataset(closes, features="example", targets=(1, 5, 20)).rename(columns={"ret_5": "ret_5", "vol_20": "vol_20"})
    monkeypatch.setattr(cli, "stack_scores", lambda ml_dir, split, max_dates: dataset.assign(score=dataset["ret_20"], asset_class="crypto").copy()
                        if split != "backtest" else dataset[dataset["split"] == "backtest"].assign(score=dataset["ret_20"], asset_class="crypto"))
    assert aq("stack", "decay", "--ml-dir", ml, "--by", "class", "--html", tmp_path / "d.html") == 0
    assert "crypto: IC +" in capsys.readouterr().out and (tmp_path / "d.html").exists()
    assert aq("stack", "decay", "--ml-dir", ml, "--by", "year", "--json") == 0 and "2020" in json.loads(capsys.readouterr().out)["by"]
    assert aq("stack", "decay", "--ml-dir", ml, "--by", "split") == 0
    import aq_cli as main_cli

    monkeypatch.setattr(main_cli, "_blend_raw_scores_for_dataset", lambda frame, config, window, ml_dir=None: (frame["ret_20"].fillna(0).to_numpy(), {}))
    monkeypatch.setattr(cli, "ROOT_DIR", tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    assert aq("stack", "attrib", "--ml-dir", ml, "--split", "backtest") == 0 and "crypto:" in capsys.readouterr().out
    lab = make_lab(tmp_path / "lab")
    assert aq("stack", "lab-baseline", "--ml-dir", ml, "--lab", lab) == 0 and "aq lab compare" in capsys.readouterr().out
    run = next(path for path in (lab / "runs").iterdir() if "installed_stack" in path.name)
    assert (run / "scores.csv").exists() and json.loads((run / "run.json").read_text())["template"] == "installed"


def test_stack_scores_read_the_project_dataset_without_its_holdout(tmp_path, monkeypatch):
    dataset = pd.DataFrame({"date": ["2025-01-02", "2025-08-01", "2025-01-03"], "ticker": ["A", "A", "B"], "split": ["backtest", "backtest", "validation"],
                            "target_rank_20d": [0.5, 0.5, 0.5]})
    (tmp_path / "config.json").write_text(json.dumps({"splits": {"validation": {}, "holdout": {"start": "2025-07-01", "end": "2025-12-31"}}}), encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli, "_read_dataset_rows", lambda path: dataset.copy())
    monkeypatch.setattr(aq_cli, "_blend_raw_scores_for_dataset", lambda frame, config, window, ml_dir=None: (np.arange(len(frame), dtype=float), {}))
    monkeypatch.setattr(aq_cli, "_universe_asset_metadata", lambda config: ({"A": "equity"}, {}))
    scored = cli.stack_scores(tmp_path / "ml", split=None, max_dates=None)
    assert scored["date"].tolist() == ["2025-01-02", "2025-01-03"] and scored["asset_class"].tolist() == ["equity", "other"]
    assert cli.stack_scores(tmp_path / "ml", split="backtest", max_dates=1)["date"].tolist() == ["2025-01-02"]


# ---------------------------------------------------------------------------
# trials, runs, api-diff, release, health
# ---------------------------------------------------------------------------


def test_trials_count_list_dsr_and_add(tmp_path, capsys):
    from evaluation.trial_ledger import append_trial

    folder = tmp_path / "evaluation"
    (folder / "v671").mkdir(parents=True)
    (folder / "trial_registry.json").write_text(json.dumps({"trials": []}), encoding="utf-8")
    for index, sharpe in enumerate((0.2, 0.6, 1.0)):
        append_trial(folder / "v671" / "trial_ledger.jsonl", trial_id=f"t{index}", track="x", window="v660_selection", role="candidate", annualised_sharpe=sharpe, n_obs=100)
    assert aq("trials", "count", "--evaluation-dir", folder) == 0 and "N = 3" in capsys.readouterr().out
    assert aq("trials", "list", "--evaluation-dir", folder, "--phase", "v671", "--limit", "2") == 0 and capsys.readouterr().out.count("candidate") == 2
    pd.DataFrame({"returns": np.random.default_rng(1).normal(0.001, 0.01, 200)}).to_csv(tmp_path / "r.csv", index=False)
    assert aq("trials", "dsr", "--evaluation-dir", folder, "--returns", tmp_path / "r.csv") == 0 and "DSR is" in capsys.readouterr().out
    assert aq("trials", "dsr", "--evaluation-dir", folder, "--json") == 0 and json.loads(capsys.readouterr().out)["N"] == 3
    ledger = tmp_path / "manual.jsonl"
    assert aq("trials", "add", "--trial-id", "idea", "--role", "candidate", "--sharpe", "0.4", "--obs", "50", "--ledger", ledger, "--dry-run") == 0
    assert "would record idea" in capsys.readouterr().out and not ledger.exists()
    assert aq("trials", "add", "--trial-id", "idea", "--role", "candidate", "--sharpe", "0.4", "--obs", "50", "--note", "n", "--ledger", ledger) == 0 and ledger.exists()
    assert aq("trials", "count", "--evaluation-dir", tmp_path / "none") == 1 and "trial ledgers live" in capsys.readouterr().err


def test_lean_runs_list_show_and_diff(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT_DIR", tmp_path)
    assert aq("runs", "list") == 0 and "no runs" in capsys.readouterr().out
    for name, sharpe in (("2026-01-01_00-00-00", "0.5"), ("2026-01-02_00-00-00", "0.7")):
        folder = tmp_path / "backtests" / name
        folder.mkdir(parents=True)
        (folder / "123.json").write_text(json.dumps({"statistics": {"Sharpe Ratio": sharpe, "Net Profit": "10%"}}), encoding="utf-8")
        (folder / "123-summary.json").write_text("{}", encoding="utf-8")
        (folder / "bad.json").write_text("{", encoding="utf-8")
    (tmp_path / "backtests" / "2026-01-02_00-00-00" / "log.txt").write_text("Algorithm Id: x completed PythonInitializer.Shutdown() timed out", encoding="utf-8")
    (tmp_path / "ml" / "evaluation" / "run_configs").mkdir(parents=True)
    (tmp_path / "ml" / "evaluation" / "readme_lean_run.json").write_text(json.dumps({"run": "2026-01-01_00-00-00"}), encoding="utf-8")
    for name, value in (("2026-01-01_00-00-00", 1), ("2026-01-02_00-00-00", 2)):
        (tmp_path / "ml" / "evaluation" / "run_configs" / f"{name}.json").write_text(json.dumps({"k": value}), encoding="utf-8")
    assert aq("runs", "list", "--json") == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["run"] for row in rows} == {"2026-01-01_00-00-00", "2026-01-02_00-00-00"} and any(row["pinned"] for row in rows)
    assert aq("runs", "list") == 0 and "*pin" in capsys.readouterr().out
    assert aq("runs", "show", "2026-01-02_00-00-00") == 0 and "teardown timed out" in capsys.readouterr().out
    assert aq("runs", "show", "nope") == 2
    assert aq("runs", "diff", "2026-01-01_00-00-00", "2026-01-02_00-00-00") == 0 and "~ k: 1 -> 2" in capsys.readouterr().out
    (tmp_path / "ml" / "evaluation" / "run_configs" / "2026-01-01_00-00-00.json").unlink()
    assert aq("runs", "diff", "2026-01-01_00-00-00", "2026-01-02_00-00-00", "--json") == 0 and json.loads(capsys.readouterr().out)["config_diff"] is None
    assert aq("runs", "diff", "x", "2026-01-02_00-00-00") == 2
    assert cli.engine_log_verdict(tmp_path) == "no engine log (log.txt)"
    (tmp_path / "log.txt").write_text("Runtime Error", encoding="utf-8")
    assert cli.engine_log_verdict(tmp_path).startswith("errored")
    (tmp_path / "log.txt").write_text("quiet", encoding="utf-8")
    assert cli.engine_log_verdict(tmp_path) == "unknown"
    assert cli.run_summary(tmp_path / "backtests")["statistics"] == {}
    torn = tmp_path / "torn"
    torn.mkdir()
    (torn / "1.json").write_text("{", encoding="utf-8")
    assert cli.run_summary(torn)["result_id"] is None, "an unreadable result file is skipped"


def test_api_diff_and_its_semver_bump(monkeypatch, capsys):
    assert cli.api_diff({"m": ["a", "b"]}, {"m": ["a", "c"], "n": ["d"]}) == {"added": {"m": ["c"], "n": ["d"]}, "removed": {"m": ["b"]}, "bump": "major"}
    assert cli.api_diff({"m": ["a"]}, {"m": ["a", "b"]})["bump"] == "minor" and cli.api_diff({"m": ["a"]}, {"m": ["a"]})["bump"] == "patch"
    monkeypatch.setattr(cli, "latest_tag", lambda: "v1")
    monkeypatch.setattr(cli, "api_surface_at", lambda ref: {"m": ["a", "b"]} if ref else {"m": ["a"]})
    assert aq("api-diff") == 3 and "- m.b" in capsys.readouterr().out
    monkeypatch.setattr(cli, "api_surface_at", lambda ref: {"m": ["a"]} if ref else {"m": ["a", "z"]})
    assert aq("api-diff", "v0", "--json") == 0 and json.loads(capsys.readouterr().out)["against"] == "v0"
    monkeypatch.setattr(cli, "api_surface_at", lambda ref: None)
    assert aq("api-diff", "v0") == 1
    monkeypatch.setattr(cli, "latest_tag", lambda: None)
    assert aq("api-diff") == 1 and "no tag" in capsys.readouterr().err


def test_api_surfaces_come_from_git_and_the_tree(monkeypatch):
    monkeypatch.setattr(dev, "RUN", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout='{"m": ["x"]}' if "show" in command else "v6.6.8\n", stderr=""))
    assert cli.api_surface_at("v1") == {"m": ["x"]} and "signals" in cli.api_surface_at(None) and cli.latest_tag() == "v6.6.8"
    monkeypatch.setattr(dev, "RUN", lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr=""))
    assert cli.api_surface_at("v1") is None and cli.latest_tag() is None


def test_release_check_and_the_version_bump(tmp_path, monkeypatch, capsys):
    assert cli.implied_bump("v6.6.8", "v7.0.0") == "major" and cli.implied_bump("v6.6.8", "v6.7.0") == "minor" and cli.implied_bump("v6.6.8", "v6.6.9") == "patch"
    assert cli.implied_bump(None, "v1") == "major"
    answers = {("git", "status"): (0, ""), ("git", "rev-parse"): (0, "main\n")}

    smoke_calls = []
    install = {"code": 0}

    def capture(command, timeout=None, cwd=None, env=None):
        if command[1:3] == ["-m", "build"]:
            Path(command[-1], "aether_quant-1-py3-none-any.whl").write_text("w", encoding="utf-8")
            return 0, "built"
        if command[1:4] == ["-m", "pip", "install"]:
            return install["code"], "" if install["code"] == 0 else "pip: no matching distribution"
        if command[-1].endswith("wheel_smoke.py"):
            smoke_calls.append((cwd, env["PYTHONPATH"]))
            return 0, "smoke ok"
        return answers.get(tuple(command[:2]), (0, ""))

    monkeypatch.setattr(dev, "run_capture", capture)
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/bin/gh")
    monkeypatch.setattr(dev, "ci_runs", lambda sha: [{"workflowName": "CI", "status": "completed", "conclusion": "success", "jobs": []}])
    monkeypatch.setattr(cli, "latest_tag", lambda: "v6.6.8")
    monkeypatch.setattr(cli, "api_surface_at", lambda ref: {"m": ["a"]})
    checks = {check["name"]: check for check in cli.release_checks("v6.7.1")}
    assert checks["clean tree"]["status"] == "ok" and checks["on main"]["status"] == "ok" and checks["wheel builds"]["status"] == "ok"
    assert checks["wheel smoke"]["status"] == "ok" and checks["version vs API"]["status"] == "ok" and checks["tag"]["status"] == "manual"
    cwd, path = smoke_calls[-1]
    assert Path(path).name == "site-packages" and Path(path).parent == cwd and cli.ROOT_DIR not in Path(cwd).parents, "the smoke runs outside the checkout, on the wheel alone"
    install["code"] = 1
    assert {c["name"]: c for c in cli.release_checks("v6.7.1")}["wheel smoke"]["detail"] == "pip: no matching distribution"
    install["code"] = 0
    monkeypatch.setattr(cli, "api_surface_at", lambda ref: {"m": ["a", "b"]} if ref else {"m": ["a"]})
    assert {c["name"]: c for c in cli.release_checks("v6.6.9")}["version vs API"]["status"] == "fail"
    monkeypatch.setattr(cli, "release_checks", lambda version: [dev._check("x", "fail", "d"), dev._check("y", "manual", "m")])
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: None)
    assert aq("release", "check", "v1") == 3 and "✗ x: d" in capsys.readouterr().out
    monkeypatch.setattr(cli, "release_checks", lambda version: [dev._check("x", "ok", "d")])
    assert aq("release", "check", "v1", "--json") == 0
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: 1)
    assert aq("release", "check", "v1") == 1


def test_health_reports_and_keeps_a_history(tmp_path, monkeypatch, capsys):
    root = tmp_path
    (root / "risk").mkdir()
    (root / "risk" / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (root / "tool.py").write_text("z = 3\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("", encoding="utf-8")
    (root / "coverage-report").mkdir()
    (root / "coverage-report" / "coverage.json").write_text(json.dumps({"files": {"risk/a.py": {"summary": {"covered_lines": 1, "num_statements": 2}},
                                                                                   "tool.py": {"summary": {"covered_lines": 0, "num_statements": 0}}}}), encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "formal_inventory.py").write_text("BACKLOG_CEILING = 881\n", encoding="utf-8")
    (root / "scripts" / "library_gate.py").write_text("nothing here\n", encoding="utf-8")
    (root / "development").mkdir()
    (root / "development" / "Problems.md").write_text("### 1. A\n🟢 x\n### 2. B\n🟡 y\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('ignore = [\n    "E501",  # long\n]\n', encoding="utf-8")
    report = cli.health_report(root)
    assert report["loc"]["risk"] == 2 and report["loc"]["top-level"] == 1 and report["test_files"] == 1
    assert report["coverage_by_subsystem"] == {"risk": 50.0, "top-level": 100.0} and report["backlog_ceilings"] == {"formal_inventory": 881, "library_gate": None}
    assert report["problems"] == {"fixed": 1, "partial": 1} and report["ruff_ignores"] == 1
    assert cli.health_report(tmp_path / "empty")["loc_total"] == 0
    monkeypatch.setattr(cli, "ROOT_DIR", root)
    monkeypatch.setattr(cli, "health_report", lambda root=None: report)
    assert aq("health", "--history") == 0 and "lines of Python" in capsys.readouterr().out
    assert aq("health", "--history", "--json") == 0 and json.loads(capsys.readouterr().out)["trend"]["loc_total"] == 0
    assert len((root / "development" / "health_history.jsonl").read_text().splitlines()) == 2
    assert aq("health") == 0


def test_every_lab_command_is_registered():
    choices = dev._subparsers_of(aq_cli.build_parser())
    for name in ("data", "signal", "features", "overfit", "lab", "dataset", "stack", "trials", "runs", "api-diff", "release", "health"):
        assert name in choices and choices[name].epilog.startswith("Examples:")
    assert cli._lab_dir(SimpleNamespace(lab="x")) == Path("x")
