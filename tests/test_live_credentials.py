from execution import (
    DEFAULT_DEV_DB_PASSWORD,
    credentials_present,
    describe_missing_fields,
    postgres_dsn_is_live_safe,
)


def _complete_credentials(**overrides) -> dict:
    credentials = {
        "ib_account": "U1234567",
        "ib_user_name": "trader",
        "ib_password": "secret",
    }
    credentials.update(overrides)
    return credentials


def test_credentials_present_true_when_all_fields_set():
    assert credentials_present(_complete_credentials()) is True


def test_credentials_present_false_when_any_field_missing():
    for field in ("ib_account", "ib_user_name", "ib_password"):
        assert credentials_present(_complete_credentials(**{field: ""})) is False


def test_credentials_present_false_on_empty_dict():
    assert credentials_present({}) is False


def test_describe_missing_fields_lists_only_missing_ones():
    credentials = _complete_credentials(ib_password="")

    assert describe_missing_fields(credentials) == ["ib_password"]


def test_describe_missing_fields_empty_when_all_present():
    assert describe_missing_fields(_complete_credentials()) == []


def test_describe_missing_fields_lists_all_on_empty_dict():
    assert describe_missing_fields({}) == ["ib_account", "ib_user_name", "ib_password"]


def test_postgres_dsn_unsafe_when_empty():
    assert postgres_dsn_is_live_safe("") is False
    assert postgres_dsn_is_live_safe("   ") is False


def test_postgres_dsn_unsafe_when_default_password_present():
    dsn = f"postgresql://aether:{DEFAULT_DEV_DB_PASSWORD}@postgres:5432/aether_quant"
    assert postgres_dsn_is_live_safe(dsn) is False


def test_postgres_dsn_safe_with_real_password():
    dsn = "postgresql://aether:a-real-strong-password@postgres:5432/aether_quant"
    assert postgres_dsn_is_live_safe(dsn) is True


def test_postgres_dsn_safe_without_password_component():
    # trust/peer auth (no password at all) is not the published default - allowed
    assert postgres_dsn_is_live_safe("postgresql://aether@postgres:5432/aether_quant") is True
