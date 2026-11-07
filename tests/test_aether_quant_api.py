"""The aether_quant library's contract (V6.4.3): every exported name resolves to the very function the system uses, the
import stays light (no torch / Lean / Redis / Postgres / web stack / sklearn), and the public surface only changes on
purpose (snapshot in tests/data/aether_quant_api.json; regenerate with AQ_UPDATE_API_SNAPSHOT=1)."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests" / "data" / "aether_quant_api.json"
MODULES = (
    "analyzer", "audit", "cycle", "data", "evaluation", "execution", "experience", "experts", "features", "formal", "inference", "io", "liquidity", "moe", "monitoring", "notifications", "performance",
    "portfolio", "regime", "research", "retraining", "risk", "topology", "training",
)
HEAVY = ("torch", "AlgorithmImports", "redis", "psycopg", "psycopg2", "fastapi", "uvicorn", "sklearn")


def _surface() -> dict[str, list[str]]:
    return {name: sorted(importlib.import_module(f"aether_quant.{name}").__all__) for name in MODULES}


def test_every_exported_name_resolves():
    for name in MODULES:
        module = importlib.import_module(f"aether_quant.{name}")
        for attribute in module.__all__:
            assert hasattr(module, attribute), f"aether_quant.{name}.{attribute}"


def test_facade_re_exports_the_same_objects():
    from aether_quant import audit, execution, portfolio, research, risk
    from audit import hash_chain
    from evaluation import pbo
    from execution import order_gate
    from portfolio import book_neutrality
    from risk import kill_switch

    assert portfolio.apply_book_neutrality is book_neutrality.apply_book_neutrality
    assert execution.resolve_order_permission is order_gate.resolve_order_permission
    assert risk.evaluate_kill_switch is kill_switch.evaluate_kill_switch
    assert audit.verify_chain is hash_chain.verify_chain
    assert research.probability_of_backtest_overfitting is pbo.probability_of_backtest_overfitting


def test_the_new_modules_re_export_the_same_objects():
    from aether_quant import cycle, moe, regime, retraining, topology, training
    from evaluation import alpha_decay, generation_registry
    from features import training_splits
    from moe import gating
    from portfolio import generation_blend
    from regime import market_regime
    from retraining import validation_gate
    from topology import market_topology

    assert cycle.update_generation_shares is generation_blend.update_generation_shares
    assert cycle.decay_state is alpha_decay.decay_state
    assert cycle.next_stage is generation_registry.next_stage
    assert training.purged_embargoed_folds is training_splits.purged_embargoed_folds
    assert moe.build_gating_decision is gating.build_gating_decision
    assert regime.build_market_regime_vector is market_regime.build_market_regime_vector
    assert retraining.evaluate_validation_gate is validation_gate.evaluate_validation_gate
    assert topology.build_market_topology is market_topology.build_market_topology


def test_the_trainers_import_the_moved_helpers_rather_than_keep_copies():
    import ast

    from features import training_splits

    moved = {"purge_label_overlap", "purge_label_overlap_calendar", "assign_split", "assign_split_series", "purged_embargoed_folds", "annual_windows", "rank_inputs", "centred_label"}
    assert moved <= set(dir(training_splits))
    for name in ("train.py", "train_cross_sectional.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        assert not moved & {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}, name


def test_importing_the_library_stays_light():
    code = ("import sys, importlib\n"
            f"for name in {MODULES!r}:\n    importlib.import_module('aether_quant.' + name)\n"
            f"print(sorted(m for m in {HEAVY!r} if m in sys.modules))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_public_surface_matches_the_snapshot():
    surface = _surface()
    if os.environ.get("AQ_UPDATE_API_SNAPSHOT") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(surface, indent=1) + "\n", encoding="utf-8")
    assert surface == json.loads(SNAPSHOT.read_text(encoding="utf-8")), "public API changed: update the snapshot deliberately"


def test_package_version_is_a_string():
    import aether_quant

    assert isinstance(aether_quant.__version__, str) and aether_quant.__version__
