"""scripts/backup_postgres.py (V6.6.5, #352)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backup_postgres.py"


def _module():
    spec = importlib.util.spec_from_file_location("backup_postgres", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_help_and_dry_run():
    assert subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60).returncode == 0
    result = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", "--docker"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and "pg_dump --format=custom" in result.stdout


def test_the_dsn_never_reaches_argv(tmp_path):
    module = _module()
    assert "postgresql" not in " ".join(module.dump_command(docker=False, target=tmp_path / "x.dump"))
    assert module.dump_command(docker=True, target=tmp_path / "x.dump")[:5] == ["docker", "compose", "exec", "-T", "postgres"]


def test_prune_keeps_the_newest(tmp_path):
    module = _module()
    for stamp in ("20261101", "20261102", "20261103"):
        (tmp_path / f"aether_quant_{stamp}T000000Z.dump").write_bytes(b"x")
    removed = module.prune(tmp_path, 2)
    assert [path.name for path in removed] == ["aether_quant_20261101T000000Z.dump"] and len(list(tmp_path.glob("*.dump"))) == 2


def test_without_a_dsn_it_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("AETHER_POSTGRES_DSN", raising=False)
    monkeypatch.setattr("execution.secrets_io.keyring_get", lambda service, user: None)
    module = _module()
    assert module.main(["--out-dir", str(tmp_path)]) == 1


def _dump(module, monkeypatch, *, returncode=0, writes=b"PGDMP", which="/usr/bin/pg_dump", dsn="postgresql://u@h/db"):
    from types import SimpleNamespace

    seen = {}
    monkeypatch.setattr(module, "secret_env", lambda name, default: dsn)
    monkeypatch.setattr(module.shutil, "which", lambda name: which)

    def run(command, cwd, env, check, stdout=None):
        seen.update(command=command, env=env)
        target = stdout if stdout is not None else None
        if target is not None:
            target.write(writes)
        else:
            Path(command[command.index("--file") + 1] if "--file" in command else command[-1]).write_bytes(writes)
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(module.subprocess, "run", run)
    return seen


def test_a_local_dump_is_kept_marked_and_pruned(tmp_path, monkeypatch, capsys):
    import json

    module = _module()
    for stamp in ("20200101T000000Z", "20200102T000000Z"):
        (tmp_path / f"aether_quant_{stamp}.dump").write_bytes(b"old")
    seen = _dump(module, monkeypatch)
    assert module.main(["--out-dir", str(tmp_path), "--keep", "2"]) == 0
    marker = json.loads((tmp_path / "last_backup.json").read_text(encoding="utf-8"))
    assert marker["pruned"] == ["aether_quant_20200101T000000Z.dump"] and seen["env"]["PGDATABASE"] == "postgresql://u@h/db"
    assert "postgresql" not in " ".join(seen["command"]) and "backed up to" in capsys.readouterr().out


def test_a_docker_dump_streams_to_the_file(tmp_path, monkeypatch):
    module = _module()
    seen = _dump(module, monkeypatch, which=None, dsn="")
    assert module.main(["--docker", "--out-dir", str(tmp_path)]) == 0
    assert seen["command"][:3] == ["docker", "compose", "exec"] and len(list(tmp_path.glob("aether_quant_*.dump"))) == 1


def test_a_failed_or_empty_dump_leaves_nothing_behind(tmp_path, monkeypatch, capsys):
    module = _module()
    _dump(module, monkeypatch, returncode=1)
    assert module.main(["--out-dir", str(tmp_path)]) == 1
    _dump(module, monkeypatch, writes=b"")
    assert module.main(["--out-dir", str(tmp_path)]) == 1
    assert not list(tmp_path.glob("aether_quant_*.dump")) and "pg_dump failed" in capsys.readouterr().err


def test_no_dsn_or_no_pg_dump_is_refused(tmp_path, monkeypatch, capsys):
    module = _module()
    _dump(module, monkeypatch, dsn="")
    assert module.main(["--out-dir", str(tmp_path)]) == 1 and "no Postgres DSN" in capsys.readouterr().err
    _dump(module, monkeypatch, which=None)
    assert module.main(["--out-dir", str(tmp_path)]) == 1 and "pg_dump is not installed" in capsys.readouterr().err
