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
execution/lean_config_render.py and development/infrastructure.md's V2-22
runbook). Never raises - missing everything just yields all-empty-string values.
"""

from __future__ import annotations

import os


def load_live_credentials() -> dict:
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
        "ib_account": os.environ.get("AETHER_IB_ACCOUNT", ""),
        "ib_user_name": os.environ.get("AETHER_IB_USER_NAME", ""),
        "ib_password": os.environ.get("AETHER_IB_PASSWORD", ""),
        "ib_trading_mode": os.environ.get("AETHER_IB_TRADING_MODE", "paper"),
    }


def load_postgres_dsn() -> str:
    """The runtime Postgres DSN, read from AETHER_POSTGRES_DSN (the same var
    docker-compose.yml injects). Empty string if unset. Fed to
    execution.paper_readiness's live gate so a live run against the published
    dev-default password fails closed - see
    execution.live_credentials.postgres_dsn_is_live_safe()."""
    return os.environ.get("AETHER_POSTGRES_DSN", "")
