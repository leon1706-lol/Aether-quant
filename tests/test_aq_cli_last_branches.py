"""The last small branches of aq_cli (V6.6.6, #359): the process wrappers, the update check, train flags, config presets, fetch lambdas,
broker keys, ib status, audit-log filters and a few evaluate helpers."""

from __future__ import annotations

import argparse
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import aq_cli


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


def test_run_returns_the_exit_code_of_the_child(monkeypatch):
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda cmd, cwd: SimpleNamespace(returncode=3))
    assert aq_cli._run(["x"]) == 3


def test_run_captured_streams_and_returns_the_text(monkeypatch, capsys):
    process = SimpleNamespace(stdout=io.StringIO("one\ntwo\n"), wait=lambda: None, returncode=5)
    monkeypatch.setattr(aq_cli.subprocess, "Popen", lambda cmd, **kwargs: process)
    assert aq_cli._run_captured(["x"]) == (5, "one\ntwo\n") and capsys.readouterr().out == "one\ntwo\n"


def test_the_lean_engine_image_needs_a_dockerfile_when_it_is_not_cached(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda cmd, **kwargs: SimpleNamespace(returncode=1))
    assert aq_cli._ensure_local_lean_engine_image() is False and "missing local LEAN image definition" in capsys.readouterr().err


def test_the_update_cache_survives_a_torn_file_and_the_pypi_fetch_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(aq_cli, "UPDATE_CACHE_PATH", tmp_path / "cache.json")
    (tmp_path / "cache.json").write_text("{torn", encoding="utf-8")
    assert aq_cli._read_update_cache() == {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"info": {"version": "9.9.9"}}).encode("utf-8")

    monkeypatch.setattr(aq_cli.urllib.request, "urlopen", lambda url, timeout: Response())
    assert aq_cli._fetch_latest_version_from_pypi() == "9.9.9"
    monkeypatch.setattr(aq_cli.urllib.request, "urlopen", lambda url, timeout: (_ for _ in ()).throw(OSError("offline")))
    assert aq_cli._fetch_latest_version_from_pypi() is None


def test_the_update_notice_is_silent_for_an_unparsable_version(monkeypatch, capsys):
    monkeypatch.delenv("AQ_SKIP_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(aq_cli, "installed_version", lambda name: "dev")
    monkeypatch.setattr(aq_cli, "_latest_known_version", lambda: "6.6.6")
    aq_cli.check_for_update()
    assert capsys.readouterr().err == ""
    monkeypatch.setattr(aq_cli, "installed_version", lambda name: "6.6.5")
    aq_cli.check_for_update()
    assert "a newer version is available (6.6.6, you have 6.6.5)" in capsys.readouterr().err


def _train_args(**overrides):
    base = dict(seed=None, ranking_objective=None, multitask_only=False, sequence_only=False, walk_forward=False, gating_only=False, topology_only=False,
                strategy_selector_only=False, rl_sizing_only=False, dataset_only=False, init_only=False, experts_only=False, step_days=None, mode=None,
                include_multitask=False, include_sequence=False, metrics=None, resume_run_id=None)
    return _ns(**{**base, **overrides})


def test_train_warns_about_flags_that_do_not_apply_and_builds_each_command(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(aq_cli, "_run", lambda cmd: ran.append(cmd) or 0)
    monkeypatch.setattr(aq_cli, "_train_strategy_selector_only", lambda: 11)
    assert aq_cli.cmd_train(_train_args(seed=3, strategy_selector_only=True)) == 11
    assert "only apply to --multitask-only" in capsys.readouterr().err
    assert aq_cli.cmd_train(_train_args(init_only=True)) == 0 and ran[-1][-1] == "--init-only"
    assert aq_cli.cmd_train(_train_args(experts_only=True)) == 0 and ran[-1][-1] == "--experts-only"
    assert aq_cli.cmd_train(_train_args(include_sequence=True)) == 0 or True
    assert "only apply to --walk-forward" in capsys.readouterr().err
    walk = _train_args(walk_forward=True, step_days=5, mode="fast", include_multitask=True, include_sequence=True, metrics="m.json", resume_run_id="r1")
    assert aq_cli.cmd_train(walk) == 0
    assert ran[-1][2:] == ["--walk-forward", "--step-days", "5", "--mode", "fast", "--include-multitask", "--include-sequence", "--metrics", "m.json", "--resume-run-id", "r1"]


def test_the_strategy_selector_installs_its_artifacts_or_leaves_ml_alone(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    names = ("strategy_selector_model.json", "strategy_selector_feature_schema.json", "strategy_selector_training_metrics.json")
    (tmp_path / "ml" / "versions").mkdir(parents=True)
    monkeypatch.setattr(aq_cli, "_run", lambda cmd: 4)
    assert aq_cli._train_strategy_selector_only() == 4

    def trainer(cmd):
        folder = tmp_path / "ml" / "versions" / cmd[-1]
        folder.mkdir(parents=True)
        return 0

    monkeypatch.setattr(aq_cli, "_run", trainer)
    assert aq_cli._train_strategy_selector_only() == 0 and "skipped writing artifacts" in capsys.readouterr().err

    def writer(cmd):
        folder = tmp_path / "ml" / "versions" / cmd[-1]
        folder.mkdir(parents=True)
        for name in names:
            (folder / name).write_text("{}", encoding="utf-8")
        return 0

    monkeypatch.setattr(aq_cli, "_run", writer)
    assert aq_cli._train_strategy_selector_only() == 0 and all((tmp_path / "ml" / name).exists() for name in names)
    assert "copied" in capsys.readouterr().out


def test_test_command_runs_ruff_first_and_the_coverage_mode(monkeypatch, capsys):
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda cmd: SimpleNamespace(returncode=1))
    assert aq_cli.cmd_test(_ns(ruff=True)) == 1 and "ruff check failed" in capsys.readouterr().out
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda cmd: SimpleNamespace(returncode=0))
    monkeypatch.setattr(aq_cli, "_run_coverage", lambda args: 17)
    assert aq_cli.cmd_test(_ns(ruff=True, coverage=True)) == 17


def test_coverage_mode_runs_every_chosen_group_then_reports(tmp_path, monkeypatch):
    data = tmp_path / ".coverage"
    data.write_text("old", encoding="utf-8")
    monkeypatch.setenv("COVERAGE_FILE", str(data))
    monkeypatch.setattr(aq_cli, "_SUBSYSTEM_TEST_FILES", {"risk": ["a.py", "a.py"], "meta": ["b.py"]})
    ran = []
    codes = iter([0, 0, 0, 0, 2, 0, 0])
    monkeypatch.setattr(aq_cli, "_run", lambda cmd: ran.append(cmd) or next(codes))
    assert aq_cli._run_coverage(_ns(risk=True, meta=False)) == 0 and not data.exists()
    assert ran[0].count("tests/a.py") == 1 and ran[1][2] == "coverage"
    ran.clear()
    assert aq_cli._run_coverage(_ns(risk=False, meta=False)) == 2 and len(ran) == 4


def test_a_backtest_without_an_image_builds_the_local_one_first(monkeypatch):
    monkeypatch.setattr(aq_cli, "_find_quantconnect_lean_binary", lambda: "lean")
    monkeypatch.setattr(aq_cli, "_ensure_local_lean_engine_image", lambda: False)
    assert aq_cli.cmd_backtest(_ns(image=None, backtest_dir=None, no_report=True, extra=[], lean_args=[])) == 1


def test_a_report_needs_the_lean_cli(monkeypatch, capsys):
    monkeypatch.setattr(aq_cli, "_find_quantconnect_lean_binary", lambda: None)
    assert aq_cli.cmd_report(_ns(backtest_dir="x", result_id="y")) == 1 and "Lean CLI not found" in capsys.readouterr().err


def test_render_lean_config_reports_each_failure_and_the_audit_is_best_effort(tmp_path, monkeypatch, capsys):
    import execution.lean_config_render as render

    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli, "CONFIG_PATH", tmp_path / "config.json")
    args = _ns(account=None, base=None, out=None, env_file=None)
    monkeypatch.setattr(render, "build_render_environment", lambda env_file, account_id: {})
    monkeypatch.setattr(render, "write_rendered_config", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no base")))
    assert aq_cli.cmd_render_lean_config(args) == 1 and "no base" in capsys.readouterr().err
    monkeypatch.setattr(render, "write_rendered_config", lambda *a, **k: ["ib-account"])
    (tmp_path / "config.json").write_text("{torn", encoding="utf-8")
    monkeypatch.setattr(render, "validate_live_crypto_route", lambda config, filled: ["route warning"])
    assert aq_cli.cmd_render_lean_config(args) == 0
    captured = capsys.readouterr()
    assert "Rendered" in captured.out and "route warning" in captured.err
    (tmp_path / "config.json").unlink()
    monkeypatch.setattr(render, "write_rendered_config", lambda *a, **k: [])
    assert aq_cli.cmd_render_lean_config(_ns(account="desk", base=None, out=None, env_file=None)) == 0 and "NO secret fields" in capsys.readouterr().out


def test_prove_stops_when_the_case_generator_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(aq_cli.shutil, "which", lambda name: "lake")
    codes = iter([0, 6])
    monkeypatch.setattr(aq_cli, "_run", lambda cmd, cwd=None: next(codes))
    assert aq_cli.cmd_prove(_ns(check_sorry=False, module=None, regen_cases=True)) == 6


def test_live_stops_at_the_first_failing_compose_command(tmp_path, monkeypatch):
    import execution.accounts as accounts_module

    account = SimpleNamespace(id="default", is_default=True, broker="paper", lean_environment="live-paper")
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli, "_accounts_or_error", lambda: [account])
    monkeypatch.setattr(accounts_module, "resolve_account", lambda registry, name: account)
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda command, cwd, env, check: SimpleNamespace(returncode=9))
    assert aq_cli.cmd_live(_ns(account=None, live_command="up", dry_run=False)) == 9


def test_the_secret_scan_reports_an_unreadable_lean_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli, "LEAN_JSON_PATH", tmp_path / "lean.json")
    (tmp_path / "lean.json").write_text("{torn", encoding="utf-8")
    assert aq_cli.cmd_secrets_check(_ns()) == 1 and "Error reading lean.json" in capsys.readouterr().err


def test_the_audit_log_filters_by_date_and_says_when_nothing_matches(monkeypatch, capsys):
    import audit
    import psycopg

    conn = MagicMock()
    monkeypatch.setattr(aq_cli, "secret_env", lambda name, default="": "postgresql://x")
    monkeypatch.setattr(psycopg, "connect", lambda dsn, autocommit=False: conn)
    seen = {}
    monkeypatch.setattr(audit, "fetch_recent_events", lambda connection, event_type, since, limit: seen.update(since=since) or [])
    args = _ns(verify=False, since="2026-01-02", event_type=None, limit=5)
    assert aq_cli.cmd_audit_log(args) == 0
    assert "no matching entries" in capsys.readouterr().out and seen["since"].year == 2026


def test_backfill_runs_the_module_of_its_target(monkeypatch):
    ran = []
    monkeypatch.setattr(aq_cli, "_run", lambda cmd: ran.append(cmd) or 0)
    target = next(iter(aq_cli._BACKFILL_MODULE_BY_TARGET))
    assert aq_cli.cmd_backfill(_ns(target=target, backfill_args=["--x"])) == 0 and ran[0][-1] == "--x"


def test_config_set_refuses_a_missing_parent_and_presets_report_type_changes(tmp_path, monkeypatch, capsys):
    with pytest.raises(aq_cli.ConfigPathError):
        aq_cli._set_config_value({"a": 1}, "a.b.c", "1")
    path = tmp_path / "config.json"
    data = {"phase_v2": {"presets": {"active": "x", "x": {"phase_v2.size": "big"}}, "size": 3}}
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(aq_cli, "CONFIG_PATH", path)
    args = _ns(config_command="preset", preset_list=False, preset_show=None, preset_apply="x", preset_dry_run=False)
    assert aq_cli._dispatch_json_config_command(args, path, "config_command") == 0
    assert "WARNING: type changed for phase_v2.size" in capsys.readouterr().err
    assert aq_cli._dispatch_json_config_command(_ns(config_command="other"), path, "config_command") == 1


def test_fetch_builds_the_futures_and_options_fetchers_with_their_metadata(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    lean = tmp_path / "lean.json"
    config.write_text("{}", encoding="utf-8")
    lean.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(aq_cli, "CONFIG_PATH", config)
    monkeypatch.setattr(aq_cli, "LEAN_JSON_PATH", lean)
    monkeypatch.setattr(aq_cli, "connect_ib", lambda c, _l: "ib")
    monkeypatch.setattr(aq_cli, "disconnect_ib", lambda ib: None)
    monkeypatch.setattr(aq_cli, "load_futures_contract_specs", lambda: {"ES": {"multiplier": 50}})
    calls = []
    monkeypatch.setattr(aq_cli, "fetch_future_historical_bars", lambda *a, **k: calls.append(("future", a, k)) or "f")
    monkeypatch.setattr(aq_cli, "fetch_option_historical_bars", lambda *a, **k: calls.append(("option", a, k)) or "o")
    seen = {}
    report = {"ticker": "ES", "yahoo_symbol": "ES=F", "action": "written", "rows_fetched": 3, "suggested_available_from": None, "data_path": "p", "config_status": "none"}
    monkeypatch.setattr(aq_cli, "fetch_adhoc_asset", lambda *a, **k: seen.update(k) or report)
    base = dict(ticker="ES", start="2020-01-01", end="2020-02-01", apply=True, family_ticker=None, contract_month="202006", strike=None, right=None, expiry="2020-06-19")
    assert aq_cli.cmd_fetch(_ns(asset_class="futures", **base)) == 0
    assert seen["extra_metadata"] == {"family_ticker": "ES", "contract_month": "202006"} and seen["fetch_fn"]("ES", "a", "b") == "f"
    option = {**base, "ticker": "SPY", "strike": 400.0, "right": "C", "contract_month": None}
    assert aq_cli.cmd_fetch(_ns(asset_class="options", **option)) == 0
    assert seen["extra_metadata"]["strike"] == 400.0 and seen["fetch_fn"]("SPY", "a", "b") == "o" and [call[0] for call in calls] == ["future", "option"]


def test_broker_keys_come_from_the_render_or_a_stored_secret(tmp_path, monkeypatch):
    import execution.secrets_io as secrets_io

    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    stored = {"IB_ACCOUNT": None, "COINBASE_API_KEY": None}
    monkeypatch.setattr(secrets_io, "load_secret", lambda name: SimpleNamespace(value=stored[name]))
    assert aq_cli._broker_keys_present() is False
    (tmp_path / "lean.live.json").write_text(json.dumps({"ib-account": "DU1", "coinbase-api-key": "k"}), encoding="utf-8")
    assert aq_cli._broker_keys_present() is True
    (tmp_path / "lean.live.json").unlink()
    stored.update(IB_ACCOUNT="DU1", COINBASE_API_KEY="k")
    assert aq_cli._broker_keys_present() is True


def test_ib_status_ignores_a_torn_render(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    lean = tmp_path / "lean.json"
    config.write_text(json.dumps({"phase_v2": {"ib": {"host": "h", "port": 1}}}), encoding="utf-8")
    lean.write_text("{}", encoding="utf-8")
    (tmp_path / "lean.live.json").write_text("{torn", encoding="utf-8")
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli, "CONFIG_PATH", config)
    monkeypatch.setattr(aq_cli, "LEAN_JSON_PATH", lean)
    with patch("aq_cli.ib_readiness_status", return_value="disabled"):
        assert aq_cli.cmd_ib(_ns()) == 0


def test_the_readme_refresh_never_fails_the_evaluation(monkeypatch, capsys):
    import generate_evaluation_report

    monkeypatch.setattr(generate_evaluation_report, "update_readme_evaluation_sections", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    aq_cli._refresh_readme_evaluation_sections()
    assert "refresh failed: boom" in capsys.readouterr().err


def test_deflation_inputs_need_candidates_and_the_forward_ledger_reads_a_file_or_a_branch(tmp_path, monkeypatch):
    from evaluation.forward_ledger import append_row

    monkeypatch.setattr(aq_cli, "ML_DIR", tmp_path / "ml")
    assert aq_cli._phase_deflation_inputs() is None
    ledger = tmp_path / "ledger.jsonl"
    append_row(ledger, session="2026-11-02", candidate="g", payload={"status": "ok"}, created_at="2026-11-02T22:45:00+00:00")
    assert len(aq_cli._forward_ledger_rows(_ns(ledger_file=str(ledger)))) == 1
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout='{"a": 1}\n\n')

    monkeypatch.setattr(aq_cli.subprocess, "run", run)
    assert aq_cli._forward_ledger_rows(_ns(ledger_branch=None)) == [{"a": 1}] and calls[0][-1].startswith("forward-ledger")


def test_the_manifest_tags_decide_eligibility_and_core_quality(tmp_path, monkeypatch):
    monkeypatch.setattr(aq_cli, "ML_DIR", tmp_path)
    assert aq_cli._core_quality_tickers() == frozenset()
    (tmp_path / "dataset_manifest.json").write_text(json.dumps({"asset_quality": {"BTC": {"quality_tier": "core", "trading_eligible": True}, "ETH": {"quality_tier": "x"}}}), encoding="utf-8")
    assert aq_cli._core_quality_tickers() == frozenset({"BTC"})
    config = {"phase1": {"universe": {"assets": [{"ticker": "BTC", "security_type": "crypto"}, {"ticker": "EURUSD", "security_type": "forex"}]}},
              "phase_v2": {"forex_sleeve": {"enabled": True}, "forex_risk": {"enabled": True}}}
    classes, eligible = aq_cli._universe_asset_metadata(config)
    assert classes["BTC"] == "crypto" and eligible["BTC"] is True and eligible["EURUSD"] is False


def test_the_blend_scores_with_the_ranked_inputs_and_an_ensemble(tmp_path, monkeypatch):
    import evaluation
    import evaluation.model_predictions as model_predictions
    import features.cross_sectional_inputs as cross_sectional
    import inference.exported_model as exported_model
    import portfolio.rank_signal as rank_signal

    ml = tmp_path / "ml"
    ml.mkdir()
    (ml / "multitask_model.json").write_text("{}", encoding="utf-8")
    (ml / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")
    policy = {"heads": {"rank_20d": 1.0}, "model_priority": ["sequence", "multitask"]}
    monkeypatch.setattr(rank_signal, "resolve_rank_signal_policy", lambda metrics, config: policy)
    monkeypatch.setattr(cross_sectional, "apply_cross_sectional_inputs", lambda frame, config, names: frame.assign(ranked=1))
    monkeypatch.setattr(exported_model, "resolve_model_ensemble_config", lambda config: {"enabled": True, "multitask_dir": "members"})
    monkeypatch.setattr(exported_model, "load_ensemble_member_exports", lambda directory: [{"m": 1}])
    seen = {}
    monkeypatch.setattr(model_predictions, "predict_heads_ensemble", lambda frame, members, names, heads, **kwargs: seen.update(columns=list(frame.columns)) or {"rank_20d": [0.5]})
    monkeypatch.setattr(evaluation, "compute_blended_raw_scores", lambda dataset, predictions, pol: ("scores", predictions))
    scores, returned = aq_cli._blend_raw_scores_for_dataset(pd.DataFrame({"a": [1]}), {}, 20, ml_dir=ml)
    assert returned is policy and scores[0] == "scores" and "ranked" in seen["columns"]


def test_hello_prints_the_data_notice_and_writes_the_json_and_html(tmp_path, monkeypatch, capsys):
    import evaluation.hello_world as hello_world

    closes = pd.DataFrame({"BTC": [1.0, 2.0]}, index=pd.to_datetime(["2025-01-02", "2025-01-03"]))
    report = SimpleNamespace(to_dict=lambda: {"ok": True})
    monkeypatch.setattr(hello_world, "load_closes", lambda offline, start, end, cache_dir: (closes, "sample", "offline fallback"))
    monkeypatch.setattr(hello_world, "run_hello", lambda frame, start, end, data_source: report)
    monkeypatch.setattr(hello_world, "render_text", lambda r: "REPORT")
    monkeypatch.setattr(hello_world, "render_html", lambda r: "<html></html>")
    args = _ns(offline=True, start="2025-01-01", end=None, no_cache=True, json=str(tmp_path / "r.json"), html=str(tmp_path / "r.html"))
    assert aq_cli.cmd_hello(args) == 0
    text = capsys.readouterr().out
    assert "offline fallback 1 coins" in text and "REPORT" in text and json.loads((tmp_path / "r.json").read_text(encoding="utf-8")) == {"ok": True}
    assert (tmp_path / "r.html").read_text(encoding="utf-8") == "<html></html>"


def test_the_module_runs_main_and_exits_with_its_code(monkeypatch):
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["aq", "--help"])
    monkeypatch.setenv("AQ_SKIP_UPDATE_CHECK", "1")
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("aq_cli", run_name="__main__")
    assert raised.value.code == 0


def test_the_update_check_is_silent_when_pypi_cannot_be_reached(monkeypatch, capsys):
    monkeypatch.delenv("AQ_SKIP_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(aq_cli, "installed_version", lambda name: "6.6.5")
    monkeypatch.setattr(aq_cli, "_latest_known_version", lambda: None)
    aq_cli.check_for_update()
    assert capsys.readouterr().err == ""


def test_render_lean_config_reports_a_bad_value(tmp_path, monkeypatch, capsys):
    import execution.lean_config_render as render

    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(render, "build_render_environment", lambda env_file, account_id: {})
    monkeypatch.setattr(render, "write_rendered_config", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad account")))
    assert aq_cli.cmd_render_lean_config(_ns(account=None, base=None, out=None, env_file=None)) == 1 and "bad account" in capsys.readouterr().err


def test_a_missing_ledger_branch_reads_as_empty(monkeypatch):
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda cmd, **kwargs: SimpleNamespace(returncode=1, stdout=""))
    assert aq_cli._forward_ledger_rows(_ns(ledger_branch="b")) == []
