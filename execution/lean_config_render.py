"""Render a secret-bearing runtime Lean config from env vars (Phase V2-22 security).

The tracked `lean.json` is the full stock Lean template with EVERY brokerage/
API-secret field left empty (`ib-password`, `polygon-api-key`, … all `""`), so
it is safe to share - anyone who pulls the repo gets the usable config structure
but none of the keys. Lean itself does **not** expand environment variables
inside `lean.json` (verified against the Lean CLI's own
`components/config/lean_config_manager.py` - values are read literally), so
"put `${VAR}` in the field" does not work: the literal string would be sent to
the broker. Instead this module renders a gitignored `lean.live.json` that
overlays the real secret values (pulled from `.env.live` / `AETHER_*` env vars)
onto the empty template, and live/paper deployment points Lean at that rendered
file via `--lean-config`. Backtests are untouched - they use the plain, empty
`lean.json`.

Pure/IO split, matching execution/live_credentials(_io).py:
- `render_lean_config()` / `parse_env_file()` are pure (no disk, no os.environ,
  never return secret VALUES - only the field NAMES that were filled).
- `load_env_file()` / `write_rendered_config()` are the thin IO wrappers.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

# lean.json field  ->  environment variable that supplies its value.
# Deliberately a small, explicit allow-list (IB live creds + the two data-feed
# keys this project actually uses) rather than "fill anything that looks like a
# secret" - rendering only touches fields we know how to source, and leaves the
# rest of the stock template untouched. Extend here (and in .env.live.example)
# when a new provider is adopted.
SECRET_ENV_MAP: dict[str, str] = {
    "ib-account": "AETHER_IB_ACCOUNT",
    "ib-user-name": "AETHER_IB_USER_NAME",
    "ib-password": "AETHER_IB_PASSWORD",
    "ib-trading-mode": "AETHER_IB_TRADING_MODE",
    "polygon-api-key": "AETHER_POLYGON_API_KEY",
    "iex-cloud-api-key": "AETHER_IEX_CLOUD_API_KEY",
    # V6.6.5 (#348): the crypto sleeve's venue (#192). Lean's Coinbase brokerage reads these two fields.
    "coinbase-api-key": "AETHER_COINBASE_API_KEY",
    "coinbase-api-secret": "AETHER_COINBASE_API_SECRET",
}


def account_env_name(env_name: str, account_id: str | None) -> str:
    """`AETHER_IB_PASSWORD` for the default account, `AETHER_<ACCOUNT>_IB_PASSWORD` for another (V6.6.5, #349)."""
    from execution.secrets import env_prefix

    return env_prefix(account_id) + env_name[len("AETHER_"):]


def parse_env_file(text: str) -> dict[str, str]:
    """Minimal `.env` parser (no python-dotenv dependency, mirroring this
    codebase's deferred/optional-import style). Handles `KEY=VALUE`, blank
    lines, `#` comments, surrounding quotes, and a leading `export `. Later
    duplicate keys win. Never raises on a malformed line - it is skipped."""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


def render_lean_config(
    base_config: Mapping[str, object], env: Mapping[str, str], account_id: str | None = None
) -> tuple[dict, list[str]]:
    """Pure render. Returns `(rendered_config, filled_field_names)`.

    Overlays onto a copy of `base_config` every `SECRET_ENV_MAP` field whose
    env var is present and non-empty (after strip). Fields whose env var is
    unset/blank are left exactly as they were in the template. The returned
    list contains only the lean.json FIELD names that were populated - never
    the secret values - so callers can safely log/report it.
    """
    rendered = dict(base_config)
    filled: list[str] = []
    for field, env_name in SECRET_ENV_MAP.items():
        value = str(env.get(account_env_name(env_name, account_id), "")).strip()
        if value:
            rendered[field] = value
            filled.append(field)
    return rendered, filled


def load_env_file(path: str | Path) -> dict[str, str]:
    """Read a `.env`-style file into a dict. Missing file -> empty dict."""
    p = Path(path)
    if not p.exists():
        return {}
    return parse_env_file(p.read_text(encoding="utf-8"))


def build_render_environment(
    env_file: str | Path | None = None,
    os_environ: Mapping[str, str] | None = None,
    account_id: str | None = None,
    stored: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Merge a `.env.live` file (if given/exists) under the real process
    environment - process env wins, so an explicitly-exported `AETHER_*`
    overrides the file, matching docker-compose's own `.env` precedence.
    V6.6.5 (#348): a secret stored in a `*_FILE` file, a Docker secret or the keyring wins over both (`stored`, from
    `stored_secret_environment`); pass `stored={}` to skip that lookup."""
    merged: dict[str, str] = {}
    if env_file is not None:
        merged.update(load_env_file(env_file))
    merged.update(dict(os_environ if os_environ is not None else os.environ))
    merged.update(dict(stored if stored is not None else stored_secret_environment(account_id)))
    return merged


def stored_secret_environment(account_id: str | None = None) -> dict[str, str]:
    """{env var: value} for each rendered secret found in a file, a Docker secret or the keyring (not plain env)."""
    from execution.secrets_io import load_secret

    out: dict[str, str] = {}
    for env_name in SECRET_ENV_MAP.values():
        resolved = load_secret(env_name[len("AETHER_"):], account_id)
        if resolved.value is not None and resolved.source and not resolved.source.startswith("env:"):
            out[account_env_name(env_name, account_id)] = resolved.value.reveal()
    return out


def write_rendered_config(
    base_path: str | Path,
    out_path: str | Path,
    env: Mapping[str, str],
    account_id: str | None = None,
) -> list[str]:
    """Read the empty template at `base_path`, render with `env`, write the
    secret-bearing result to `out_path` (pretty JSON). Returns the list of
    filled field names (never values). Raises FileNotFoundError if the template
    is missing - never silently writes an all-empty file that would look valid.
    """
    base = Path(base_path)
    if not base.exists():
        raise FileNotFoundError(f"Lean config template not found: {base}")
    base_config = json.loads(base.read_text(encoding="utf-8"))
    rendered, filled = render_lean_config(base_config, env, account_id)
    Path(out_path).write_text(
        json.dumps(rendered, indent=4) + "\n", encoding="utf-8"
    )
    return filled


def validate_live_crypto_route(config: Mapping[str, object], filled_fields: list[str] | tuple[str, ...]) -> list[str]:
    """Advisory warnings about trading crypto through the configured live brokerage (V6.1.0, Problems.md #192).

    The rendered live config fills Interactive Brokers credentials (`ib-*`). QuantConnect's Interactive Brokers
    brokerage does not support crypto (QuantConnect forum, "when will the interactivebrokersbrokeragemodel support
    crypto", staff answer "Interactive Brokers does not support crypto"; LEAN PR #8446 still open), while the book prices
    Coinbase fees (`CoinbaseFeeModel`, cash account) and the backtest fills on Lean's Coinbase market. So when crypto
    trading is enabled and the live credentials are IB's, a live or paper deploy would route crypto orders to a venue that
    cannot fill them. Pure and advisory: it never changes trading. Returns [] when there is nothing to flag."""
    phase_v2 = dict(config.get("phase_v2", {}) or {})
    assets = (config.get("phase1", {}) or {}).get("universe", {}).get("assets", []) or []
    crypto_in_universe = any(str(a.get("asset_class") or a.get("security_type")) == "crypto" for a in assets)
    crypto_trades = crypto_in_universe and bool(phase_v2.get("crypto_risk", {}).get("enabled", True))
    if not crypto_trades:
        return []
    uses_ib = any(str(field).startswith("ib-") for field in filled_fields)
    if not uses_ib:
        return []
    return [
        "crypto is in the trading universe but the live credentials are Interactive Brokers': QuantConnect's IB brokerage "
        "does not support crypto, so crypto orders would not fill there. Trade crypto through a crypto brokerage "
        "(Coinbase, cash account, the venue the fee model prices) or switch the crypto classes off before a live deploy."
    ]
