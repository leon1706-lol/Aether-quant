"""Evidence for the paper-to-live scorecard (V6.6.5, #352): read from what the project already writes, each source degrading
to "unknown" (which fails) rather than to a guess. `aq live-readiness` calls `gather_evidence`, then
`execution.live_readiness.build_scorecard`, and writes `visualization/grafana/live_readiness.json` for the dashboard."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution.live_readiness import Scorecard, build_scorecard, resolve_thresholds

__all__ = ["READINESS_FILE", "DOCS_BLOCK", "gather_evidence", "forward_rows_from_branch", "write_scorecard", "readiness_scorecard", "write_docs_block"]

READINESS_FILE = Path("visualization") / "grafana" / "live_readiness.json"
DOCS_BLOCK = ("<!-- AQ:READINESS_START -->", "<!-- AQ:READINESS_END -->")


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _latest(root: Path, pattern: str) -> Path | None:
    found = sorted(Path(root).glob(pattern), key=lambda path: (path.stat().st_mtime, str(path)))
    return found[-1] if found else None


def forward_rows_from_branch(root: Path) -> list[dict]:
    """The generations' ledger on the `forward-ledger` branch (local copy; `aq cycle status` fetches it). Empty when absent."""
    try:
        result = subprocess.run(["git", "show", "forward-ledger:forward/generations.jsonl"], cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()] if result.returncode == 0 else []


def _forward(root: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from evaluation.generation_ledger import judge_generations

    registry = _json(Path(root) / "ml" / "generations" / "registry.json") or {}
    active = [str(entry.get("name")) for entry in registry.get("generations", []) if entry.get("stage") == "active"]
    if not rows:
        return {"forward_source": "forward/generations.jsonl (not found)"}
    judged = judge_generations(list(rows))
    if not judged.get("chain_valid"):
        return {"forward_source": f"forward/generations.jsonl chain broken at row {judged.get('first_broken_row')}", "forward_sessions": 0}
    generations = judged.get("generations") or {}
    name = next((candidate for candidate in active if candidate in generations), None) or (sorted(generations)[0] if generations else None)
    if name is None:
        return {"forward_source": "forward/generations.jsonl (no generation)"}
    report = generations[name]
    alpha = report.get("alpha") or {}
    return {"forward_sessions": int(report.get("sessions") or 0), "forward_alpha_t": alpha.get("t_hac"), "forward_source": f"forward/generations.jsonl, {name}"}


def gather_evidence(root: Path, account_id: str | None = None, *, forward_rows: Sequence[Mapping[str, Any]] | None = None,
                    paper_check: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every metric's evidence for one account. `forward_rows` (default: the forward-ledger branch) and `paper_check`
    (`aq evaluate --paper-check`'s report) can be passed in; nothing here needs a broker, Redis or Postgres."""
    from execution.accounts import resolve_account
    from execution.accounts_io import ACCOUNT_SECRETS, load_account_config, load_accounts
    from execution.live_credentials import postgres_dsn_is_live_safe
    from execution.live_credentials_io import load_postgres_dsn
    from execution.secrets_io import all_secret_status, load_secret

    root = Path(root)
    evidence: dict[str, Any] = {}
    config = _json(root / "config.json") or {}
    try:
        accounts = load_accounts(root, config.get("phase_v2", {}))
        account = resolve_account(accounts, account_id)
        effective = load_account_config(config, account.id, root)["phase_v2"]
        evidence["accounts_valid"] = True
    except ValueError as error:
        evidence["accounts_valid"] = False
        evidence["accounts_error"] = str(error)
        account, effective = None, config.get("phase_v2", {})

    evidence.update(_forward(root, forward_rows if forward_rows is not None else forward_rows_from_branch(root)))
    alpha_proof = _json(root / "ml" / "evaluation" / "alpha_proof.json") or {}
    dsr = ((alpha_proof.get("periods") or {}).get("full") or {}).get("dsr")
    if isinstance(dsr, Mapping):
        dsr = dsr.get("value")
    evidence["book_dsr"] = dsr
    evidence["book_dsr_source"] = f"ml/evaluation/alpha_proof.json ({alpha_proof.get('run', '-')})" if alpha_proof else "ml/evaluation/alpha_proof.json (not found)"
    round_file = _latest(root, "ml/evaluation/v6*/r_round*.json")
    if round_file is not None:
        rounds = (_json(round_file) or {}).get("rounds") or {}
        last = rounds[sorted(rounds)[-1]] if rounds else {}
        evidence["round_pbo"] = last.get("pbo")
        evidence["round_source"] = f"{round_file.relative_to(root).as_posix()}, round {sorted(rounds)[-1] if rounds else '-'}"

    if paper_check:
        evidence["paper_trading_days"] = paper_check.get("trading_days")
        evidence["paper_rebalances"] = paper_check.get("rebalances")
        evidence["paper_bands_all_inside"] = paper_check.get("all_inside")

    field_report = _latest(root, "ml/evaluation/field_test/*/report.json")
    if field_report is not None:
        report = _json(field_report) or {}
        judged = report.get("judged") or {}
        evidence["field_test"] = {"date": report.get("date"), "all_passed": bool(judged.get("all_passed")), "passed": judged.get("passed"),
                                  "total": judged.get("total"), "path": field_report.relative_to(root).as_posix()}

    kill_switch = (effective.get("risk") or {}).get("kill_switch") or {}
    evidence["kill_switch_enabled"] = bool(kill_switch.get("enabled")) if "enabled" in kill_switch else None
    reconciliation = effective.get("reconciliation") or {}
    evidence["reconciliation_trips_kill_switch"] = bool(reconciliation.get("trips_kill_switch")) if "trips_kill_switch" in reconciliation else None
    evidence["max_total_drawdown_pct"] = (effective.get("live") or {}).get("max_allowed_total_drawdown_pct")

    if account is not None:
        needed = ACCOUNT_SECRETS.get(account.broker, ())
        status = all_secret_status(account.id, needed) if needed else []
        evidence["secrets_all_safe"] = bool(needed) and all(row["resolved"] and row["stored_safely"] for row in status)
        evidence["secrets_detail"] = "no broker secrets: a paper account" if not needed else ", ".join(f"{row['name']} {row['source'] or 'missing'}" for row in status)
        evidence["live_account_ok"] = account.broker != "paper" and account.capital_usd is not None
        evidence["live_account_detail"] = f"{account.id}: {account.broker}, capital {account.capital_usd}"
    dsn = load_postgres_dsn()
    evidence["postgres_dsn_safe"] = postgres_dsn_is_live_safe(dsn) if dsn else None
    audit = _json(root / "visualization" / "grafana" / "audit_log.json")
    evidence["audit_chain_valid"] = audit.get("chain_valid") if isinstance(audit, Mapping) and "chain_valid" in audit else None
    evidence["telegram_configured"] = load_secret("TELEGRAM_BOT_TOKEN").value is not None and load_secret("TELEGRAM_CHAT_ID").value is not None
    backup = _json(root / "state" / "backups" / "last_backup.json")
    evidence["backup_date"] = backup.get("date") if isinstance(backup, Mapping) else None
    digest = root / "state" / "deploy" / "image_digest.txt"
    evidence["image_digest"] = digest.read_text(encoding="utf-8").strip() if digest.is_file() else None

    verification_file = _latest(root, "ml/evaluation/v6*/verification.json")
    if verification_file is not None:
        doc = _json(verification_file) or {}
        rows = doc.get("rows") or []
        failed = [row for row in rows if str(row.get("result")) not in ("pass", "skip")]
        stamp = doc.get("date") or datetime.fromtimestamp(verification_file.stat().st_mtime, timezone.utc).date().isoformat()
        evidence["verification"] = {"date": stamp, "all_passed": bool(rows) and not failed, "summary": f"{len(rows) - len(failed)}/{len(rows)} surfaces pass",
                                    "path": verification_file.relative_to(root).as_posix()}
    mutation_file = _latest(root, "ml/evaluation/v6*/mutation_summary.json")
    if mutation_file is not None:
        doc = _json(mutation_file) or {}
        # the current tests' kill rate on every seed run after them, the lowest one counting (never a cherry-picked seed)
        after = [doc[key]["overall"][0] for key in doc if "after" in key and isinstance(doc[key], Mapping) and isinstance(doc[key].get("overall"), list)]
        if after:
            evidence["mutation_score"] = min(after)
            evidence["mutation_source"] = mutation_file.relative_to(root).as_posix()
    return evidence


def readiness_scorecard(root: Path, account_id: str | None = None, *, now: datetime | None = None, **kwargs: Any) -> Scorecard:
    config = _json(Path(root) / "config.json") or {}
    thresholds = resolve_thresholds((config.get("phase_v2") or {}).get("live_readiness"))
    return build_scorecard(gather_evidence(root, account_id, **kwargs), thresholds, now=now or datetime.now(timezone.utc), account=account_id or "default")


def write_scorecard(root: Path, scorecard: Scorecard) -> Path:
    from json_safety import atomic_write_json

    path = Path(root) / READINESS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, scorecard.to_dict(), indent=1)
    return path


def write_docs_block(path: Path, markdown: str) -> bool:
    """Replace the generated block between the AQ:READINESS markers in `path`; False when the markers are missing."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    start, end = DOCS_BLOCK
    if start not in text or end not in text:
        return False
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    target.write_text(f"{head}{start}\n{markdown.rstrip()}\n{end}{tail}", encoding="utf-8", newline="\n")
    return True
