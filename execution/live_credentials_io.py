"""IO layer for loading live-broker credentials (Phase V2-22).

Two equally-supported patterns, tried in order:
1. `ib_config.py` (repo-root, gitignored, planned-but-absent per
   .gitignore - a human creates it locally, never committed).
2. AETHER_IB_ACCOUNT / AETHER_IB_USER_NAME / AETHER_IB_PASSWORD /
   AETHER_IB_TRADING_MODE environment variables (populated from `.env.live`,
   see .env.live.example).

This is pre-flight validation only, feeding execution.live_credentials's
credentials_present() - it does not wire Lean itself. The tracked `lean.json`
ships with ib-account/ib-user-name/ib-password/ib-trading-mode as empty
placeholders; real values are rendered into a gitignored `lean.live.json` by
scripts/render_lean_credentials.py (`aq render-lean-config`) from these same
AETHER_* vars, and Lean is pointed at that file via `--lean-config` (see
execution/lean_config_render.py and development/infrastructure.md's "Live"
runbook). Never raises - missing everything just yields all-empty-string values.
"""

from __future__ import annotations

from execution.secrets_io import secret_env


def load_live_credentials(account_id: str | None = None) -> dict:
    """The IB credential fields for one account (`None` or "default" is today's single account). The default account still
    tries a gitignored `ib_config.py` first; every value then comes through `execution.secrets_io.secret_env` (a `*_FILE`
    file, a Docker secret, `AETHER_[<ACCOUNT>_]IB_*`, or the keyring), V6.6.5 #348/#349."""
    default = not account_id or account_id == "default"
    if default:
        try:
            import ib_config  # type: ignore[import-not-found]

            return {
                "ib_account": str(getattr(ib_config, "IB_ACCOUNT", "")),
                "ib_user_name": str(getattr(ib_config, "IB_USER_NAME", "")),
                "ib_password": str(getattr(ib_config, "IB_PASSWORD", "")),
                "ib_trading_mode": str(getattr(ib_config, "IB_TRADING_MODE", "paper")),
            }
        except ImportError:
            pass

    return {
        "ib_account": secret_env("IB_ACCOUNT", "", account_id),
        "ib_user_name": secret_env("IB_USER_NAME", "", account_id),
        "ib_password": secret_env("IB_PASSWORD", "", account_id),
        "ib_trading_mode": secret_env("IB_TRADING_MODE", "paper", account_id),
    }


def load_coinbase_credentials(account_id: str | None = None) -> dict:
    """The Coinbase Advanced Trade key pair for one account, resolved like the IB fields. Empty strings when absent."""
    return {
        "coinbase_api_key": secret_env("COINBASE_API_KEY", "", account_id),
        "coinbase_api_secret": secret_env("COINBASE_API_SECRET", "", account_id),
    }


def load_postgres_dsn() -> str:
    """The runtime Postgres DSN, read from AETHER_POSTGRES_DSN (the same var
    docker-compose.yml injects; or its `*_FILE`, Docker secret or keyring entry). Empty string if unset. Fed to
    execution.paper_readiness's live gate so a live run against the published
    dev-default password fails closed - see
    execution.live_credentials.postgres_dsn_is_live_safe()."""
    return secret_env("POSTGRES_DSN", "")
