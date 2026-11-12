"""The field test without a broker (V6.6.5, #351): main.py in Lean's `live-paper` (PaperBrokerage, FakeDataQueue), real
Redis and Postgres, three runs, and a report with every check of `execution.field_test.judge_field_test`.

- **Run 1, the default account.** The plan's order row fills, injected drift breaches reconciliation, and an injected
  shock trips the kill switch, which flattens the book. Redis and then Postgres are stopped under the running engine.
- **Run 2, the same project.** It restarts; its first reconciliation must match.
- **Run 3, two named accounts at once** (`AQ_ACCOUNT=paper-a` and `paper-b`). Separate state directories, and the
  audit events tagged with each account's id.

Needs Docker, the `aether-quant-lean:17900` image and the compose Redis and Postgres. No QuantConnect login, no broker,
no key and no money. Configs live in a temp directory; lean.json and config.json are never touched. It proves plumbing,
never edge.

    python scripts/lean_smoke/field_test.py [--bars 22] [--minutes-per-run 45] [--out-dir ml/evaluation/field_test]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from execution.field_test import judge_field_test, parse_field_test_log  # noqa: E402

IMAGE = "aether-quant-lean:17900"
NETWORK = "aether-quant_aether-net"
REDIS_IN, POSTGRES_IN = "redis://redis:6379/0", "postgresql://aether:aether_dev_password@postgres:5432/aether_quant"
REDIS_HOST, POSTGRES_HOST = "redis://localhost:6380/0", "postgresql://aether:aether_dev_password@localhost:5433/aether_quant"
SKIP = {".git", ".av", ".venv", "node_modules", "backtests", "backtests_invalid", "data", "data_pre2013", "data_wide", "data_crypto_wide", "data_backups",
        "visualization", "state", "site", "Aether-quant-Obsidian-Vault", "__pycache__", "datasets", "versions", "cpp_inference_ext", "webui",
        ".lake", "build", ".cache", ".hypothesis", ".pytest_cache", ".ruff_cache", ".matplotlib_cache", "aether_quant.egg-info", "notebooks", "docs"}


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)


def copy_project(target: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in SKIP}
    shutil.copytree(ROOT, target, ignore=ignore)


def engine(name: str, project: Path, results: Path, launcher: Path, account: str = "") -> None:
    run(["docker", "rm", "-f", name])
    results.mkdir(parents=True, exist_ok=True)
    command = [
        "docker", "run", "-d", "--name", name, "--network", NETWORK, "--memory", "1400m",
        "-e", f"AETHER_REDIS_URL={REDIS_IN}", "-e", f"AETHER_POSTGRES_DSN={POSTGRES_IN}", "-e", "AQ_FIELD_TEST=1", "-e", f"AQ_ACCOUNT={account}",
        "-v", f"{project}:/LeanCLI", "-v", f"{ROOT / 'data'}:/Lean/Data:ro", "-v", f"{ROOT / 'data'}:/LeanCLI/data:ro", "-v", f"{results}:/Results",
        "-v", f"{launcher}:/Lean/Launcher/bin/Debug/config.json:ro", "-w", "/Lean/Launcher/bin/Debug", IMAGE,
    ]
    result = run(command)
    if result.returncode:
        raise SystemExit(f"docker run failed: {result.stderr}")


def logs(name: str) -> str:
    result = run(["docker", "logs", name])
    return (result.stdout or "") + (result.stderr or "")


def alive(name: str) -> bool:
    return run(["docker", "inspect", "-f", "{{.State.Running}}", name]).stdout.strip() == "true"


def wait_for_bar(name: str, bar: int, deadline: float) -> list[dict]:
    while time.time() < deadline:
        events = parse_field_test_log(logs(name))
        if any(int(event.get("bar", 0)) >= bar for event in events) or not alive(name):
            return events
        time.sleep(20)
    return parse_field_test_log(logs(name))


def stop(name: str, out: Path) -> str:
    text = logs(name)
    out.write_text(text, encoding="utf-8")
    run(["docker", "stop", "-t", "30", name])
    text = logs(name)
    out.write_text(text, encoding="utf-8")
    run(["docker", "rm", "-f", name])
    return text


def summarize_run(events: list[dict]) -> dict:
    by_event: dict[str, list[dict]] = {}
    for event in events:
        by_event.setdefault(event["event"], []).append(event)
    orders = [e for e in by_event.get("order_event", []) if "Submitted" in e.get("status", "")]
    fills = [e for e in by_event.get("order_event", []) if e.get("status", "").endswith("Filled") and "Partially" not in e.get("status", "")]
    trip = by_event.get("kill_switch_tripped", [{}])[0].get("bar")
    shock = by_event.get("shock", [{}])[0].get("bar")
    # the strategy's own exposure (`risk`, the T-bill sweep excluded, as the lock's liquidation does); `value` if absent
    gross_after = [float(e.get("risk", e["value"])) for e in by_event.get("gross", []) if trip is not None and int(e["bar"]) > int(trip) + 2]
    first = by_event.get("first_reconciliation", [{}])[0]
    return {
        "orders_submitted": len(orders), "orders_filled": len(fills), "shock_bar": int(shock) if shock is not None else None,
        "kill_switch_trip_bar": int(trip) if trip is not None else None, "gross_after_trip": gross_after[-1] if gross_after else None,
        "reconciliation_breach": bool(by_event.get("reconciliation_breach")), "first_reconciliation_breach": first.get("breach") == "True" if first else None,
        "bars_seen": max((int(e.get("bar", 0)) for e in events), default=0), "events": {key: len(value) for key, value in by_event.items()},
    }


def audit_facts() -> dict:
    """The audit chain on the real Postgres: verified, and which accounts and events it holds."""
    import psycopg

    from audit.hash_chain import verify_chain
    from audit.postgres_audit import fetch_all_events_ordered

    with psycopg.connect(POSTGRES_HOST) as conn:
        rows = fetch_all_events_ordered(conn)
    valid, broken = verify_chain(rows)
    payloads = [json.loads(row["payload"]) if isinstance(row.get("payload"), str) else (row.get("payload") or {}) for row in rows]
    return {
        "audit_chain_valid": bool(valid), "audit_first_broken": broken, "audit_entries": len(rows),
        "account_ids_in_audit": sorted({str(p["account_id"]) for p in payloads if isinstance(p, dict) and p.get("account_id")}),
        "reconciliation_audit_event": any(isinstance(p, dict) and p.get("event") == "reconciliation_breach" for p in payloads),
        "kill_switch_audit_event": any(isinstance(p, dict) and p.get("event") == "kill_switch_tripped" for p in payloads),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bars", type=int, default=22, help="bars run 1 waits for (the plan trips the kill switch at 14)")
    parser.add_argument("--minutes-per-run", type=float, default=45.0)
    parser.add_argument("--out-dir", default=str(ROOT / "ml" / "evaluation" / "field_test"))
    parser.add_argument("--work-dir", default=None)
    args = parser.parse_args(argv)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    out = Path(args.out_dir) / stamp
    out.mkdir(parents=True, exist_ok=True)
    work = Path(args.work_dir or tempfile.mkdtemp(prefix="aq_field_test_"))
    project = work / "project"
    if project.exists():
        shutil.rmtree(project)
    copy_project(project)
    (project / "visualization" / "grafana").mkdir(parents=True, exist_ok=True)
    (project / "data").mkdir(exist_ok=True)  # the mount point of the repo's data (read-only)
    launcher = work / "launcher.json"
    made = run([sys.executable, str(ROOT / "scripts" / "lean_smoke" / "make_field_test_config.py"), "--lean-json", str(ROOT / "lean.json"), "--out", str(launcher),
                "--project-config", str(project / "config.json")], cwd=ROOT)
    if made.returncode:
        raise SystemExit(made.stderr)
    shutil.copyfile(ROOT / "accounts.example.json", project / "accounts.json")
    print("services: docker compose up -d redis postgres", flush=True)
    run(["docker", "compose", "up", "-d", "redis", "postgres"], cwd=ROOT)
    time.sleep(10)
    worker_env = {**os.environ, "AETHER_REDIS_URL": REDIS_HOST, "AETHER_POSTGRES_DSN": POSTGRES_HOST}
    worker_log = (out / "audit_worker.log").open("w", encoding="utf-8")
    worker = subprocess.Popen([sys.executable, "-m", "audit.postgres_worker"], cwd=ROOT, env=worker_env, stdout=worker_log, stderr=subprocess.STDOUT)
    evidence: dict = {"runs": [], "outages": [], "date": stamp}
    try:
        print("run 1: default account, order, drift, shock, outages", flush=True)
        engine("aq_field_test", project, work / "results1", launcher)
        deadline = time.time() + args.minutes_per_run * 60
        wait_for_bar("aq_field_test", 10, deadline)
        for service, container in (("redis", "aether-quant-redis"), ("postgres", "aether-quant-postgres")):
            run(["docker", "stop", container])
            time.sleep(40)
            evidence["outages"].append({"service": service, "engine_alive_after": alive("aq_field_test")})
            run(["docker", "start", container])
            time.sleep(15)
        events = wait_for_bar("aq_field_test", args.bars, deadline)
        stop("aq_field_test", out / "engine1.log")
        evidence["runs"].append(summarize_run(events))

        print("run 2: restart on the same project", flush=True)
        engine("aq_field_test", project, work / "results2", launcher)
        events2 = wait_for_bar("aq_field_test", 4, time.time() + args.minutes_per_run * 60)
        stop("aq_field_test", out / "engine2.log")
        second = summarize_run(events2)
        evidence["restart"] = {"started": second["bars_seen"] >= 1, "reconciliation_breach_on_start": bool(second["first_reconciliation_breach"]), "summary": second}

        print("run 3: two accounts at once", flush=True)
        engine("aq_field_test_a", project, work / "results3a", launcher, account="paper-a")
        engine("aq_field_test_b", project, work / "results3b", launcher, account="paper-b")
        deadline3 = time.time() + args.minutes_per_run * 60
        wait_for_bar("aq_field_test_a", 4, deadline3)
        wait_for_bar("aq_field_test_b", 4, deadline3)
        stop("aq_field_test_a", out / "engine3a.log")
        stop("aq_field_test_b", out / "engine3b.log")
        dirs = [project / "state" / "accounts" / account for account in ("paper-a", "paper-b")]
        evidence["state_dirs_distinct"] = all(path.is_dir() for path in dirs)
        evidence["state_dirs"] = [str(path.relative_to(project)) for path in dirs if path.is_dir()]
    finally:
        time.sleep(10)
        worker.terminate()
        worker_log.close()
    try:
        evidence.update(audit_facts())
        if evidence["runs"]:
            evidence["runs"][0]["reconciliation_audit_event"] = evidence["reconciliation_audit_event"]
    except Exception as error:  # noqa: BLE001 - a missing service is recorded, never faked
        evidence["audit_error"] = f"{type(error).__name__}: {error}"
    judged = judge_field_test(evidence)
    report = {"date": stamp, "evidence": evidence, "judged": judged, "image": IMAGE, "work_dir": str(work)}
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({name: check["status"] for name, check in judged["checks"].items()}, indent=1))
    print(f"{judged['passed']}/{judged['total']} checks passed; report {out / 'report.json'}")
    return 0 if judged["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
