"""Record a phase gate in the local Aether-Vault repository: its rules, ledger, frozen configs and weight files, with
metrics, in one tagged commit. Nothing is pushed. The commit's timestamp is what shows a rule existed before the
scores it judged.

  python scripts/vault_record.py --label rules --metric trials=0 ml/evaluation/v650/rules.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retraining.vault_client import parse_av_envelope, run_av_command, vault_preflight  # noqa: E402
from retraining.vault_commands import build_av_add_command, build_av_commit_command  # noqa: E402


def find_av_binary() -> str:
    """`AQ_AV_BINARY`, then PATH, then the per-user scripts folder pip installs to on Windows."""
    configured = os.environ.get("AQ_AV_BINARY")
    if configured:
        return configured
    found = shutil.which("av")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        for candidate in sorted(Path(appdata).glob("Python/Python*/Scripts/av.exe")):
            return str(candidate)
    return "av"


def parse_metrics(raw: list[str]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for item in raw:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise ValueError(f"metric must be key=value: {item!r}")
        metrics[key] = float(value)
    return metrics


def record(label: str, paths: list[str], metrics: dict[str, float], *, cwd: Path = ROOT, av_binary: str | None = None) -> dict:
    """Returns {"ok": bool, "stage": str, "commit": str | None, "detail": str | None}. Never raises on an `av` failure."""
    binary = av_binary or find_av_binary()
    config = {"av_binary": binary, "timeout_seconds": 600}
    preflight = vault_preflight(config, cwd=cwd)
    if not preflight["ok"]:
        return {"ok": False, "stage": "preflight", "commit": None, "detail": preflight["reason"]}
    added = run_av_command(build_av_add_command(paths, av_binary=binary), cwd=cwd, timeout=600)
    if not added["ok"]:
        return {"ok": False, "stage": "add", "commit": None, "detail": added["error"]}
    committed = run_av_command(
        build_av_commit_command(f"gate {label}", f"gate:{label}", metrics, av_binary=binary, no_upload=True), cwd=cwd, timeout=600
    )
    envelope = parse_av_envelope(committed["stdout"])
    if not committed["ok"]:
        error = (envelope or {}).get("error") or {}
        # The same files recorded at an earlier gate are not a failure: that commit already holds them.
        if error.get("code") == "nothing_to_commit":
            return {"ok": True, "stage": "unchanged", "commit": None, "detail": "nothing_to_commit"}
        return {"ok": False, "stage": "commit", "commit": None, "detail": committed["error"]}
    data = (envelope or {}).get("data") or {}
    return {"ok": True, "stage": "done", "commit": data.get("hash"), "detail": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--metric", action="append", default=[], help="key=value, repeatable")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    result = record(args.label, args.paths, parse_metrics(args.metric))
    print(json.dumps(result, indent=1))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
