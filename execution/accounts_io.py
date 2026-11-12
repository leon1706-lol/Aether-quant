"""Reading the account registry (V6.6.5, #349): `$AQ_ACCOUNTS_FILE`, else `accounts.json` at the repo root (gitignored;
`accounts.example.json` is the tracked template). No file means the default account only, today's single deployment."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from execution.accounts import Account, account_output_paths, apply_risk_overrides, parse_accounts, resolve_account

__all__ = ["ACCOUNT_SECRETS", "accounts_file", "account_status_rows", "load_accounts", "load_account_config", "requested_account_id"]


def accounts_file(root: Path) -> Path:
    return Path(os.environ.get("AQ_ACCOUNTS_FILE") or (Path(root) / "accounts.json"))


def load_accounts(root: Path, base_phase_v2: Mapping[str, Any] | None = None) -> tuple[Account, ...]:
    """The registry's accounts, the default first. A missing file is the default alone; an unreadable or invalid one
    raises, because a deployment that asked for an account must not quietly run as another."""
    path = accounts_file(root)
    if not path.exists():
        return parse_accounts({}, base_phase_v2)
    return parse_accounts(json.loads(path.read_text(encoding="utf-8")), base_phase_v2)


def requested_account_id(parameter: str | None = None) -> str:
    """`AQ_ACCOUNT`, else the Lean parameter `aq-account`, else "" (the default account)."""
    return (os.environ.get("AQ_ACCOUNT") or parameter or "").strip()


def load_account_config(config: Mapping[str, Any], account_id: str | None, root: Path) -> dict[str, Any]:
    """The config one account runs on: a copy with its `phase_v2` through `apply_risk_overrides`, the function main.py
    applies at startup, so an offline evaluation (`aq evaluate --account`) judges the limits the deployment trades with."""
    out = dict(config)
    account = resolve_account(load_accounts(root, config.get("phase_v2", {})), account_id)
    out["phase_v2"] = apply_risk_overrides(config.get("phase_v2", {}), account)
    return out


ACCOUNT_SECRETS: dict[str, tuple[str, ...]] = {
    "paper": (),
    "coinbase": ("COINBASE_API_KEY", "COINBASE_API_SECRET"),
    "interactive_brokers": ("IB_ACCOUNT", "IB_USER_NAME", "IB_PASSWORD"),
}


def account_status_rows(root: Path, accounts: tuple[Account, ...]) -> list[dict[str, Any]]:
    """One row per account: broker, environment, mode, capital, its secrets (names and whether they resolve, never values),
    and its last state file's reconciliation (`aq accounts status`, `GET /api/accounts`)."""
    from execution.secrets_io import all_secret_status

    rows: list[dict[str, Any]] = []
    for account in accounts:
        needed = ACCOUNT_SECRETS.get(account.broker, ())
        secrets = all_secret_status(account.id, needed) if needed else []
        state = account_output_paths(Path(root), account)["state_path"]
        reconciliation = None
        if state.exists():
            try:
                reconciliation = (json.loads(state.read_text(encoding="utf-8")).get("reconciliation") or {}).get("breach")
            except (OSError, ValueError, AttributeError):
                reconciliation = None
        rows.append({
            "id": account.id, "broker": account.broker, "environment": account.lean_environment, "mode": account.mode or "(config)",
            "capital_usd": account.capital_usd, "overrides": len(account.risk_overrides), "description": account.description,
            "secrets": f"{sum(1 for row in secrets if row['resolved'])}/{len(needed)}", "secrets_missing": [row["name"] for row in secrets if not row["resolved"]],
            "state": state.relative_to(Path(root)).as_posix() if state.exists() else "-", "reconciliation_breach": reconciliation,
        })
    return rows
