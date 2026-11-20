"""evaluation/model_book_round.py: the round's stages on a synthetic project root (V6.6.9). The windows are moved onto the synthetic data by patching the module constants."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import train_world as world
from evaluation import model_book_research as research
from evaluation import model_book_round as rnd

WINDOW = ("2018-09-03", "2019-01-02", "2019-06-28")
VERIFICATION = ("2019-07-01", "2019-12-30")


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = world.build_root(tmp_path_factory.mktemp("book"))
    sessions = pd.bdate_range("2018-01-02", "2019-12-31")
    rng = np.random.default_rng(11)
    tickers = world.EQUITIES + world.BONDS + world.CRYPTO + world.FOREX
    scores = root / "scores"
    scores.mkdir()
    for name in ("ml_a1", "ml_a2", "ml_a3"):
        rows = [(day.strftime("%Y-%m-%d"), ticker, float(rng.random())) for day in sessions for ticker in tickers]
        pd.DataFrame(rows, columns=["date", "ticker", "score"]).to_csv(scores / f"{name}.csv", index=False)
    return root


@pytest.fixture
def small_round(project, monkeypatch, tmp_path):
    monkeypatch.setattr(research, "SELECTION", WINDOW)
    monkeypatch.setattr(research, "VERIFICATION", VERIFICATION)
    sources = {name: project / "scores" / f"{name}.csv" for name in ("ml_a1", "ml_a2", "ml_a3")}
    context = rnd.load_round_context(project, sources, end=WINDOW[2])
    out = tmp_path / "v669"
    rnd.write_rules(out, rnd.rules_payload(written="2019-01-01"))
    return context, out, sources


def test_the_rules_are_written_once_and_a_changed_file_is_caught(tmp_path):
    out = tmp_path / "v669"
    payload = rnd.rules_payload(written="2026-11-16")
    digest = rnd.write_rules(out, payload)
    assert rnd.check_rules(out)["counted_trials"] == 26 and len(digest) == 64
    assert set(payload["trials"]) == {*(f"b{n:02d}" for n in range(1, 14)), *(f"m{n:02d}" for n in range(1, 7)), "core"}
    with pytest.raises(FileExistsError):
        rnd.write_rules(out, payload)
    (out / "rules.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="rules.json changed"):
        rnd.check_rules(out)


def test_a_round_context_holds_the_aligned_tables_and_the_model_sizing(small_round):
    context, _, _ = small_round
    assert {"ml_a1", "mix_trend", "mix_a23", "const"} <= set(context.panel.extras)
    assert context.settings == research.model_settings() and "forex" not in context.disabled_classes
    assert context.panel.extras["ml_a1"]["BTCUSD"].iloc[:2].isna().all()  # a crypto score is used a row late


def test_scoring_appends_candidates_and_controls_once_and_refuses_a_window_past_the_selection(small_round):
    context, out, _ = small_round
    lines = []
    scores = rnd.score_stage(context, out, window=WINDOW, ids=["b02", "core", "b01"], log=lines.append)
    assert set(scores) == {"b02", "core", "b01"} and len(lines) == 3
    assert {"volatility", "class_breadth", "mean_gross"} <= set(scores["b02"])
    ledger = [json.loads(line) for line in (out / "trial_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(entry["trial_id"], entry["role"]) for entry in ledger} == {("b02", "candidate"), ("core", "plumbing"), ("b01", "plumbing")}
    rnd.score_stage(context, out, window=WINDOW, ids=["b02"], log=lines.append)
    assert len(lines) == 3 and len((out / "trial_ledger.jsonl").read_text(encoding="utf-8").splitlines()) == 3
    rnd.score_stage(context, out, window=WINDOW, ids=["b02"], force=True, log=lines.append)
    assert len(lines) == 4
    with pytest.raises(SystemExit, match="past the selection window"):
        rnd.score_stage(context, out, window=(WINDOW[0], WINDOW[1], "2019-12-31"))


def test_placebos_run_only_for_trials_that_pass_the_sharpe_clauses(small_round, monkeypatch):
    context, out, _ = small_round
    rnd.score_stage(context, out, window=WINDOW, ids=["b02", "b03"], log=lambda text: None)
    scores = rnd.read_json(out / "selection_scores.json")
    assert rnd.placebo_stage(context, out, draws=2, window=WINDOW, log=lambda text: None) == {} or all(name in scores for name in rnd.read_json(out / "selection_placebos.json", {}))
    monkeypatch.setattr(rnd, "passes_sharpe_clauses", lambda score: True)
    lines = []
    done = rnd.placebo_stage(context, out, draws=2, only=["b02"], window=WINDOW, log=lines.append)
    assert set(done) == {"b02"} and set(done["b02"]) == {"asset_block", "time_shift"} and len(lines) == 2
    again = rnd.placebo_stage(context, out, draws=2, only=["b02"], window=WINDOW, log=lines.append)
    assert len(lines) == 2 and again == done
    placebos = [json.loads(line) for line in (out / "trial_ledger.jsonl").read_text(encoding="utf-8").splitlines() if '"placebo"' in line]
    assert placebos and all(entry["role"] == "placebo" for entry in placebos)


def test_the_gate_the_pbo_and_the_report_name_a_candidate(small_round, monkeypatch, project):
    context, out, _ = small_round
    rnd.score_stage(context, out, window=WINDOW, log=lambda text: None)
    monkeypatch.setattr(rnd, "passes_sharpe_clauses", lambda score: True)
    rnd.placebo_stage(context, out, draws=2, only=["b02"], window=WINDOW, log=lambda text: None)
    gate = rnd.gate_stage(out)
    assert set(gate) == {"survivors", "failed", "unscored"} and gate["unscored"] == []
    prior = project / "ml" / "evaluation" / "v650"
    prior.mkdir(parents=True)
    index = pd.bdate_range(WINDOW[0], WINDOW[2]).strftime("%Y-%m-%d")
    pd.DataFrame({name: np.random.default_rng(i).normal(0, 0.01, len(index)) for i, name in enumerate(rnd.PBO_PRIOR_COLUMNS)}, index=index).to_parquet(prior / "selection_daily.parquet")
    pbo = rnd.pbo_stage(out, root=project, blocks=4)
    assert pbo["num_trials"] >= 4 and 0.0 <= pbo["pbo"] <= 1.0
    no_prior = rnd.pbo_stage(out, root=project / "nowhere", blocks=4)
    assert no_prior["num_trials"] >= 1
    rnd.diagnostics_stage(context, out, log=lambda text: None)
    again = rnd.diagnostics_stage(context, out, log=lambda text: None)
    assert len(again) == 8
    report = rnd.report_stage(out)
    assert set(report) == {"trials", "gate", "pbo", "survivors", "diagnostics", "install"} and report["install"]["candidate"]
    assert report["survivors"] in ([], gate["survivors"])


def test_a_candidate_is_frozen_once_and_the_freeze_is_checked(small_round, project):
    _, out, _ = small_round
    with pytest.raises(SystemExit, match="no candidate"):
        rnd.freeze_stage(out, root=project, code_files=["config.json"])
    rnd.write_json(out / "r_book1.json", {"install": {"candidate": "b03", "reason": "test"}, "survivors": []})
    path, digest = rnd.freeze_stage(out, root=project, code_files=["config.json", "does/not/exist.py"])
    frozen = rnd.check_freeze(out)
    assert frozen["candidate"] == "b03" and frozen["survivor"] is False and list(frozen["code_sha256"]) == ["config.json"]
    assert frozen["definition"]["params"]["optimizer"] == "inverse_vol" and len(digest) == 64 and path.exists()
    spec = rnd.candidate_spec(frozen)
    assert spec.id == "b03" and spec.rebalance_every == 20 and spec.universe == research.CLASSES
    with pytest.raises(FileExistsError):
        rnd.freeze_stage(out, root=project, code_files=[])
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="freeze.json changed"):
        rnd.check_freeze(out)


def test_the_core_stands_in_as_a_frozen_control_and_verification_blend_and_judge_run(small_round, project):
    context, out, _ = small_round
    rnd.write_json(out / "r_book1.json", {"install": {"candidate": "core", "reason": "none eligible"}, "survivors": []})
    rnd.freeze_stage(out, root=project, code_files=[])
    lines = []
    summary = rnd.verify_stage(context, out, window=VERIFICATION, log=lines.append)
    assert len(lines) == 5 and summary["candidate"] == "core" and summary["median_phase"] in summary["phases"]
    assert (out / "weights" / "model_book.csv").exists()
    blend = rnd.blend_stage(context, out, name="blend", start=VERIFICATION[0], end=VERIFICATION[1], share=0.3, phase_index=0)
    assert blend["model_share"] == 0.3 and blend["rows"] >= blend["crypto_rows"] and len(blend["sha256"]) == 64
    assert (out / "weights" / "blend.csv").exists()
    lean = rnd.lean_summary({"corr_lag0": 0.97, "annual_gap_bps": 40.0, "run": "r", "name": "n"}, completed=True, engine_log_clean=True)
    assert lean["annual_return_gap"] == pytest.approx(0.004)
    verdict = rnd.judge_stage(out, lean=lean)
    assert verdict["candidate"] == "core" and "clauses" in verdict and (out / "r_install2.json").exists()
    none = rnd.judge_stage(out, lean=None)
    assert "lean_completed" in none["failed"]


def test_the_combined_score_file_switches_models_at_the_seam(tmp_path):
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    pd.DataFrame({"date": ["2023-06-29", "2023-06-30", "2023-07-03"], "ticker": ["A"] * 3, "score": [0.1, 0.2, 0.3]}).to_csv(first, index=False)
    pd.DataFrame({"date": ["2023-06-30", "2023-07-03", "2023-07-04"], "ticker": ["A"] * 3, "score": [0.9, 0.8, 0.7]}).to_csv(second, index=False)
    merged = pd.read_csv(rnd.combine_score_files(first, second, tmp_path / "c.csv", last_selection="2023-06-30"))
    assert merged["date"].tolist() == ["2023-06-29", "2023-06-30", "2023-07-03", "2023-07-04"]
    assert merged["score"].tolist() == [0.1, 0.2, 0.8, 0.7]


def test_the_inverse_volatility_share_favours_the_calmer_sleeve():
    assert rnd.inverse_vol_share(0.05, 0.05) == pytest.approx(0.5)
    assert rnd.inverse_vol_share(0.04, 0.08) == pytest.approx(2.0 / 3.0)


def test_the_install_edits_three_values_in_the_config_text_and_nothing_else():
    text = (
        '{\n  "phase_v2": {\n    "forex_risk": {\n      "enabled": false,\n      "x": 1\n    },\n    "target_weights": {\n      "enabled": true,\n'
        f'      "weights_path": "ml/target_weights.csv",\n      "weights_sha256": "{"0" * 64}",\n      "min_weight_change": 0.002\n    }}\n  }}\n}}\n'
    )
    changed = rnd.install_config_text(text, weights_sha256="a" * 64)
    assert json.loads(changed)["phase_v2"]["forex_risk"]["enabled"] is True
    block = json.loads(changed)["phase_v2"]["target_weights"]
    assert block["uses_model"] is True and block["weights_sha256"] == "a" * 64 and block["min_weight_change"] == 0.002
    assert len(changed.splitlines()) == len(text.splitlines()) + 1
    with pytest.raises(ValueError, match="uses_model"):
        rnd.install_config_text(changed, weights_sha256="b" * 64)
    with pytest.raises(ValueError, match="forex_risk"):
        rnd.install_config_text(text.replace('"enabled": false', '"enabled": true'), weights_sha256="c" * 64)


def test_the_real_config_has_the_shape_the_install_expects():
    config = (world.REPO / "config.json").read_text(encoding="utf-8")
    changed = rnd.install_config_text(config, weights_sha256="d" * 64) if '"uses_model"' not in config else config
    assert json.loads(changed)["phase_v2"]["target_weights"]["weights_sha256"] in ("d" * 64, json.loads(config)["phase_v2"]["target_weights"]["weights_sha256"])



def test_a_decision_for_the_last_sessions_is_the_verification_row_and_stale_scores_are_named(small_round, project):
    context, out, _ = small_round
    rnd.write_json(out / "r_book1.json", {"install": {"candidate": "b03", "reason": "test"}, "survivors": []})
    rnd.freeze_stage(out, root=project, code_files=[])
    frozen = rnd.check_freeze(out)
    definition = rnd.book_definition(frozen)
    assert definition.parts[0].generation == "model" and definition.shares == {"model": 1.0} and definition.history_start == VERIFICATION[0]
    session = "2019-07-03"
    row = rnd.decide_row(context, frozen, session)
    assert row is not None and all(isinstance(weight, float) for weight in row.values())
    assert rnd.score_problem(context, session) is None
    assert "days older" in rnd.score_problem(context, "2020-03-02")
    empty = rnd.with_tables(context, {"ml_a1": context.panel.extras["ml_a1"].iloc[:0]})
    assert "no score" in rnd.score_problem(empty, session)
    assert rnd.phase_index_of(frozen) == 0 and rnd.phase_index_of(frozen, {}) == 0
    assert rnd.phase_index_of(frozen, {"median_phase": 8}) == 2 and rnd.book_definition(frozen, {"median_phase": 8}).parts[0].phase_index == 2


def test_two_placebo_processes_write_their_own_files_and_the_gate_merges_them(small_round, monkeypatch):
    context, out, _ = small_round
    rnd.score_stage(context, out, window=WINDOW, ids=["b02"], log=lambda text: None)
    monkeypatch.setattr(rnd, "passes_sharpe_clauses", lambda score: True)
    first = rnd.placebo_stage(context, out, draws=2, only=["b02"], window=WINDOW, log=lambda text: None, suffix="_a", modes=["asset_block"])
    second = rnd.placebo_stage(context, out, draws=2, only=["b02"], window=WINDOW, log=lambda text: None, suffix="_b", modes=["time_shift"])
    assert set(first["b02"]) == {"asset_block"} and set(second["b02"]) == {"time_shift"}
    assert (out / "selection_placebos_a.json").exists() and (out / "selection_placebos_b.json").exists() and (out / "trial_ledger_a.jsonl").exists()
    gate = rnd.gate_stage(out)
    assert "b02" in gate["failed"] and rnd.read_json(out / "selection_gate.json")["unscored"]


def test_the_candidate_file_names_both_parts_the_sizing_and_the_phase_the_run_used():
    from portfolio.model_book import parse_definition, weight_settings

    frozen = {"definition": {"id": "b03", "universe": list(research.CLASSES), "every": 20, "params": {"optimizer": "inverse_vol", "table": "ml_a1"}}}
    raw = rnd.candidate_file(frozen, {"median_phase": 8}, share=0.3, pinned_run="2026-11-16_16-25-28")
    parsed = parse_definition(raw)
    assert [(part.generation, part.kind, part.phase_index) for part in parsed.parts] == [("g0001", "sleeve", 4), ("g0006", "book", 2)]
    assert parsed.shares == {"g0001": pytest.approx(0.7), "g0006": 0.3} and parsed.history_start == research.VERIFICATION[0] and parsed.pinned_run == "2026-11-16_16-25-28"
    book, sleeve = weight_settings(parsed)
    assert book.name_cap_by_class["forex"] == 0.06 and sleeve.name_cap == 0.15


def test_the_model_book_is_registered_once_as_installed_or_as_a_shadow_observer(tmp_path):
    from evaluation.generation_registry import Generation, lifecycle_is_intact, load_registry, save_registry
    from evaluation.generation_registry import read_lifecycle as lifecycle

    registry = tmp_path / "registry.json"
    log = tmp_path / "lifecycle.jsonl"
    save_registry(registry, {"g0001": Generation("g0001", "rule", "installed", "active", "2026-11-04", "x" * 64, {"id": "t3"})})
    frozen = {"definition": {"id": "b03", "universe": list(research.CLASSES), "every": 20, "table": "ml_a1", "params": {"optimizer": "inverse_vol"}}}
    added = rnd.register_generation(registry, log, frozen=frozen, freeze_sha256="f" * 64, installed=True, procedure_sha256="p" * 64, born="2026-11-16", created_at="2026-11-16T12:00:00+00:00")
    assert added == {"added": True, "generation": "g0006", "tier": "installed", "stage": "active"}
    entry = load_registry(registry)["g0006"]
    assert entry.kind == "model" and entry.needs == "model" and entry.definition["freeze_sha256"] == "f" * 64 and "reinstated, not verified" in entry.note
    assert rnd.register_generation(registry, log, frozen=frozen, freeze_sha256="f", installed=False, procedure_sha256="p", born="d", created_at="c")["added"] is False
    assert lifecycle_is_intact(log)[0] and len(lifecycle(log)) == 1
    other = tmp_path / "other.json"
    save_registry(other, {})
    shadow = rnd.register_generation(other, tmp_path / "other.jsonl", frozen=frozen, freeze_sha256="f", installed=False, procedure_sha256="p" * 64, born="2026-11-16", created_at="2026-11-16T12:00:00+00:00")
    assert shadow["tier"] == "none" and shadow["stage"] == "shadow" and "holds nothing" in load_registry(other)["g0006"].note


def test_the_installed_shares_go_to_the_policy_file_without_touching_its_other_keys(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text('{"enabled": false, "glide": {"mode": "dynamic"}}', encoding="utf-8")
    assert rnd.set_installed_shares(policy, {"g0001": 0.7, "g0006": 0.3}) == {"g0001": 0.7, "g0006": 0.3}
    stored = json.loads(policy.read_text(encoding="utf-8"))
    assert stored["enabled"] is False and stored["glide"] == {"mode": "dynamic"} and stored["installed_shares"] == {"g0001": 0.7, "g0006": 0.3}


def test_an_installed_blend_gives_a_row_on_a_decision_day_and_none_between(small_round, project):
    context, out, _ = small_round
    rnd.write_json(out / "r_book1.json", {"install": {"candidate": "b03", "reason": "test"}, "survivors": []})
    rnd.freeze_stage(out, root=project, code_files=[])
    raw = rnd.candidate_file(rnd.check_freeze(out), {"median_phase": 0}, share=0.3, pinned_run=None)
    sessions = [day for day in context.panel.known.index if "2019-07-01" <= day <= "2019-09-27"]
    rows = {day: rnd.blend_row(raw, context, day) for day in sessions}
    decided = [day for day, row in rows.items() if row is not None]
    assert 0 < len(decided) < len(sessions) and all(isinstance(rows[day], dict) for day in decided)


def test_another_round_runs_every_stage_on_its_own_trials_and_controls(small_round, monkeypatch, project):
    """V6.6.10 (R-BOOK2): the stages take a round's own trial list and controls; with no survivor the report names no candidate and
    nothing can be frozen, and a survivor is frozen from that round's list."""
    from portfolio.premia_signals import XS, SleeveSpec

    context, out, _ = small_round
    trial = SleeveSpec("q01", "B2", XS, "external_score", research.CLASSES, 20, {"table": "ml_a2", **research.GUARD, "optimizer": "inverse_vol"})
    control = SleeveSpec("q00", "B2C", XS, "external_score", research.CLASSES, 20, {"table": "ml_a1", **research.GUARD, "optimizer": "inverse_vol"})
    scores = rnd.score_stage(context, out, window=WINDOW, specs=[trial, control], control_ids=("q00",), log=lambda text: None)
    assert set(scores) == {"q01", "q00"}
    ledger = {json.loads(line)["trial_id"]: json.loads(line)["role"] for line in (out / "trial_ledger.jsonl").read_text(encoding="utf-8").splitlines()}
    assert ledger == {"q01": "candidate", "q00": "plumbing"}
    monkeypatch.setattr(rnd, "passes_sharpe_clauses", lambda score: True)
    assert set(rnd.placebo_stage(context, out, draws=2, window=WINDOW, log=lambda text: None, pool=[trial])) == {"q01"}
    gate = rnd.gate_stage(out, pool=[trial])
    assert gate["unscored"] == [] and set(gate["failed"]) | set(gate["survivors"]) == {"q01"}
    pbo = rnd.pbo_stage(out, root=project / "nowhere", blocks=4, pool=[trial])
    assert pbo["num_trials"] == 1 and set(pbo["absent"]) == set(rnd.PBO_PRIOR_COLUMNS), "the pool's own column, no prior on this root"
    rnd.write_json(out / "selection_pbo.json", {"pbo": 0.9})
    report = rnd.report_stage(out, name="r_book2.json", survivors_only=True)
    assert report["install"] == {"candidate": None, "reason": "no trial survived the gate and the PBO"} and (out / "r_book2.json").exists()
    with pytest.raises(SystemExit, match="nothing to freeze"):
        rnd.freeze_stage(out, root=project, code_files=[], report_name="r_book2.json", specs=[trial, control])
    rnd.write_json(out / "selection_pbo.json", {"pbo": 0.1})
    rnd.write_json(out / "selection_gate.json", {"survivors": ["q01"], "failed": {}})
    report = rnd.report_stage(out, name="r_book2.json", survivors_only=True)
    assert report["survivors"] == ["q01"] and report["install"]["candidate"] in ("q01", "core")
    rnd.write_json(out / "r_book2.json", {"install": {"candidate": "q01", "reason": "test"}, "survivors": ["q01"]})
    rnd.freeze_stage(out, root=project, code_files=[], report_name="r_book2.json", specs=[trial, control])
    frozen = rnd.check_freeze(out)
    assert frozen["candidate"] == "q01" and frozen["survivor"] is True and frozen["definition"]["table"] == "ml_a2"

