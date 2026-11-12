"""Property (V6.6.5, #348): no output of `secret_status`, `redact` or a `SecretValue`'s text forms contains a secret."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from execution.secrets import SECRET_NAMES, SecretValue, redact, resolve_secret, secret_status

SECRETS = st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=8, max_size=40)


@settings(max_examples=200, deadline=None)
@given(SECRETS, st.sampled_from(SECRET_NAMES), st.sampled_from(["env", "file"]), st.text(max_size=80))
def test_no_status_redaction_or_text_form_contains_the_value(value, name, source, prefix):
    env = {f"AETHER_{name}": value} if source == "env" else {}
    resolved = resolve_secret(name, env=env, read_file=lambda path: value if source == "file" else None)
    assert value not in repr(secret_status([resolved]))
    wrapped = SecretValue(value)
    assert value not in repr(wrapped) and value not in str(wrapped) and value not in f"{wrapped}"
    assert value not in redact(f"{prefix}{value}{prefix}{value}", [wrapped])
