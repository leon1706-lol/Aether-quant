"""Offline/live parity for accounts (V6.6.5, #349, rule 6): main.py and `aq evaluate --account` derive an account's
effective config through the one function, `execution.accounts.apply_risk_overrides`."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from execution.accounts import apply_risk_overrides, parse_accounts
from execution.accounts_io import load_account_config

ROOT = Path(__file__).resolve().parents[1]


def test_main_applies_the_overrides_to_phase_v2_with_the_shared_function():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "apply_risk_overrides"]
    assert len(calls) == 1
    assert ast.unparse(calls[0].args[0]) == "self.phase_v2"


def test_the_offline_loader_gives_the_same_effective_config(tmp_path, monkeypatch):
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "accounts.example.json").read_text(encoding="utf-8"))
    (tmp_path / "accounts.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.delenv("AQ_ACCOUNTS_FILE", raising=False)
    for account in parse_accounts(registry, config["phase_v2"]):
        live_side = apply_risk_overrides(config["phase_v2"], account)
        offline = load_account_config(config, account.id, tmp_path)
        assert offline["phase_v2"] == live_side, account.id
        assert offline["phase_v2"]["risk"]["kill_switch"] == live_side["risk"]["kill_switch"]
    assert load_account_config(config, None, tmp_path)["phase_v2"] == config["phase_v2"]


def test_aq_evaluate_takes_the_account_flag():
    import aq_cli

    args = aq_cli.build_parser().parse_args(["evaluate", "--account", "paper-b"])
    assert args.account == "paper-b"
