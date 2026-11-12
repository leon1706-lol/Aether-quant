"""Back up the Postgres database (V6.6.5, #352): `pg_dump --format=custom` into `state/backups/`, keeping the newest N,
and a `last_backup.json` marker the paper-to-live scorecard reads (a backup older than 7 days fails it).

The DSN is the runtime one (`AETHER_POSTGRES_DSN`, its `_FILE`, a Docker secret or the keyring); it is passed to pg_dump
through the environment, never on the command line. With `--docker` the dump runs inside the compose `postgres` container,
for a host without the client tools. Restore: `pg_restore --clean --if-exists -d <dsn> state/backups/<file>.dump`
(RUNBOOK "Backups").

    python scripts/backup_postgres.py                 # local pg_dump
    python scripts/backup_postgres.py --docker        # docker compose exec postgres pg_dump
    python scripts/backup_postgres.py --dry-run       # print what would run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from execution.secrets_io import secret_env  # noqa: E402

BACKUP_DIR = ROOT / "state" / "backups"


def dump_command(*, docker: bool, target: Path) -> list[str]:
    """The pg_dump invocation; the DSN arrives through PG* environment variables (never argv)."""
    if docker:
        user = os.environ.get("POSTGRES_USER", "aether")
        database = os.environ.get("POSTGRES_DB", "aether_quant")
        return ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "--format=custom", "-U", user, "-d", database]
    return ["pg_dump", "--format=custom", "--file", str(target)]


def prune(directory: Path, keep: int) -> list[Path]:
    dumps = sorted(directory.glob("aether_quant_*.dump"))
    removed = dumps[:-keep] if keep > 0 and len(dumps) > keep else []
    for path in removed:
        path.unlink()
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--docker", action="store_true", help="Run pg_dump inside the compose postgres container")
    parser.add_argument("--keep", type=int, default=14, help="Dumps to keep (default 14)")
    parser.add_argument("--out-dir", default=str(BACKUP_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"aether_quant_{stamp}.dump"
    command = dump_command(docker=args.docker, target=target)
    if args.dry_run:
        print(" ".join(command), f"> {target}" if args.docker else "")
        return 0
    dsn = secret_env("POSTGRES_DSN", "")
    if not args.docker and not dsn:
        print("error: no Postgres DSN (AETHER_POSTGRES_DSN, its _FILE, a Docker secret or the keyring)", file=sys.stderr)
        return 1
    if not args.docker and shutil.which("pg_dump") is None:
        print("error: pg_dump is not installed; use --docker", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ}
    if dsn and not args.docker:
        env["PGDATABASE"] = dsn  # libpq accepts a connection URI as the database name
    if args.docker:
        with target.open("wb") as handle:
            result = subprocess.run(command, cwd=ROOT, stdout=handle, env=env, check=False)
    else:
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        print(f"error: pg_dump failed ({result.returncode})", file=sys.stderr)
        return 1
    removed = prune(out_dir, args.keep)
    marker = {"date": datetime.now(timezone.utc).date().isoformat(), "file": target.name, "bytes": target.stat().st_size, "pruned": [path.name for path in removed]}
    (out_dir / "last_backup.json").write_text(json.dumps(marker, indent=1) + "\n", encoding="utf-8")
    print(f"backed up to {target} ({marker['bytes']} bytes); kept the newest {args.keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
