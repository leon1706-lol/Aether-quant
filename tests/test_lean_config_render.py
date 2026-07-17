"""Tests for execution/lean_config_render.py — the lean.live.json render step.

The render step exists because Lean does NOT expand env vars inside lean.json;
the tracked lean.json stays all-empty and a gitignored lean.live.json is
rendered from AETHER_* env vars. These tests pin: (1) only mapped fields with a
non-empty env var get filled, (2) the returned list is field NAMES not values,
(3) an all-empty env leaves the template untouched, (4) the .env parser handles
quotes/comments/export, (5) write refuses a missing template.
"""

import json

import pytest

from execution.lean_config_render import (
    SECRET_ENV_MAP,
    build_render_environment,
    parse_env_file,
    render_lean_config,
    write_rendered_config,
)


def _empty_template() -> dict:
    return {field: "" for field in SECRET_ENV_MAP} | {"ib-trading-mode": "paper", "data-folder": "data"}


def test_render_fills_only_fields_with_nonempty_env():
    env = {"AETHER_IB_ACCOUNT": "U123", "AETHER_POLYGON_API_KEY": "pk_live_abc"}
    rendered, filled = render_lean_config(_empty_template(), env)

    assert rendered["ib-account"] == "U123"
    assert rendered["polygon-api-key"] == "pk_live_abc"
    # untouched fields keep the template value
    assert rendered["iex-cloud-api-key"] == ""
    assert rendered["data-folder"] == "data"
    assert set(filled) == {"ib-account", "polygon-api-key"}


def test_render_returns_field_names_not_secret_values():
    env = {"AETHER_IB_PASSWORD": "super-secret-value"}
    _, filled = render_lean_config(_empty_template(), env)

    assert filled == ["ib-password"]
    assert "super-secret-value" not in filled


def test_render_ignores_blank_and_whitespace_env_values():
    env = {"AETHER_IB_ACCOUNT": "", "AETHER_IB_PASSWORD": "   "}
    rendered, filled = render_lean_config(_empty_template(), env)

    assert filled == []
    assert rendered["ib-account"] == ""
    assert rendered["ib-password"] == ""


def test_render_does_not_mutate_input_template():
    template = _empty_template()
    render_lean_config(template, {"AETHER_IB_ACCOUNT": "U999"})

    assert template["ib-account"] == ""


def test_parse_env_file_handles_comments_quotes_export_and_blanks():
    text = "\n".join(
        [
            "# a comment",
            "",
            "AETHER_IB_ACCOUNT=U123",
            'AETHER_IB_PASSWORD="quoted secret"',
            "export AETHER_POLYGON_API_KEY='pk_abc'",
            "MALFORMED_NO_EQUALS",
            "AETHER_IB_ACCOUNT=U456",
        ]
    )
    parsed = parse_env_file(text)

    assert parsed["AETHER_IB_PASSWORD"] == "quoted secret"
    assert parsed["AETHER_POLYGON_API_KEY"] == "pk_abc"
    assert "MALFORMED_NO_EQUALS" not in parsed
    assert parsed["AETHER_IB_ACCOUNT"] == "U456"  # later duplicate wins


def test_build_render_environment_process_env_overrides_file(tmp_path):
    env_file = tmp_path / ".env.live"
    env_file.write_text("AETHER_IB_ACCOUNT=from_file\n", encoding="utf-8")

    merged = build_render_environment(env_file=env_file, os_environ={"AETHER_IB_ACCOUNT": "from_process"})

    assert merged["AETHER_IB_ACCOUNT"] == "from_process"


def test_write_rendered_config_writes_secrets_and_keeps_template_empty(tmp_path):
    base = tmp_path / "lean.json"
    base.write_text(json.dumps(_empty_template()), encoding="utf-8")
    out = tmp_path / "lean.live.json"

    filled = write_rendered_config(base, out, {"AETHER_IB_PASSWORD": "pw", "AETHER_IB_ACCOUNT": "U1"})

    assert set(filled) == {"ib-password", "ib-account"}
    rendered = json.loads(out.read_text(encoding="utf-8"))
    assert rendered["ib-password"] == "pw"
    # the tracked template on disk is untouched (still empty)
    assert json.loads(base.read_text(encoding="utf-8"))["ib-password"] == ""


def test_write_rendered_config_raises_on_missing_template(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_rendered_config(tmp_path / "nope.json", tmp_path / "out.json", {})
