"""Accounts (V6.6.5, #349): several broker accounts, each its own Lean deployment, without any of them loosening a limit.

One Lean process trades one brokerage account. So an account is a deployment: `AQ_ACCOUNT=<id>` (or the Lean parameter
`aq-account`) selects it, its secrets come from `AETHER_<ACCOUNT>_*` (`execution/secrets.py`), its state and manual
overrides live under `state/accounts/<id>/`, and its audit events carry its id. Its risk overrides may only *tighten* the
base config: a smaller drawdown limit, a stricter kill switch, less leverage, live orders off, a lower runtime mode. A
looser value is refused when the registry is parsed or applied, never silently used.

The default account is today's single deployment, and resolving it changes nothing: the same config dict, the same paths,
no `account_id` in the audit payloads.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "BROKER_ENVIRONMENTS", "MODE_RANK", "OVERRIDE_KEYS", "Account", "DEFAULT_ACCOUNT", "parse_accounts", "resolve_account", "apply_risk_overrides",
    "account_state_dir", "override_path", "account_output_paths", "tag_audit_event", "AccountTaggedQueue",
]

DEFAULT_ID = "default"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
BROKER_ENVIRONMENTS: dict[str, tuple[str, ...]] = {
    "paper": ("live-paper",),
    "coinbase": ("live-coinbase", "live-paper"),
    "interactive_brokers": ("live-interactive", "live-interactive-iqfeed", "live-paper"),
}
MODE_RANK = {"observation": 1, "paper": 2, "live": 3}
# phase_v2 key path -> which direction is tighter. "lower": the override must be <= the base; "higher": >= the base;
# "false": a boolean that may only be switched off.
OVERRIDE_KEYS: dict[str, str] = {
    "live.max_allowed_daily_drawdown_pct": "lower",
    "live.max_allowed_total_drawdown_pct": "lower",
    "dynamic_risk.max_leverage": "lower",
    "reconciliation.max_tolerated_drift": "lower",
    "risk.kill_switch.min_rolling_sharpe": "higher",
    "risk.kill_switch.max_drawdown_velocity_pct_per_bar": "lower",
    "risk.kill_switch.max_consecutive_losses": "lower",
    "risk.kill_switch.max_slippage_divergence_bps": "lower",
    "risk.kill_switch.max_model_age_days": "lower",
    "runtime.allow_live_orders": "false",
}


@dataclass(frozen=True)
class Account:
    """One deployment. `mode`, when set, may only lower the config's `runtime.mode` (observation < paper < live);
    `capital_usd` is the capital the account is funded with, which the readiness scorecard requires for a live account."""

    id: str
    broker: str = "paper"
    lean_environment: str = "live-paper"
    mode: str | None = None
    capital_usd: float | None = None
    risk_overrides: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""

    @property
    def is_default(self) -> bool:
        return self.id == DEFAULT_ID


DEFAULT_ACCOUNT = Account(DEFAULT_ID)


def _get(tree: Mapping[str, Any], dotted: str) -> Any:
    node: Any = tree
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _set(tree: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = tree
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _check_tighter(key: str, value: Any, base: Any) -> None:
    direction = OVERRIDE_KEYS[key]
    if direction == "false":
        if value is not False:
            raise ValueError(f"{key} may only be switched off by an account (got {value!r})")
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:  # NaN != NaN
        raise ValueError(f"{key} must be a number (got {value!r})")
    if base is None or isinstance(base, bool) or not isinstance(base, (int, float)):
        return  # no base value to loosen
    if direction == "lower" and value > base:
        raise ValueError(f"{key}: {value} is looser than the base {base}; an account may only tighten a limit")
    if direction == "higher" and value < base:
        raise ValueError(f"{key}: {value} is looser than the base {base}; an account may only tighten a limit")


def parse_accounts(doc: Mapping[str, Any], base_phase_v2: Mapping[str, Any] | None = None) -> tuple[Account, ...]:
    """`{"accounts": [{"id": ..., "broker": ..., ...}]}` to accounts, the default first. Raises ValueError on a bad or
    duplicate id, a broker/environment mismatch, `live` on the paper broker, an unknown override key or, given
    `base_phase_v2`, an override looser than the base."""
    rows = doc.get("accounts", []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, list):
        raise ValueError("accounts must be a list")
    accounts: list[Account] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(f"an account must be an object, got {row!r}")
        account_id = str(row.get("id", ""))
        if not _ID_RE.match(account_id):
            raise ValueError(f"bad account id {account_id!r}: lowercase letters, digits, - and _, at most 32")
        if account_id in seen:
            raise ValueError(f"duplicate account id {account_id!r}")
        seen.add(account_id)
        broker = str(row.get("broker", "paper"))
        if broker not in BROKER_ENVIRONMENTS:
            raise ValueError(f"{account_id}: unknown broker {broker!r} (one of {sorted(BROKER_ENVIRONMENTS)})")
        environment = str(row.get("lean_environment", BROKER_ENVIRONMENTS[broker][0]))
        if environment not in BROKER_ENVIRONMENTS[broker]:
            raise ValueError(f"{account_id}: environment {environment!r} does not fit broker {broker!r}")
        mode = row.get("mode")
        if mode is not None and mode not in MODE_RANK:
            raise ValueError(f"{account_id}: mode must be one of {sorted(MODE_RANK)}")
        if mode == "live" and (broker == "paper" or environment == "live-paper"):
            raise ValueError(f"{account_id}: live mode needs a real brokerage, not the paper one")
        capital = row.get("capital_usd")
        if capital is not None and (isinstance(capital, bool) or not isinstance(capital, (int, float)) or not capital > 0):
            raise ValueError(f"{account_id}: capital_usd must be a positive number")
        overrides = dict(row.get("risk_overrides") or {})
        for key, value in overrides.items():
            if key not in OVERRIDE_KEYS:
                raise ValueError(f"{account_id}: {key!r} is not an account override (allowed: {sorted(OVERRIDE_KEYS)})")
            _check_tighter(key, value, _get(base_phase_v2, key) if base_phase_v2 is not None else None)
        accounts.append(Account(account_id, broker, environment, mode, float(capital) if capital is not None else None, overrides, str(row.get("description", ""))))
    if DEFAULT_ID in seen:
        default = next(account for account in accounts if account.id == DEFAULT_ID)
        if default.risk_overrides or default.mode:
            raise ValueError("the default account is the base config itself: give overrides to a named account")
        return tuple([default] + [account for account in accounts if account.id != DEFAULT_ID])
    return (DEFAULT_ACCOUNT, *accounts)


def resolve_account(accounts: tuple[Account, ...], requested: str | None) -> Account:
    """The account named `requested`; the default when it is empty. An unknown id raises: a deployment must never run
    on another account's settings by a typo."""
    wanted = (requested or "").strip() or DEFAULT_ID
    for account in accounts:
        if account.id == wanted:
            return account
    if wanted == DEFAULT_ID:
        return DEFAULT_ACCOUNT
    raise ValueError(f"unknown account {wanted!r} (registry has {[account.id for account in accounts]})")


def apply_risk_overrides(phase_v2: Mapping[str, Any], account: Account) -> dict[str, Any]:
    """A deep copy of `phase_v2` with the account's overrides and mode applied; the default account returns an equal
    copy. Re-checks every override against this base, so a registry written for another config cannot loosen this one."""
    out = copy.deepcopy(dict(phase_v2))
    if account.is_default:
        return out
    for key, value in account.risk_overrides.items():
        if key not in OVERRIDE_KEYS:
            raise ValueError(f"{account.id}: {key!r} is not an account override")
        _check_tighter(key, value, _get(out, key))
        _set(out, key, value)
    if account.mode is not None:
        current = str(_get(out, "runtime.mode") or "")
        if current in MODE_RANK and MODE_RANK[account.mode] < MODE_RANK[current]:
            _set(out, "runtime.mode", account.mode)
        elif current in MODE_RANK and MODE_RANK[account.mode] > MODE_RANK[current]:
            raise ValueError(f"{account.id}: mode {account.mode!r} is looser than the config's {current!r}")
        # a backtest (or an unset mode) keeps its own mode: an account describes a deployment
    return out


def account_state_dir(root: Path, account: Account) -> Path:
    """Where an account writes its state: the repo root for the default (today's paths), else `state/accounts/<id>`."""
    return Path(root) if account.is_default else Path(root) / "state" / "accounts" / account.id


def override_path(root: Path, account: Account) -> Path:
    """The file the manual trade-lock and kill-switch overrides are read from and written to (`aq trade-lock`, the API)."""
    return Path(root) / "config.json" if account.is_default else account_state_dir(root, account) / "overrides.json"


def account_output_paths(root: Path, account: Account) -> dict[str, Path]:
    """The runtime files main.py writes, by name. The default account's are exactly today's."""
    base = account_state_dir(root, account)
    grafana = base / "visualization" / "grafana"
    return {
        "state_path": base / "visualization" / "state.json",
        "scene_path": base / "visualization" / "scene.json",
        "topology_state_path": base / "visualization" / "topology_state.json",
        "grafana_dir": grafana,
        "runtime_metrics_path": grafana / "runtime_metrics_snapshot.json",
        "runtime_asset_metrics_path": grafana / "runtime_asset_metrics.csv",
        "observation_summary_path": grafana / "observation_summary.json",
        "observation_equity_curve_path": grafana / "observation_equity_curve.csv",
    }


def tag_audit_event(event: Mapping[str, Any], account: Account) -> dict[str, Any]:
    """The event with `payload.account_id` set for a named account; the default account's events are left as they are."""
    out = dict(event)
    if not account.is_default:
        out["payload"] = {**dict(event.get("payload") or {}), "account_id": account.id}
    return out


class AccountTaggedQueue:
    """Wraps an audit queue so every event it pushes carries the account id (named accounts only)."""

    def __init__(self, queue: Any, account: Account) -> None:
        self._queue = queue
        self._account = account

    def push(self, event: Mapping[str, Any]) -> Any:
        return self._queue.push(tag_audit_event(event, self._account))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._queue, name)
