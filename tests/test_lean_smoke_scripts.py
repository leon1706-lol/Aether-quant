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
