"""scripts/render_lean_credentials.py: renders lean.live.json and names the filled fields, never their values (V6.6.6)."""

from __future__ import annotations

import json

from script_loader import load_script, run_script


def test_it_names_the_filled_fields_and_never_prints_a_secret(tmp_path, capsys):
    base = tmp_path / "lean.json"
    base.write_text(json.dumps({"ib-account": "", "ib-user-name": "", "ib-password": ""}), encoding="utf-8")
    env_file = tmp_path / ".env.live"
    env_file.write_text("AETHER_IB_ACCOUNT=DU123\nAETHER_IB_USER_NAME=me\nAETHER_IB_PASSWORD=hunter2\n", encoding="utf-8")
    out = tmp_path / "lean.live.json"
    module = load_script("render_lean_credentials")
    assert module.main(["--base", str(base), "--out", str(out), "--env-file", str(env_file)]) == 0
    printed = capsys.readouterr().out
    assert "field(s)" in printed and "hunter2" not in printed and json.loads(out.read_text(encoding="utf-8"))["ib-password"] == "hunter2"


def test_it_warns_when_nothing_was_filled(tmp_path, capsys, monkeypatch):
    base = tmp_path / "lean.json"
    base.write_text(json.dumps({"ib-account": ""}), encoding="utf-8")
    for name in list(__import__("os").environ):
        if name.startswith("AETHER_"):
            monkeypatch.delenv(name)
    code = run_script("render_lean_credentials", ["--base", str(base), "--out", str(tmp_path / "o.json"), "--env-file", str(tmp_path / "none")], monkeypatch)
    assert code == 0 and "NO secret fields" in capsys.readouterr().out
