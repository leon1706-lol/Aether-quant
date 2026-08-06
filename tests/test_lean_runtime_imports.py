"""Regression guards for Lean's module-startup dependency boundary.

The Lean engine wraps importing ``main.py`` and ``initialize()`` in a hard
startup isolator.  ``performance`` is still used by the in-memory dashboard
view, but importing it at module scope pulls in the standalone trigger worker
and, transitively, ``train.py``/PyTorch.  These tests intentionally inspect
the AST instead of importing ``main.py`` because ``AlgorithmImports`` only
exists inside the Lean engine image.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "main.py"
LEAN_CONFIG_PATH = ROOT / "lean.json"


def _main_module_ast() -> ast.Module:
    return ast.parse(MAIN_PATH.read_text(encoding="utf-8"), filename=str(MAIN_PATH))


def _import_module(node: ast.Import | ast.ImportFrom) -> str:
    if isinstance(node, ast.Import):
        return node.names[0].name
    return node.module or ""


def test_main_does_not_import_performance_or_training_stack_at_module_scope():
    """Lean startup must not pull the performance/training stack into import."""
    tree = _main_module_ast()
    module_scope_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    imported_modules = {_import_module(node) for node in module_scope_imports}

    assert "performance" not in imported_modules
    assert "train" not in imported_modules


def test_performance_trigger_import_is_deferred_to_runtime_view():
    """The in-memory trigger view retains the import without early startup cost."""
    tree = _main_module_ast()
    algorithm_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AetherQuantAlgorithm"
    )
    method = next(
        node
        for node in algorithm_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_build_performance_triggers_view"
    )
    deferred_imports = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.ImportFrom) and node.module == "performance"
    ]

    assert len(deferred_imports) == 1
    assert [alias.name for alias in deferred_imports[0].names] == ["evaluate_all_triggers"]


def test_tracked_lean_config_uses_local_backtest_handlers_without_credentials():
    """Keep the committed Lean config in safe, local-backtest mode."""
    config = json.loads(LEAN_CONFIG_PATH.read_text(encoding="utf-8"))
    backtesting = config["environments"]["backtesting"]

    assert config["data-folder"] == "data"
    assert config["id"] == "Local"
    assert backtesting == {
        "live-mode": False,
        "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
        "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
        "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
        "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
        "history-provider": [
            "QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider"
        ],
        "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler",
    }
    assert all(config[key] == "" for key in ("ib-account", "ib-user-name", "ib-password"))
