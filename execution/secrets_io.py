"""The real environment, files and OS keyring behind `execution/secrets.py` (V6.6.5, #348).

`secret_env("POSTGRES_DSN", default)` is the drop-in for `os.environ.get("AETHER_POSTGRES_DSN", default)`: with only the
environment variable set it returns the same string, and it also finds the value in a `*_FILE` file, a Docker secret or
the keyring. Imports nothing heavy; `keyring` loads only when it is installed and a lookup gets that far.
"""

from __future__ import annotations

import os
from pathlib import Path

from execution.secrets import KEYRING_SERVICE, SECRET_NAMES, ResolvedSecret, SecretValue, env_prefix, resolve_secret, secret_status

__all__ = ["read_secret_file", "keyring_get", "keyring_set", "keyring_delete", "load_secret", "secret_env", "all_secret_status"]


def read_secret_file(path: str) -> str | None:
    """A file's text, or None when it is missing or unreadable."""
    try:
        target = Path(path)
        return target.read_text(encoding="utf-8") if target.is_file() else None
    except OSError:
        return None


def _keyring():
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - absent, or a broken backend: no keyring
        return None
    return keyring


def keyring_get(service: str, user: str) -> str | None:
    module = _keyring()
    if module is None:
        return None
    try:
        return module.get_password(service, user)
    except Exception:  # noqa: BLE001 - a locked or missing backend is "not stored"
        return None


def keyring_set(name: str, value: str, account_id: str | None = None) -> None:
    """Store a secret in the OS keyring (`aq secrets set`). Raises RuntimeError without the `keyring` package."""
    module = _keyring()
    if module is None:
        raise RuntimeError("the keyring package is not installed: pip install keyring (or aether-quant[live])")
    env_prefix(account_id)  # validates the account id
    user = name if not account_id or account_id == "default" else f"{account_id}/{name}"
    module.set_password(KEYRING_SERVICE, user, value)


def keyring_delete(name: str, account_id: str | None = None) -> bool:
    module = _keyring()
    if module is None:
        return False
    user = name if not account_id or account_id == "default" else f"{account_id}/{name}"
    try:
        module.delete_password(KEYRING_SERVICE, user)
        return True
    except Exception:  # noqa: BLE001 - nothing stored
        return False


def load_secret(name: str, account_id: str | None = None) -> ResolvedSecret:
    """Resolve one secret from the real sources."""
    return resolve_secret(name, account_id=account_id, env=os.environ, read_file=read_secret_file, keyring_get=keyring_get)


def secret_env(name: str, default: str = "", account_id: str | None = None) -> str:
    """The secret's text, or `default`: the replacement for `os.environ.get("AETHER_<NAME>", default)`."""
    resolved = load_secret(name, account_id)
    if isinstance(resolved.value, SecretValue):
        return resolved.value.reveal()
    # a variable set to "" reads as "" (not the default), exactly as os.environ.get did
    return os.environ.get(f"{env_prefix(account_id)}{name}", default)


def all_secret_status(account_id: str | None = None, names: tuple[str, ...] = SECRET_NAMES) -> list[dict[str, str | bool]]:
    """`secret_status` of every known secret for one account."""
    return secret_status(load_secret(name, account_id) for name in names)
