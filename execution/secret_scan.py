"""Detect secrets that must never be committed (Phase V2-22 security guard).

Backs `aq secrets-check` and the `.githooks/pre-commit` hook. Two independent
checks, both pure over their inputs so they are trivially testable:

1. `find_populated_secret_fields()` - flags any field in a parsed `lean.json`
   whose NAME looks like a credential (`*-api-key`, `*-password`, `ib-account`,
   …) and whose VALUE is non-empty. The tracked `lean.json` is meant to ship
   with every such field empty (see execution/lean_config_render.py); a
   populated one means real keys are about to be committed.
2. `is_tracked_env_secret()` - flags a `.env`-style filename that is NOT one of
   the committed `*.example` templates.

Nothing here touches disk or git - the IO/glue (reading files, asking git what
is tracked) lives in aq_cli.py so this module stays pure and unit-testable.
Only field NAMES are ever returned, never the secret values.
"""

from __future__ import annotations

# A lean.json key is treated as a secret if it ends with any of these. Covers
# the whole stock template's credential surface (api keys/secrets, passwords,
# access/refresh tokens, private keys) plus the IB identity fields, which are
# not "*-password" suffixed but still must not be published.
SECRET_FIELD_SUFFIXES: tuple[str, ...] = (
    "-api-key",
    "-api-secret",
    "-secret",
    "-password",
    "-access-token",
    "-refresh-token",
    "-auth-token",
    "-shared-key",
    "-private-key-hex",
    "-session-password",
    "-rest-app-key",
    "-rest-app-secret",
    "-app-key",
)

# Exact-match secret fields that don't follow the suffix pattern above.
SECRET_FIELD_EXACT: frozenset[str] = frozenset(
    {
        "ib-account",
        "ib-user-name",
        "ib-password",
    }
)


def is_secret_field(field: str) -> bool:
    return field in SECRET_FIELD_EXACT or field.endswith(SECRET_FIELD_SUFFIXES)


def find_populated_secret_fields(lean_config: dict) -> list[str]:
    """Return the sorted names of every secret-looking lean.json field that has
    a non-empty string value. Empty template -> empty list."""
    populated = [
        field
        for field, value in lean_config.items()
        if is_secret_field(field) and isinstance(value, str) and value.strip()
    ]
    return sorted(populated)


def is_tracked_env_secret(filename: str) -> bool:
    """True if `filename` is a real `.env` secret file (must not be committed)
    rather than one of the committed `*.example` templates. Accepts a bare
    filename or a path - only the final component matters."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if name.endswith(".example"):
        return False
    return name == ".env" or name.startswith(".env.")
