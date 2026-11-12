"""Secret resolution (V6.6.5, #348): where a credential comes from, without ever printing it.

A secret has a NAME (`IB_PASSWORD`, `COINBASE_API_SECRET`, `POSTGRES_DSN`, ...) and is looked up, first match wins, in:

1. a file named by `AETHER_<NAME>_FILE` (the Docker and Kubernetes convention),
2. the Docker secret `/run/secrets/aether_<name>`,
3. the environment variable `AETHER_<NAME>` (what every service read before; with only that set, nothing changes),
4. the OS keyring, service `aether-quant`, user `<NAME>` (`aq secrets set NAME`; only when the `keyring` package is installed).

An account other than `default` reads `AETHER_<ACCOUNT>_<NAME>` (and the matching file, Docker secret and keyring entry), so
two accounts never share a credential by accident. Values travel as `SecretValue`, whose repr and str are `***`; only
`reveal()` returns the text. This module is pure: the environment, the file reader and the keyring come in as arguments
(`execution/secrets_io.py` passes the real ones).
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "SECRET_NAMES", "KEYRING_SERVICE", "SecretValue", "SecretRef", "ResolvedSecret", "parse_ref", "env_prefix", "default_refs", "resolve_secret", "redact",
    "secret_status",
]

SECRET_NAMES: tuple[str, ...] = (
    "IB_ACCOUNT", "IB_USER_NAME", "IB_PASSWORD", "IB_TRADING_MODE", "COINBASE_API_KEY", "COINBASE_API_SECRET", "POSTGRES_DSN", "REDIS_URL",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "POLYGON_API_KEY", "IEX_CLOUD_API_KEY",
)
KEYRING_SERVICE = "aether-quant"
DOCKER_SECRETS_DIR = "/run/secrets"
_ACCOUNT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class SecretValue:
    """A credential that never shows itself: `repr`, `str` and f-strings give `***`. `reveal()` returns the text."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = str(value)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretValue('***')"

    def __str__(self) -> str:
        return "***"

    def __format__(self, spec: str) -> str:
        return "***"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretValue):
            return NotImplemented
        return hmac.compare_digest(self._value.encode("utf-8"), other._value.encode("utf-8"))

    def __hash__(self) -> int:
        return hash(("SecretValue", len(self._value)))

    def __reduce__(self):
        raise TypeError("a SecretValue is not pickled or copied out of the process")


@dataclass(frozen=True)
class SecretRef:
    """Where to look: `env:AETHER_IB_PASSWORD`, `file:/run/secrets/aether_ib_password` or `keyring:aether-quant/IB_PASSWORD`."""

    scheme: Literal["env", "file", "keyring"]
    target: str

    def __str__(self) -> str:
        return f"{self.scheme}:{self.target}"


@dataclass(frozen=True)
class ResolvedSecret:
    """The outcome of one lookup. `value` is None when nothing matched; `source` names the ref that did."""

    name: str
    value: SecretValue | None
    source: str | None


def parse_ref(text: str) -> SecretRef:
    """`scheme:target` to a `SecretRef`. A literal value is refused: secrets are never written into config."""
    scheme, sep, target = str(text).partition(":")
    if not sep or not target or scheme not in ("env", "file", "keyring"):
        raise ValueError(f"not a secret reference (env:, file: or keyring:): {text!r}")
    return SecretRef(scheme, target)  # type: ignore[arg-type]


def env_prefix(account_id: str | None) -> str:
    """`AETHER_` for the default account, `AETHER_<ACCOUNT>_` for any other (dashes become underscores)."""
    if not account_id or account_id == "default":
        return "AETHER_"
    if not _ACCOUNT_RE.match(account_id):
        raise ValueError(f"bad account id {account_id!r}")
    return f"AETHER_{account_id.upper().replace('-', '_')}_"


def default_refs(name: str, account_id: str | None = None, env: Mapping[str, str] | None = None) -> tuple[SecretRef, ...]:
    """The lookup order for one secret (see the module docstring)."""
    if not re.match(r"^[A-Z][A-Z0-9_]*$", str(name)):
        raise ValueError(f"bad secret name {name!r}")
    variable = f"{env_prefix(account_id)}{name}"
    refs: list[SecretRef] = []
    file_variable = f"{variable}_FILE"
    if env is not None and env.get(file_variable):
        refs.append(SecretRef("file", env[file_variable]))
    refs.append(SecretRef("file", f"{DOCKER_SECRETS_DIR}/{variable.lower()}"))
    refs.append(SecretRef("env", variable))
    keyring_user = name if not account_id or account_id == "default" else f"{account_id}/{name}"
    refs.append(SecretRef("keyring", f"{KEYRING_SERVICE}/{keyring_user}"))
    return tuple(refs)


def resolve_secret(
    name: str,
    *,
    account_id: str | None = None,
    env: Mapping[str, str],
    read_file: Callable[[str], str | None],
    keyring_get: Callable[[str, str], str | None] | None = None,
) -> ResolvedSecret:
    """The first non-empty value along `default_refs`. A file's trailing newline is dropped; a reader that raises counts as
    "not there", never as a crash."""
    for ref in default_refs(name, account_id, env):
        value: str | None = None
        try:
            if ref.scheme == "env":
                value = env.get(ref.target)
            elif ref.scheme == "file":
                value = read_file(ref.target)
                value = value.rstrip("\r\n") if value is not None else None
            elif keyring_get is not None:
                service, _, user = ref.target.partition("/")
                value = keyring_get(service, user)
        except Exception:  # noqa: BLE001 - an unreadable source is a missing source
            value = None
        if value:
            return ResolvedSecret(name, SecretValue(value), str(ref))
    return ResolvedSecret(name, None, None)


def redact(text: str, values: Iterable[SecretValue | str | None]) -> str:
    """`text` with every occurrence of every secret value replaced by `***`, longest first (so a value that contains another
    is hidden whole). Values shorter than 4 characters are left alone: masking `1` would mangle every number."""
    secrets = sorted({(value.reveal() if isinstance(value, SecretValue) else str(value)) for value in values if value}, key=len, reverse=True)
    out = str(text)
    for secret in secrets:
        if len(secret) >= 4:
            out = out.replace(secret, "***")
    return out


def secret_status(resolved: Iterable[ResolvedSecret]) -> list[dict[str, str | bool]]:
    """Names and sources only, never values: what `aq secrets status` prints and the readiness scorecard reads. A secret
    from a file or the keyring counts as `stored_safely`; one from a plain environment variable does not."""
    rows: list[dict[str, str | bool]] = []
    for item in resolved:
        source = item.source or ""
        rows.append({
            "name": item.name, "resolved": item.value is not None, "source": source.split(":", 1)[0] if source else "",
            "where": source, "stored_safely": source.startswith(("file:", "keyring:")),
        })
    return rows
