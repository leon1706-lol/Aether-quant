"""Real Redis and Postgres, no broker: what "safety is not field-tested" can honestly be narrowed by (V6.6.4, README Known Limitations, #228).

The audit trail is the one safety component that needs both services and nothing else. This drives the project's own `AuditQueue` and `PostgresWorker` against real servers: events flow
Redis -> Postgres with a hash chain, a tampered row is found, and each service is stopped and restarted underneath a running pipeline. It proves the plumbing under real outages. It is not a
paper period, a broker fill or a Lean live run, and the report says so.

    docker compose up -d redis postgres           # or any Redis and Postgres you point the two variables at
    AETHER_REDIS_URL=redis://localhost:6380/0 AETHER_POSTGRES_DSN=postgresql://... python scripts/field_test_services.py \
        --report ml/evaluation/v664/field_test_services.json [--stop-cmd 'docker compose stop {service}' --start-cmd 'docker compose start {service}']

Without `--stop-cmd` / `--start-cmd` the outage scenarios are reported as "not run" rather than faked.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audit.hash_chain import verify_chain  # noqa: E402
from audit.postgres_audit import fetch_all_events_ordered  # noqa: E402
from audit.redis_queue import ORDER_PLACEMENT, AuditQueue, build_audit_event  # noqa: E402


def drain(worker, *, limit: int = 50) -> int:
    """Runs the worker until a batch comes back empty, and returns how many rows it wrote."""
    written = 0
    for _ in range(limit):
        count = worker.run_once()
        if not count:
            break
        written += count
    return written


def chain_report(conn) -> dict:
    rows = fetch_all_events_ordered(conn)
    valid, broken = verify_chain(rows)
    return {"rows": len(rows), "valid": valid, "first_broken": broken}


def service(command: str | None, name: str) -> bool:
    if not command:
        return False
    result = subprocess.run(command.format(service=name), shell=True, capture_output=True, text=True, timeout=120)
    return result.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True)
    parser.add_argument("--stop-cmd", default=None, help="shell command that stops a service; {service} is `redis` or `postgres`")
    parser.add_argument("--start-cmd", default=None)
    parser.add_argument("--events", type=int, default=50)
    args = parser.parse_args(argv)
    redis_url, dsn = os.environ.get("AETHER_REDIS_URL", ""), os.environ.get("AETHER_POSTGRES_DSN", "")
    if not redis_url or not dsn:
        print("set AETHER_REDIS_URL and AETHER_POSTGRES_DSN", file=sys.stderr)
        return 2
    import psycopg

    from audit.postgres_worker import PostgresWorker

    report: dict = {"note": "real Redis and Postgres, no broker, no Lean live run: plumbing under outages, not a paper period", "scenarios": {}}
    stream = f"aether:audit:field{int(time.time())}"
    group = f"field-{int(time.time())}"
    queue = AuditQueue(redis_url=redis_url, stream_name=stream)
    worker = PostgresWorker(redis_url=redis_url, postgres_dsn=dsn, stream_name=stream, group_name=group, deadletter_stream=stream + ":dead")

    def push(count: int) -> int:
        return sum(1 for index in range(count) if queue.push(build_audit_event(ORDER_PLACEMENT, {"n": index, "symbol": "BTCUSD"})))

    pushed = push(args.events)
    written = drain(worker)
    with psycopg.connect(dsn) as inspect:
        base = chain_report(inspect)
    report["scenarios"]["flow"] = {"pushed": pushed, "written": written, "chain": base, "passed": pushed == args.events and written == pushed and base["valid"]}

    with psycopg.connect(dsn, autocommit=True) as tamper:
        row = tamper.execute("SELECT event_id, payload FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        if row is not None:
            tamper.execute("UPDATE audit_log SET payload = payload || '{\"tampered\": true}'::jsonb WHERE event_id = %s", (row[0],))
            broken = chain_report(tamper)
            tamper.execute("UPDATE audit_log SET payload = %s::jsonb WHERE event_id = %s", (json.dumps(row[1]), row[0]))
            restored = chain_report(tamper)
            report["scenarios"]["tamper"] = {"detected": broken["valid"] is False, "broken_after": broken, "restored": restored, "passed": broken["valid"] is False and restored["valid"]}

    if args.stop_cmd and args.start_cmd:
        stopped = service(args.stop_cmd, "postgres")
        pushed_down = push(20)
        down_result = {"worker_raised_during_outage": False}
        try:
            drain(worker, limit=2)
        except Exception as error:  # run_once raises on a database failure and run() backs off and reconnects; what matters is what happens to the events after
            down_result = {"worker_raised_during_outage": True, "error": f"{type(error).__name__}: {error}"[:200]}
        started = service(args.start_cmd, "postgres")
        time.sleep(5)
        recovered = 0
        try:
            worker._reconnect_pg(dsn)
            recovered = drain(worker)
        except Exception as error:
            down_result["recover_error"] = f"{type(error).__name__}: {error}"[:200]
        with psycopg.connect(dsn) as inspect:
            after = chain_report(inspect)
        report["scenarios"]["postgres_outage"] = {
            "stopped": stopped, "events_pushed_while_down": pushed_down, **down_result, "restarted": started, "rows_written_after_restart": recovered, "chain": after,
            "passed": stopped and started and pushed_down == 20 and recovered == 20 and after["valid"],
        }
        stopped = service(args.stop_cmd, "redis")
        refused = push(5)
        started = service(args.start_cmd, "redis")
        time.sleep(3)
        queue_again = AuditQueue(redis_url=redis_url, stream_name=stream)
        after_push = push(5) if queue_again._client is not None else 0
        same_instance = push(5)  # the long-lived publisher main.py holds must reconnect by itself
        report["scenarios"]["redis_outage"] = {
            "stopped": stopped, "pushes_accepted_while_down": refused, "restarted": started, "pushes_accepted_after_restart": after_push, "same_publisher_after_restart": same_instance,
            "passed": stopped and started and refused == 0 and after_push == 5 and same_instance == 5,
        }
    else:
        report["scenarios"]["postgres_outage"] = report["scenarios"]["redis_outage"] = {"passed": None, "reason": "not run: no --stop-cmd and --start-cmd"}

    passed = [value.get("passed") for value in report["scenarios"].values()]
    report["all_passed"] = all(item is True for item in passed)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8", newline="\n")
    print(json.dumps({name: value.get("passed") for name, value in report["scenarios"].items()}))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
