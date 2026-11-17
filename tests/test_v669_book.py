"""scripts/v669_book.py: each subcommand calls the round's stage with the right inputs and writes what the install rule says (V6.6.9). The stages are tested in test_model_book_round.py."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from evaluation import model_book_research as research
from script_loader import load_script, run_script


@pytest.fixture
def book(monkeypatch, tmp_path):
    module = load_script("v669_book")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path / "ml" / "evaluation" / "v669")
    monkeypatch.setattr(module, "SCORES", tmp_path / "ml" / "evaluation" / "v669" / "scores")
    monkeypatch.setattr(module, "SELECTION_SCORES", tmp_path / "sel")
    (tmp_path / "ml").mkdir()
    return module


def test_rules_are_written_once(book, capsys):
    assert book.main(["rules"]) == 0
    assert "sha256" in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        book.main(["rules"])


def test_the_selection_stages_pass_their_options_to_the_round(book, monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(book, "selection_context", lambda: "context")
    monkeypatch.setattr(book.rnd, "score_stage", lambda context, out, **kwargs: seen.update(score=(context, kwargs)))
    monkeypatch.setattr(book.rnd, "placebo_stage", lambda context, out, **kwargs: seen.update(placebo=kwargs))
    monkeypatch.setattr(book.rnd, "gate_stage", lambda out: {"survivors": []})
    monkeypatch.setattr(book.rnd, "pbo_stage", lambda out, root: {"pbo": 0.4})
    monkeypatch.setattr(book.rnd, "diagnostics_stage", lambda context, out: seen.update(diagnostics=context))
    monkeypatch.setattr(book.rnd, "report_stage", lambda out: {"install": {"candidate": "b03"}})
    assert book.main(["score", "--only", "b02", "--force"]) == 0 and seen["score"] == ("context", {"ids": ["b02"], "force": True})
    assert book.main(["placebo", "--draws", "7", "--only", "b02"]) == 0 and seen["placebo"] == {"draws": 7, "only": ["b02"], "force": False, "suffix": "", "modes": None}
    assert book.main(["gate"]) == 0 and book.main(["pbo"]) == 0 and book.main(["diagnostics"]) == 0 and book.main(["report"]) == 0
    assert seen["diagnostics"] == "context"
    out = capsys.readouterr().out
    assert '"survivors"' in out and '"pbo"' in out and '"b03"' in out


def test_the_selection_context_reads_the_three_walk_forward_tables(book, monkeypatch):
    seen = {}
    monkeypatch.setattr(book.rnd, "load_round_context", lambda root, sources, end=None: seen.update(root=root, sources=sources, end=end) or "ctx")
    assert book.selection_context() == "ctx" and set(seen["sources"]) == {"ml_a1", "ml_a2", "ml_a3"} and seen["end"] == research.SELECTION[2]


def test_long_sources_join_the_selection_and_installed_tables_at_the_seam(book, monkeypatch):
    calls = []

    def combine(first, second, destination, last_selection):
        calls.append((first.name, second.name, destination.name, last_selection))
        return destination

    monkeypatch.setattr(book.rnd, "combine_score_files", combine)
    paths = book.long_sources()
    assert list(paths) == ["ml_a1", "ml_a2", "ml_a3"]
    assert calls[0] == ("ml_a1.csv", "inst_a1.csv", "long_a1.csv", research.SELECTION[2]) and calls[2][1] == "inst_a3.csv"


def test_freeze_writes_the_candidate_and_prints_its_hash(book, monkeypatch, capsys):
    monkeypatch.setattr(book.rnd, "freeze_stage", lambda out, root, code_files: (Path("freeze.json"), "abc"))
    assert book.main(["freeze"]) == 0 and "abc" in capsys.readouterr().out


def _scores_world(book, monkeypatch, tmp_path, *, problems):
    import evaluation.dataset_io as dataset_io
    import retraining.artifact_pins as pins

    ml = tmp_path / "ml"
    (ml / "datasets").mkdir(exist_ok=True)
    (ml / "datasets" / "full_dataset.csv").write_text("date,ticker,f\n", encoding="utf-8")
    (ml / "artifact_pins.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"phase1": {"universe": {"assets": [{"ticker": "A"}]}}}), encoding="utf-8")
    for model in ("multitask", "sequence"):
        (ml / f"{model}_model.json").write_text("{}", encoding="utf-8")
        (ml / f"{model}_feature_schema.json").write_text(json.dumps({"model_input_names": ["f"]}), encoding="utf-8")
    monkeypatch.setattr(book.rnd, "check_freeze", lambda out: {})
    monkeypatch.setattr(pins, "artifact_problems", lambda ml_dir, path: problems)
    seen = {}

    def read(path, columns, start=None):
        seen.update(columns=columns, start=start)
        return pd.DataFrame({"date": [], "ticker": [], "f": []})

    def tables(dataset, exports, **kwargs):
        seen.update(kwargs=kwargs)
        return {"inst_a1": pd.DataFrame({"date": ["2023-07-03"], "ticker": ["A"], "score": [0.5]})}

    monkeypatch.setattr(dataset_io, "read_dataset_columns", read)
    monkeypatch.setattr(book.research, "installed_score_tables", tables)
    monkeypatch.setattr(book, "long_sources", lambda: seen.update(long=True))
    return seen


def test_the_installed_scores_need_the_pinned_models_and_write_one_file_per_table(book, monkeypatch, tmp_path, capsys):
    _scores_world(book, monkeypatch, tmp_path, problems=["scaler_stats.json does not match its pin"])
    with pytest.raises(SystemExit, match="not the pinned ones"):
        book.main(["scores"])
    seen = _scores_world(book, monkeypatch, tmp_path, problems=[])
    assert book.main(["scores", "--through", "2026-11-13"]) == 0
    assert seen["kwargs"]["end"] == "2026-11-13" and seen["kwargs"]["start"] == research.VERIFICATION[0] and seen["start"] == "2023-03-01"
    assert seen["columns"][:2] == ["date", "ticker"] and seen["long"] is True
    assert (book.SCORES / "inst_a1.csv").read_text(encoding="utf-8").startswith("date,ticker,score")
    assert "inst_a1: 1 rows" in capsys.readouterr().out
    assert book.main(["scores"]) == 0 and seen["kwargs"]["end"] == research.VERIFICATION[1]


def test_verification_prints_everything_but_the_phases(book, monkeypatch, capsys):
    monkeypatch.setattr(book, "long_sources", dict)
    monkeypatch.setattr(book.rnd, "load_round_context", lambda root, sources, end=None: "ctx")
    monkeypatch.setattr(book.rnd, "verify_stage", lambda context, out: {"sharpe": 0.1, "phases": {0: {}}})
    assert book.main(["verify"]) == 0
    assert json.loads(capsys.readouterr().out) == {"sharpe": 0.1}


def _freeze_world(book, monkeypatch, *, survivor):
    book.OUT.mkdir(parents=True, exist_ok=True)
    frozen = {"candidate": "b03", "survivor": survivor, "definition": {"id": "b03", "universe": ["equity"], "every": 20, "table": "ml_a1", "params": {}}}
    monkeypatch.setattr(book.rnd, "check_freeze", lambda out: frozen)
    (book.OUT / "verification.json").write_text(json.dumps({"median_phase": 8}), encoding="utf-8")
    (book.OUT / "selection_scores.json").write_text(json.dumps({"b03": {"volatility": 0.05}}), encoding="utf-8")
    monkeypatch.setattr(book, "long_sources", dict)
    monkeypatch.setattr(book.rnd, "load_round_context", lambda root, sources, end=None: "ctx")
    seen = []

    def blend(context, out, **kwargs):
        seen.append(kwargs)
        return {"name": kwargs["name"]}

    monkeypatch.setattr(book.rnd, "blend_stage", blend)
    return seen


def test_a_non_survivors_share_is_the_fixed_one_and_a_survivors_follows_volatility(book, monkeypatch):
    seen = _freeze_world(book, monkeypatch, survivor=False)
    assert book.main(["blend"]) == 0
    assert [call["name"] for call in seen] == ["blend", "blend_long"] and all(call["share"] == research.NON_SURVIVOR_SHARE for call in seen)
    assert seen[0]["phase_index"] == 2 and seen[0]["start"] == research.VERIFICATION[0] and seen[1]["start"] == research.SELECTION[0]
    seen = _freeze_world(book, monkeypatch, survivor=True)
    assert book.main(["blend"]) == 0
    assert seen[0]["share"] == pytest.approx((1 / 0.05) / (1 / 0.05 + 1 / 0.07))


def test_judging_reads_the_lean_report_and_installing_needs_a_passing_verdict(book, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(book.rnd, "judge_stage", lambda out, lean: {"install": False, "lean": lean})
    assert book.main(["judge"]) == 0
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"corr_lag0": 0.97, "annual_gap_bps": 10.0}), encoding="utf-8")
    assert book.main(["judge", "--lean-report", str(report), "--completed", "--log-clean"]) == 0
    printed = capsys.readouterr().out
    assert '"correlation": 0.97' in printed and '"completed": true' in printed
    assert book.main(["install"]) == 1 and "no verdict yet" in capsys.readouterr().out
    book.OUT.mkdir(parents=True, exist_ok=True)
    (book.OUT / "r_install2.json").write_text(json.dumps({"install": False, "failed": ["lean_return_gap"]}), encoding="utf-8")
    assert book.main(["install"]) == 1 and "lean_return_gap" in capsys.readouterr().out


def _book_files(book, monkeypatch):
    book.OUT.mkdir(parents=True, exist_ok=True)
    frozen = {"candidate": "b03", "survivor": False, "definition": {"id": "b03", "universe": ["equity", "bond"], "every": 20, "table": "ml_a1", "params": {"optimizer": "inverse_vol", "table": "ml_a1"}}}
    monkeypatch.setattr(book.rnd, "check_freeze", lambda out: frozen)
    (book.OUT / "verification.json").write_text(json.dumps({"median_phase": 8}), encoding="utf-8")
    (book.OUT / "blend_blend.json").write_text(json.dumps({"model_share": 0.3}), encoding="utf-8")


def test_the_candidate_file_is_the_blended_definition(book, monkeypatch, tmp_path, capsys):
    _book_files(book, monkeypatch)
    (book.OUT / "pinned_run.json").write_text(json.dumps({"run": "2026-11-16_16-25-28"}), encoding="utf-8")
    assert book.main(["candidate"]) == 0
    written = json.loads((book.OUT / "candidate_blend.json").read_text(encoding="utf-8"))
    assert written["pinned_run"] == "2026-11-16_16-25-28" and [part["generation"] for part in written["parts"]] == ["g0001", "g0006"]
    assert book.main(["candidate", "--out", str(tmp_path / "elsewhere.json")]) == 0 and (tmp_path / "elsewhere.json").exists()
    assert "candidate written" in capsys.readouterr().out


def test_an_installing_verdict_copies_the_file_and_changes_three_config_values(book, monkeypatch, tmp_path, capsys):
    _book_files(book, monkeypatch)
    (tmp_path / "ml" / "target_weights_candidate.json").write_text(json.dumps({"survivors": ["old"]}), encoding="utf-8")
    (book.OUT / "r_install2.json").write_text(json.dumps({"install": True, "failed": []}), encoding="utf-8")
    (book.OUT / "weights").mkdir()
    (book.OUT / "weights" / "blend.csv").write_text("date,ticker,weight\n2023-07-10,SPY,0.1\n", encoding="utf-8")
    config = (
        '{\n  "phase_v2": {\n    "forex_risk": {\n      "enabled": false\n    },\n    "target_weights": {\n      "enabled": true,\n'
        f'      "weights_path": "ml/target_weights.csv",\n      "weights_sha256": "{"0" * 64}",\n      "min_weight_change": 0.002\n    }}\n  }}\n}}\n'
    )
    (tmp_path / "config.json").write_text(config, encoding="utf-8")
    assert book.main(["install"]) == 0
    installed = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["phase_v2"]
    assert installed["forex_risk"]["enabled"] is True and installed["target_weights"]["uses_model"] is True
    assert installed["target_weights"]["weights_sha256"] == hashlib.sha256((tmp_path / "ml" / "target_weights.csv").read_bytes()).hexdigest()
    assert "weights sha256" in capsys.readouterr().out
    assert json.loads((tmp_path / "ml" / "target_weights_candidate.json").read_text(encoding="utf-8"))["kind"] == "blend"
    assert json.loads((book.OUT / "candidate_before_install.json").read_text(encoding="utf-8")) == {"survivors": ["old"]}
    assert (tmp_path / "ml" / "artifact_pins.json").exists()


def test_run_as_a_script_it_refuses_a_missing_command(monkeypatch, capsys):
    assert run_script("v669_book", [], monkeypatch) == 2
    assert "required" in capsys.readouterr().err


def test_the_run_configs_point_each_run_at_its_weight_file_with_the_install_settings(book, monkeypatch, tmp_path):
    from script_loader import fake_module

    shipped = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
    (tmp_path / "config.json").write_text(json.dumps(shipped), encoding="utf-8")
    (book.OUT / "weights").mkdir(parents=True)
    for name in ("model_book.csv", "blend.csv", "blend_long.csv"):
        (book.OUT / "weights" / name).write_text(f"date,ticker,weight\n2023-07-03,{name},0.1\n", encoding="utf-8")
    seen = []

    def make(base, *, weights_path, weights_sha256, window):
        seen.append((base["phase_v2"]["forex_risk"]["enabled"], base["phase_v2"]["target_weights"]["uses_model"], weights_path, window))
        return {"weights_sha256": weights_sha256, "phase_v2": {"target_weights": {}}}

    fake_module(monkeypatch, "v650_instrument", RUN_CONFIGS=tmp_path / "run_configs", target_path_config=make)
    assert book.main(["configs"]) == 0
    assert [entry[2] for entry in seen] == ["ml/evaluation/v669/weights/model_book.csv", "ml/evaluation/v669/weights/blend.csv", "ml/evaluation/v669/weights/blend_long.csv", ""]
    assert all(entry[0] is True and entry[1] is True for entry in seen) and seen[2][3] == (research.SELECTION[0], research.VERIFICATION[1])
    parity = json.loads((tmp_path / "run_configs" / "v669_bt_p.json").read_text(encoding="utf-8"))["phase_v2"]
    assert parity["target_weights"]["source"] == "model_book" and parity["model_book"]["candidate_path"].endswith("candidate_blend.json")
    written = json.loads((tmp_path / "run_configs" / "v669_bt_b.json").read_text(encoding="utf-8"))
    assert written["weights_sha256"] == hashlib.sha256((book.OUT / "weights" / "blend.csv").read_bytes()).hexdigest()


def test_registering_adds_g0006_and_records_the_shares_only_for_an_installed_book(book, monkeypatch, tmp_path, capsys):
    from script_loader import fake_module

    _book_files(book, monkeypatch)
    (book.OUT / "freeze.sha256").write_text("a" * 64 + "\n", encoding="utf-8")
    (book.OUT / "r_install2.json").write_text(json.dumps({"install": True}), encoding="utf-8")
    for name in ("train.py", "train_multitask.py", "train_sequence.py", "train_gating.py"):
        (tmp_path / name).write_text("# trainer", encoding="utf-8")
    fake_module(monkeypatch, "cycle_retrain", PROCEDURES={"stack": {"trainers": ["train.py", "train_multitask.py", "train_sequence.py", "train_gating.py"]}}, procedure_sha256=lambda name, procedure, source: "p" * 64)
    calls = {}
    monkeypatch.setattr(book.rnd, "register_generation", lambda registry, lifecycle, **kwargs: calls.update(kwargs) or {"added": True})
    shares = {}
    monkeypatch.setattr(book.rnd, "set_installed_shares", lambda path, values: shares.update(values))
    assert book.main(["register"]) == 0
    assert calls["installed"] is True and calls["procedure_sha256"] == "p" * 64 and shares == {"g0001": 0.7, "g0006": 0.3}
    (book.OUT / "r_install2.json").write_text(json.dumps({"install": False}), encoding="utf-8")
    shares.clear()
    assert book.main(["register"]) == 0 and calls["installed"] is False and shares == {}
    assert '"added": true' in capsys.readouterr().out
