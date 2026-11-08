"""What a `live_plumbing.sh` run proved, read from its logs (V6.6.4, B6). Pure functions over text, so a test can hold the readings to fixture logs.

    python scripts/lean_smoke/live_plumbing_report.py --dir /tmp/aq_lean/live_plumbing --out ml/evaluation/v664/live_plumbing.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path

CHECKS = {
    "engine_started_live": r"LEAN ALGORITHMIC TRADING ENGINE",
    "main_py_imported": r"main successfully imported",
    "paper_brokerage": r"creating brokerage 'PaperBrokerage'",
    "fake_data_queue": r"FakeDataQueue",
    "ticks_flowing": r"TICKS PER SECOND:: [1-9]",
    "warmed_up": r"Algorithm finished warming up",
}
FAILURES = (r"Traceback", r"Algorithm\.Initialize\(\) Error", r"Runtime Error", r"PythonException", r"Unhandled exception")


def scan_engine_log(text: str) -> dict:
    """Which startup stages the engine log shows, and any failure it shows."""
    found = {name: bool(re.search(pattern, text)) for name, pattern in CHECKS.items()}
    found["failures"] = [line.strip()[:200] for line in text.splitlines() if any(re.search(pattern, line) for pattern in FAILURES)][:5]
    return found


def scan_algorithm_log(text: str) -> dict:
    """What main.py itself logged: warm-up, and any audit-queue trouble it reported while a service was down."""
    lines = text.splitlines()
    return {
        "lines": len(lines),
        "warmup_finished": any("finished warming up" in line for line in lines),
        "audit_push_failures": sum("AuditQueue.push failed" in line for line in lines),
        "errors": [line.strip()[:200] for line in lines if re.search(r"\b(error|exception|traceback)\b", line, re.IGNORECASE)][:5],
    }


def build_report(run1: Mapping, run2: Mapping, facts: Mapping) -> dict:
    """The per-scenario verdicts. A scenario is `passed` only when its evidence is in the logs; anything not observed says so."""
    engine1, engine2 = scan_engine_log(run1.get("engine", "")), scan_engine_log(run2.get("engine", ""))
    algo1 = scan_algorithm_log(run1.get("algorithm", ""))
    startup = all(engine1[name] for name in CHECKS) and not engine1["failures"]
    return {
        "scenarios": {
            "starts_in_live_mode_on_paper_brokerage": {"passed": startup, "engine": engine1},
            "alive_through_redis_and_postgres_outages": {
                "passed": bool(facts.get("alive_after_outages")) and not engine1["failures"],
                "outage_seconds": facts.get("outage_seconds"),
                "audit_push_failures_logged": algo1["audit_push_failures"],
                "note": "the algorithm kept running while both services were stopped, and was still running after they came back",
            },
            "restart_comes_back_up": {"passed": all(engine2[name] for name in CHECKS) and not engine2["failures"] and bool(facts.get("state_file_after_restart")), "engine": engine2},
            "audit_chain_verifies": {"passed": bool(facts.get("audit_verify_ok")), "vacuous": "trivially valid" in facts.get("audit_verify_text", ""), "detail": facts.get("audit_verify_text", "")},
        },
        "not_proved": [
            "an order reaching a broker: no rebalance fell inside the window, and PaperBrokerage fills against the fake ticks, not a market",
            "the kill switch under a forced drawdown: main.py is unchanged and FakeDataQueue prices are random, so no drawdown was forced",
            "reconciliation against a real broker's positions (needs the IB or Coinbase account)",
        ],
        "algorithm": algo1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    base = Path(args.dir)

    def read(name: str) -> str:
        path = base / name
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    facts = json.loads(read("facts.json") or "{}")
    report = build_report({"engine": read("engine1.log"), "algorithm": read("results1/AetherQuantAlgorithm-log.txt")},
                          {"engine": read("engine2.log"), "algorithm": read("results2/AetherQuantAlgorithm-log.txt")}, facts)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    passed = {name: value["passed"] for name, value in report["scenarios"].items()}
    print(json.dumps(passed))
    return 0 if all(passed.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
