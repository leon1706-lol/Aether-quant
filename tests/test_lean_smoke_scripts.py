"""Static checks of scripts/lean_smoke/: they run only inside Lean, so these pin what a run depends on (V6.5.0)."""

from pathlib import Path

from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "lean_smoke"


def test_structures_smoke_walks_the_whole_registry():
    text = (SMOKE / "option_structures.py").read_text(encoding="utf-8")
    assert "for name in MULTI_LEG_STRATEGY_REGISTRY]" in text
    assert len(MULTI_LEG_STRATEGY_REGISTRY) >= 43


def test_structures_smoke_builds_through_the_repos_selectors_and_leans_factory():
    text = (SMOKE / "option_structures.py").read_text(encoding="utf-8")
    assert "select_strategy_legs(name, rows, target_delta)" in text
    assert "getattr(OptionStrategies, spec.factory_name)" in text


def test_structures_smoke_covers_both_detectors():
    text = (SMOKE / "option_structures.py").read_text(encoding="utf-8")
    assert "select_arbitrage_signal" in text
    assert "assignment_risk_score" in text


def test_futures_smoke_makes_the_calls_main_makes():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    smoke = (SMOKE / "futures_margin.py").read_text(encoding="utf-8")
    for call in ("GetInitialMarginRequirement(", "SymbolProperties.ContractMultiplier", "InitialMarginParameters(security, 1)"):
        assert call in main
        assert call in smoke


def test_runner_is_lf_and_never_touches_the_repos_config():
    payload = (SMOKE / "run.sh").read_bytes()
    assert b"\r\n" not in payload
    text = payload.decode("utf-8")
    assert 'cat > "${DIR}/config.json"' in text
    assert "git " not in text


def test_option_scenarios_cover_the_four_problems_and_use_only_names_main_py_defines():
    text = (SMOKE / "main_option_scenarios.py").read_text(encoding="utf-8")
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    for scenario in ("_scenario_scale", "_all43_bar", "_scenario_arb", "_scenario_assign"):
        assert f"def {scenario}(" in text
    for name in (
        "_apply_option_multi_leg_order", "_liquidate_option_record", "_apply_option_assignment_risk_sweep", "latest_assignment_risk_by_symbol", "options_max_positions_per_underlying",
        "option_positions_by_symbol", "latest_options_chains_payload", "options_arbitrage_detector_enabled", "options_auto_close_days_before_expiry",
    ):
        assert name in text and name in main, name
    assert "list(MULTI_LEG_STRATEGY_REGISTRY)" in text and "_all43_bar" in text, "the all-structures scenario walks the registry on every bar until each structure builds"


def test_option_scenario_runner_is_lf_names_the_scenario_and_never_touches_the_repos_config():
    payload = (SMOKE / "run_main_option_scenarios.sh").read_bytes()
    assert b"\r\n" not in payload
    text = payload.decode("utf-8")
    assert '--scenario "${SCENARIO}"' in text and 'echo "${SCENARIO}" > "${DIR}/scenario.txt"' in text
    assert not any(command in text for command in ("git checkout", "git add", "git commit", "git push", "git reset", "git stash")) and 'out "${DIR}/config.json"' in text


def test_option_scenario_config_turns_on_what_each_scenario_exercises():
    import json
    import sys

    sys.path.insert(0, str(SMOKE))
    from make_option_main_config import option_main_config

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assign = option_main_config(base, "assign")["phase_v2"]["options_risk"]
    arb = option_main_config(base, "arb")["phase_v2"]["options_risk"]
    assert assign["assignment_risk_detector"]["enabled"] is True and arb["arbitrage_detector"]["enabled"] is True and arb["multi_leg_strategies_enabled"] is True
    assert base["phase_v2"]["options_risk"]["enabled"] is False, "the shipped config keeps options off"
    assert option_main_config(base, "scale")["phase_v2"]["options_risk"]["max_positions_per_underlying"] == 1


# --- V6.6.4 (B6): live-mode plumbing without a broker -----------------------------------------------------------------------------------------------

def test_live_plumbing_launcher_config_is_paper_with_a_fake_queue_and_leaves_lean_json_alone():
    import json
    from pathlib import Path

    from scripts.lean_smoke.make_live_plumbing_config import FAKE_QUEUE, launcher_config, project_config

    root = Path(__file__).resolve().parents[1]
    lean = json.loads((root / "lean.json").read_text(encoding="utf-8"))
    before = json.dumps(lean, sort_keys=True)
    config = launcher_config(lean)
    assert json.dumps(lean, sort_keys=True) == before, "lean.json is read, never changed"
    env = config["environments"]["live-paper-fake"]
    assert config["live-mode"] is True and env["live-mode-brokerage"] == "PaperBrokerage" and env["data-queue-handler"] == [FAKE_QUEUE]
    assert config["algorithm-type-name"] == "AetherQuantAlgorithm" and config["algorithm-location"] == "/LeanCLI/main.py"
    project = project_config({"phase1": {"universe": {"assets": [{"ticker": "BTCUSD"}, {"ticker": "XYZ"}]}}})
    assert [asset["ticker"] for asset in project["phase1"]["universe"]["assets"]] == ["BTCUSD"] and project["runtime"]["mode"] == "paper"


def test_live_plumbing_report_reads_stages_and_failures_from_logs():
    from scripts.lean_smoke.live_plumbing_report import build_report, scan_engine_log

    good = "\n".join(["LEAN ALGORITHMIC TRADING ENGINE v2.5.0.0", "main successfully imported", "creating brokerage 'PaperBrokerage'", "FakeDataQueue", "TICKS PER SECOND:: 2000.0", "Algorithm finished warming up"])
    assert scan_engine_log(good)["failures"] == [] and all(value for name, value in scan_engine_log(good).items() if name != "failures")
    assert scan_engine_log(good + "\nTraceback (most recent call last):")["failures"]
    report = build_report({"engine": good, "algorithm": "AuditQueue.push failed: x\nAuditQueue.push failed: y"}, {"engine": good, "algorithm": ""},
                          {"alive_after_outages": True, "state_file_after_restart": True, "audit_verify_ok": True, "audit_verify_text": "table is empty — trivially valid."})
    scenarios = report["scenarios"]
    assert all(item["passed"] for item in scenarios.values()) and scenarios["audit_chain_verifies"]["vacuous"] is True
    assert scenarios["alive_through_redis_and_postgres_outages"]["audit_push_failures_logged"] == 2 and report["not_proved"]
    dead = build_report({"engine": "nothing"}, {"engine": ""}, {})
    assert not any(item["passed"] for item in dead["scenarios"].values())
