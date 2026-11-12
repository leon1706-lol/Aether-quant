"""execution/accounts.py (V6.6.5, #349): a registry that can only tighten, and the default account that changes nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from execution.accounts import (
    DEFAULT_ACCOUNT,
    OVERRIDE_KEYS,
    Account,
    AccountTaggedQueue,
    account_output_paths,
    account_state_dir,
    apply_risk_overrides,
    override_path,
    parse_accounts,
    resolve_account,
    tag_audit_event,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = {
    "live": {"max_allowed_daily_drawdown_pct": 0.05, "max_allowed_total_drawdown_pct": 0.15},
    "dynamic_risk": {"max_leverage": 1.0},
    "risk": {"kill_switch": {"min_rolling_sharpe": -100.0, "max_consecutive_losses": 100000}},
    "runtime": {"mode": "paper", "allow_live_orders": False},
    "reconciliation": {"max_tolerated_drift": 0.05},
}


def test_no_registry_is_the_default_alone_and_the_default_changes_nothing():
    accounts = parse_accounts({})
    assert accounts == (DEFAULT_ACCOUNT,)
    assert resolve_account(accounts, "") is DEFAULT_ACCOUNT and resolve_account(accounts, None) is DEFAULT_ACCOUNT
    out = apply_risk_overrides(BASE, DEFAULT_ACCOUNT)
    assert out == BASE and out is not BASE
    assert account_state_dir(Path("/r"), DEFAULT_ACCOUNT) == Path("/r") and override_path(Path("/r"), DEFAULT_ACCOUNT) == Path("/r/config.json")
    assert account_output_paths(Path("/r"), DEFAULT_ACCOUNT)["state_path"] == Path("/r/visualization/state.json")


def test_the_example_registry_parses_against_the_real_config():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    accounts = parse_accounts(json.loads((ROOT / "accounts.example.json").read_text(encoding="utf-8")), config["phase_v2"])
    assert [account.id for account in accounts] == ["default", "paper-a", "paper-b"]
    tightened = apply_risk_overrides(config["phase_v2"], accounts[2])
    assert tightened["live"]["max_allowed_total_drawdown_pct"] == 0.08 and tightened["dynamic_risk"]["max_leverage"] == 0.5


def test_a_named_account_tightens_namespaces_and_tags():
    account = Account("live-1", "coinbase", "live-coinbase", "observation", 25_000.0, {"live.max_allowed_total_drawdown_pct": 0.1, "runtime.allow_live_orders": False})
    out = apply_risk_overrides(BASE, account)
    assert out["live"]["max_allowed_total_drawdown_pct"] == 0.1 and out["runtime"]["mode"] == "observation" and BASE["runtime"]["mode"] == "paper"
    assert account_state_dir(Path("/r"), account) == Path("/r/state/accounts/live-1")
    assert override_path(Path("/r"), account) == Path("/r/state/accounts/live-1/overrides.json")
    event = {"event_type": "order_placement", "payload": {"symbol": "BTCUSD"}}
    assert tag_audit_event(event, account)["payload"] == {"symbol": "BTCUSD", "account_id": "live-1"}
    assert tag_audit_event(event, DEFAULT_ACCOUNT) == event and "account_id" not in event["payload"]


def test_the_tagged_queue_tags_and_delegates():
    pushed = []

    class Queue:
        enabled = True

        def push(self, event):
            pushed.append(event)
            return "ok"

    queue = AccountTaggedQueue(Queue(), Account("b"))
    assert queue.push({"payload": {}}) == "ok" and pushed == [{"payload": {"account_id": "b"}}] and queue.enabled


@pytest.mark.parametrize("row, message", [
    ({"id": "Bad Id"}, "bad account id"),
    ({"id": "a", "broker": "kraken"}, "unknown broker"),
    ({"id": "a", "broker": "paper", "lean_environment": "live-interactive"}, "does not fit"),
    ({"id": "a", "mode": "live"}, "real brokerage"),
    ({"id": "a", "mode": "turbo"}, "mode must be"),
    ({"id": "a", "capital_usd": -5}, "capital_usd"),
    ({"id": "a", "risk_overrides": {"phase1.universe": 1}}, "not an account override"),
    ({"id": "a", "risk_overrides": {"live.max_allowed_total_drawdown_pct": 0.5}}, "looser"),
    ({"id": "a", "risk_overrides": {"risk.kill_switch.min_rolling_sharpe": -1000}}, "looser"),
    ({"id": "a", "risk_overrides": {"runtime.allow_live_orders": True}}, "switched off"),
    ({"id": "a", "risk_overrides": {"dynamic_risk.max_leverage": "x"}}, "must be a number"),
])
def test_bad_rows_are_refused(row, message):
    with pytest.raises(ValueError, match=message):
        parse_accounts({"accounts": [row]}, BASE)


def test_duplicates_unknown_ids_a_loosening_mode_and_an_overridden_default_are_refused():
    with pytest.raises(ValueError, match="duplicate"):
        parse_accounts({"accounts": [{"id": "a"}, {"id": "a"}]})
    with pytest.raises(ValueError, match="unknown account"):
        resolve_account(parse_accounts({}), "typo")
    with pytest.raises(ValueError, match="looser"):
        apply_risk_overrides({"runtime": {"mode": "paper"}}, Account("x", "coinbase", "live-coinbase", "live"))
    with pytest.raises(ValueError, match="default account"):
        parse_accounts({"accounts": [{"id": "default", "risk_overrides": {"dynamic_risk.max_leverage": 0.5}}]})
    assert apply_risk_overrides({"runtime": {"mode": "backtest"}}, Account("x", mode="observation"))["runtime"]["mode"] == "backtest"


def test_overrides_are_rechecked_against_the_config_they_are_applied_to():
    account = parse_accounts({"accounts": [{"id": "a", "risk_overrides": {"dynamic_risk.max_leverage": 0.8}}]})[1]  # no base: accepted
    with pytest.raises(ValueError, match="looser"):
        apply_risk_overrides({"dynamic_risk": {"max_leverage": 0.5}}, account)


@settings(max_examples=300, deadline=None)
@given(st.sampled_from(sorted(key for key, direction in OVERRIDE_KEYS.items() if direction != "false")), st.floats(-1e6, 1e6), st.floats(-1e6, 1e6))
def test_an_applied_override_never_loosens_a_limit(key, base_value, override):
    tree: dict = {}
    node = tree
    parts = key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = base_value
    try:
        out = apply_risk_overrides(tree, Account("a", risk_overrides={key: override}))
    except ValueError:
        return
    value = out
    for part in parts:
        value = value[part]
    if OVERRIDE_KEYS[key] == "lower":
        assert value <= base_value
    else:
        assert value >= base_value


# V6.6.5 mutation check (seed 665): the boundaries the first tests left open

def _one(row, base=None):
    return parse_accounts({"accounts": [row]}, base)[1]


def test_an_override_equal_to_the_base_is_not_looser():
    lower_key = next(key for key, direction in OVERRIDE_KEYS.items() if direction == "lower")
    higher_key = next((key for key, direction in OVERRIDE_KEYS.items() if direction == "higher"), None)
    base: dict = {}

    def put(path, value):
        node = base
        *parents, leaf = path.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value

    put(lower_key, 0.15)
    rows = {lower_key: 0.15}
    if higher_key:
        put(higher_key, 2.0)
        rows[higher_key] = 2.0
    account = _one({"id": "same", "risk_overrides": rows}, base)
    assert apply_risk_overrides(base, account) == base
    with pytest.raises(ValueError):
        _one({"id": "loose", "risk_overrides": {lower_key: 0.150001}}, base)
    if higher_key:
        with pytest.raises(ValueError):
            _one({"id": "loose2", "risk_overrides": {higher_key: 1.999}}, base)


@pytest.mark.parametrize(("broker", "environment", "allowed"), [
    ("paper", "live-paper", False),
    ("coinbase", "live-paper", False),
    ("interactive_brokers", "live-paper", False),
    ("coinbase", "live-coinbase", True),
    ("interactive_brokers", "live-interactive", True),
])
def test_live_mode_needs_a_real_brokerage_and_environment(broker, environment, allowed):
    row = {"id": "acct", "broker": broker, "lean_environment": environment, "mode": "live"}
    if allowed:
        assert _one(row).mode == "live"
    else:
        with pytest.raises(ValueError, match="real brokerage"):
            _one(row)


@pytest.mark.parametrize(("capital", "ok"), [(1000, True), (0.01, True), (0, False), (-5, False), (True, False), ("100", False), (None, True)])
def test_capital_must_be_a_positive_number(capital, ok):
    row = {"id": "acct", "capital_usd": capital}
    if ok:
        assert _one(row).capital_usd == (float(capital) if capital is not None else None)
    else:
        with pytest.raises(ValueError, match="capital_usd"):
            _one(row)


def test_a_listed_default_comes_first_once_and_the_rest_keep_their_order():
    accounts = parse_accounts({"accounts": [{"id": "b"}, {"id": "default"}, {"id": "a"}]})
    assert [account.id for account in accounts] == ["default", "b", "a"]


@pytest.mark.parametrize(("base_mode", "account_mode", "expected"), [
    ("live", "live", "live"), ("live", "paper", "paper"), ("live", "observation", "observation"),
    ("paper", "paper", "paper"), ("paper", "observation", "observation"), ("paper", "live", None),
    ("observation", "observation", "observation"), ("observation", "paper", None), ("observation", "live", None),
    ("backtest", "observation", "backtest"),
])
def test_a_mode_is_only_ever_lowered(base_mode, account_mode, expected):
    broker = {"live": "coinbase"}.get(account_mode, "paper")
    environment = {"live": "live-coinbase"}.get(account_mode, "live-paper")
    account = _one({"id": "acct", "broker": broker, "lean_environment": environment, "mode": account_mode})
    base = {"runtime": {"mode": base_mode}}
    if expected is None:
        with pytest.raises(ValueError, match="looser"):
            apply_risk_overrides(base, account)
    else:
        assert apply_risk_overrides(base, account)["runtime"]["mode"] == expected


def test_an_account_cannot_be_changed_in_place():
    import dataclasses

    account = parse_accounts({"accounts": [{"id": "acct"}]})[1]
    with pytest.raises(dataclasses.FrozenInstanceError):
        account.mode = "live"  # type: ignore[misc]
