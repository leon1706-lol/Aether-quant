"""Pure validation over loaded live-broker credentials (Phase V2-22).

No I/O here on purpose - see execution/live_credentials_io.py for how
credentials actually get loaded (from ib_config.py or AETHER_IB_* env vars).
This module only decides whether what was loaded is complete enough to
consider live_credentials_present=True for execution.paper_readiness's
evaluate_live_broker_config().
"""

from __future__ import annotations

REQUIRED_FIELDS = ("ib_account", "ib_user_name", "ib_password")

# The Postgres password docker-compose.yml / the DSN defaults ship with. Safe
# for local dev but published in the public repo, so it is effectively no
# password at all - live mode must refuse to run against it. Keep in sync with
# docker-compose.yml's ${POSTGRES_PASSWORD:-aether_dev_password} default.
DEFAULT_DEV_DB_PASSWORD = "aether_dev_password"


def credentials_present(credentials: dict) -> bool:
    """True only if every field in REQUIRED_FIELDS is a non-empty string."""
    return all(str(credentials.get(field, "")).strip() for field in REQUIRED_FIELDS)


def describe_missing_fields(credentials: dict) -> list[str]:
    return [field for field in REQUIRED_FIELDS if not str(credentials.get(field, "")).strip()]


def postgres_dsn_is_live_safe(dsn: str) -> bool:
    """False if the DSN is empty or still carries the published dev-default
    password - either case is unacceptable for a live deployment. An empty DSN
    is treated as unsafe so a missing/unconfigured value fails closed. A DSN
    that simply omits a password (e.g. peer/trust auth) is considered safe -
    only the known-published default is rejected."""
    if not str(dsn).strip():
        return False
    return DEFAULT_DEV_DB_PASSWORD not in dsn
