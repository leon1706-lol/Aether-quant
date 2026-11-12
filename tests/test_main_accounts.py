"""main.py's account and field-test wiring (V6.6.5, #349, #351), on the real config and artifacts, with the smoke test's stub.

The default account must change nothing: the same phase_v2, the same output and override paths, no tagged audit queue,
and no field test. A named account tightens the config, writes under state/accounts/<id>/ and tags its audit events.
Skipped where `ml/` is absent, like tests/test_main_ensure_ready_smoke.py; tests/test_accounts.py covers the pure layer."""

from __future__ import annotations

import datetime
import json
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("config.json", "ml/feature_schema.json", "ml/scaler_stats.json")

pytestmark = pytest.mark.skipif(not all((ROOT / name).exists() for name in REQUIRED), reason="needs config.json and trained ml/ artifacts")


class _PermissiveQCAlgorithm:
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = MagicMock(name=name)
        object.__setattr__(self, name, value)
        return value


def _ready_algorithm(monkeypatch, env: dict[str, str]):
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = _PermissiveQCAlgorithm
    stub.Slice = object
    stub.time = datetime.time
    monkeypatch.setitem(sys.modules, "AlgorithmImports", stub)
    monkeypatch.delitem(sys.modules, "main", raising=False)
    monkeypatch.chdir(ROOT)
    for key in ("AQ_ACCOUNT", "AQ_ACCOUNTS_FILE", "AQ_FIELD_TEST"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import main  # noqa: PLC0415

    instance = main.AetherQuantAlgorithm()
    instance._write_state = lambda *args, **kwargs: None
    instance.Debug = lambda message: None
    instance.Log = lambda message: None
    instance.Time = datetime.datetime(2019, 1, 2)
    for _ in range(80):
        try:
            if "_initialized_once" not in instance.__dict__:
                instance.initialize()
                instance.__dict__["_initialized_once"] = True
            instance._ensure_ready()
            break
        except NameError as error:
            match = re.search(r"name '(\w+)' is not defined", str(error))
            if not match:
                raise
            main.__dict__[match.group(1)] = MagicMock(name=match.group(1))
    return main, instance


def test_the_default_account_changes_nothing(monkeypatch):
    main, algorithm = _ready_algorithm(monkeypatch, {})
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assert algorithm._account.is_default
    assert algorithm.state_path == ROOT / "visualization" / "state.json" and algorithm.grafana_dir == ROOT / "visualization" / "grafana"
    assert algorithm._override_config_path == ROOT / "config.json"
    assert algorithm.phase_v2["live"] == config["phase_v2"]["live"] and algorithm.phase_v2["risk"] == config["phase_v2"]["risk"]
    assert type(algorithm._audit_queue).__name__ == "AuditQueue"
    assert algorithm._field_test_active is False


def test_a_named_account_tightens_and_namespaces(monkeypatch, tmp_path):
    registry = tmp_path / "accounts.json"
    registry.write_text((ROOT / "accounts.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    main, algorithm = _ready_algorithm(monkeypatch, {"AQ_ACCOUNT": "paper-b", "AQ_ACCOUNTS_FILE": str(registry)})
    assert algorithm._account.id == "paper-b"
    assert algorithm.state_path == ROOT / "state" / "accounts" / "paper-b" / "visualization" / "state.json"
    assert algorithm._override_config_path == ROOT / "state" / "accounts" / "paper-b" / "overrides.json"
    assert algorithm.phase_v2["live"]["max_allowed_total_drawdown_pct"] == 0.08
    assert algorithm.phase_v2["dynamic_risk"]["max_leverage"] == 0.5
    assert type(algorithm._audit_queue).__name__ == "AccountTaggedQueue"


def test_the_field_test_needs_the_flag_the_plan_and_a_paper_mode(monkeypatch, tmp_path):
    _, algorithm = _ready_algorithm(monkeypatch, {"AQ_FIELD_TEST": "1"})
    assert algorithm._field_test_active is False  # the committed config has no plan and runs in backtest mode
