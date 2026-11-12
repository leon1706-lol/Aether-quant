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
