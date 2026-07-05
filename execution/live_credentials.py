"""Pure validation over loaded live-broker credentials (Phase V2-22).

No I/O here on purpose - see execution/live_credentials_io.py for how
credentials actually get loaded (from ib_config.py or AETHER_IB_* env vars).
This module only decides whether what was loaded is complete enough to
consider live_credentials_present=True for execution.paper_readiness's
evaluate_live_broker_config().
"""

from __future__ import annotations

REQUIRED_FIELDS = ("ib_account", "ib_user_name", "ib_password")


def credentials_present(credentials: dict) -> bool:
    """True only if every field in REQUIRED_FIELDS is a non-empty string."""
    return all(str(credentials.get(field, "")).strip() for field in REQUIRED_FIELDS)


def describe_missing_fields(credentials: dict) -> list[str]:
    return [field for field in REQUIRED_FIELDS if not str(credentials.get(field, "")).strip()]
