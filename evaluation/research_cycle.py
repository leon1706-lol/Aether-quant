"""The research cycle's plan (V6.6.1): what is due today, whether a host may train, how to schedule it. Pure, stdlib only, so `aq cycle status` answers on any machine.

The cycle: research a round -> freeze -> holdout -> shadow on the forward ledger -> ramp on the paper book -> decay -> retire, with a retrain when the calendar or the ledger asks for one. A step
that spends the owner's budget or changes the book only ever reports itself as due here.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

GIB = 1024.0 ** 3
JUDGE_SESSIONS = (60, 252)
RETRAIN_EVERY_SESSIONS = 252
STALE_LEDGER_SESSIONS = 3
RETRAIN_STAGES = ("refresh_data", "build_panel", "walk_forward", "score", "round", "register", "report")
BOOTSTRAP_STAGE = "bootstrap_data"
STACK_STAGES = (
    "snapshot_active", "factor_audit", "dataset", "parity_audit", "multitask", "sequence", "gating", "walk_forward", "scores", "pins", "register", "report",
)
MODEL_AGE_WARNING_DAYS = 30
HOSTS = ("local", "codespace")


def total_memory_bytes() -> int | None:
    """This machine's RAM, or None if it can't be read. Stdlib only, so the check works before anything heavy is installed."""
    try:
        if sys.platform == "win32":
            class _Status(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong),
                    ("avail_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong), ("avail_extended", ctypes.c_ulonglong),
                ]

            status = _Status()
            status.length = ctypes.sizeof(_Status)
            return int(status.total_phys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


MIN_RAM_GB = {"standard": 14.0, "low": 3.5}  # retraining/slicing.PROFILES' min_total_gb; this module stays stdlib only


def ram_preflight(host: str, *, total_bytes: int | None = None, min_gb: float | None = None, profile: str = "standard") -> dict[str, Any]:
    """Whether this host may train. A local machine below the minimum refuses with the numbers: a retrain killed for memory hours in costs more than a clear no. Unknown RAM refuses too.
    The minimum is the memory profile's unless `min_gb` overrides it: `low` (V6.6.10) trains the stack on a 4 GB machine, slower."""
    if host not in HOSTS:
        raise ValueError(f"unknown host {host!r}; expected one of {HOSTS}")
    if profile not in MIN_RAM_GB:
        raise ValueError(f"unknown memory profile {profile!r}; expected one of {sorted(MIN_RAM_GB)}")
    min_gb = MIN_RAM_GB[profile] if min_gb is None else float(min_gb)
    if host == "codespace":
        return {"host": host, "ok": True, "reason": "the Codespace is the host: this machine only drives it"}
    total = total_memory_bytes() if total_bytes is None else int(total_bytes)
    if total is None:
        return {"host": host, "ok": False, "total_gb": None, "min_gb": min_gb, "profile": profile, "reason": "this machine's RAM could not be read: refusing rather than guessing"}
    gigabytes = total / GIB
    ok = gigabytes >= min_gb
    advice = ": use --memory-profile low (slower, fits 4 GB), --host codespace, or --smoke to prove the plumbing" if profile == "standard" else ": use --host codespace, or --smoke to prove the plumbing"
    reason = f"{gigabytes:.1f} GB of RAM, {min_gb:g} GB needed under the {profile} profile" + ("" if ok else advice)
    return {"host": host, "ok": ok, "total_gb": round(gigabytes, 1), "min_gb": min_gb, "profile": profile, "reason": reason}


def retrain_stages(*, data_present: bool) -> list[str]:
    """A fresh checkout builds its own data first, from public sources and the user's own SEC contact: this is what lets anyone retrain."""
    return ([] if data_present else [BOOTSTRAP_STAGE]) + list(RETRAIN_STAGES)


def stack_stages() -> list[str]:
    """The model stack's retrain, in order. The first stage zips the active artifacts; nothing after it writes into the active `ml/` except the dataset build."""
    return list(STACK_STAGES)


def stack_plan(
    procedure: Mapping[str, Any], *, run_id: str, python: str = "python", score_end: str | None = None, resume_id: str | None = None, profile: str = "standard",
) -> list[tuple[str, list[str] | None]]:
    """(stage, command) for each stage of the stack retrain; a stage with no command (None) runs in this process. Every trainer writes to
    `ml/versions/<run id>_<part>/` (`--candidate`, `--version-id`), never over the installed models. `stack_asof` is a new procedure, so its scores are only written for a research round.
    A `low` profile passes `--memory-profile low` to every trainer (V6.6.10); `standard` leaves the commands as they were."""
    candidate = f"{run_id}_base"
    memory = ["--memory-profile", profile] if profile != "standard" else []
    peaks = ["--log-peak-memory", f"ml/cycle/retrain_{run_id}/memory_peaks.jsonl"] if profile != "standard" else []
    walk_forward = [python, "train.py", "--walk-forward", "--include-multitask", "--include-sequence", "--mode", str(procedure.get("mode", "expanding")), *memory,
                    "--run-id-file", f"ml/cycle/retrain_{run_id}/walk_forward_run_id"]
    if resume_id:
        walk_forward += ["--resume-run-id", resume_id]
    # the run's own folder (V6.6.10): the default ml/evaluation/v650/scores holds an earlier round's selection scores
    scores = [python, "scripts/v650_ml_scores.py", "--run-id", resume_id or "<walk-forward run id>", "--end", score_end, "--out", f"ml/cycle/retrain_{run_id}/scores"] if score_end else None
    # V6.6.10: the multitask and sequence trainers read the dataset and schema this run built, never the installed ones (which hold the
    # universe of the last build: EOSUSD was still in it, #385)
    built = ["--dataset-path", f"ml/versions/{candidate}/full_dataset.csv", "--feature-schema-path", f"ml/versions/{candidate}/feature_schema.json"]
    return [
        ("snapshot_active", None),
        ("factor_audit", [python, "-m", "data_pipeline.factor_file_backfill", "--audit"]),
        ("dataset", [python, "train.py", "--candidate", "--version-id", candidate, "--write-dataset", *memory]),
        # the run's own dataset against its own scaler (V6.6.10): the installed dataset is not what this run trains on
        ("parity_audit", [python, "scripts/feature_parity_audit.py", "--skip-synthetic", "--dataset", f"ml/versions/{candidate}/full_dataset.csv",
                          "--scaler-stats", f"ml/versions/{candidate}/scaler_stats.json", "--schema", f"ml/versions/{candidate}/feature_schema.json",
                          "--output", f"ml/cycle/retrain_{run_id}/feature_parity_report.json"]),
        ("multitask", [python, "train_multitask.py", "--version-id", f"{run_id}_mt", *built, *memory, *peaks]),
        ("sequence", [python, "train_sequence.py", "--version-id", f"{run_id}_seq", *built, *memory, *peaks]),
        ("gating", [python, "train_gating.py", "--version-id", f"{run_id}_gate", *memory, *peaks]),
        ("walk_forward", walk_forward),
        ("scores", scores),
        ("pins", None),
        ("register", None),
        ("report", None),
    ]


def validate_plan_flags(plan: Sequence[tuple[str, list[str] | None]], *, runner: Any) -> list[str]:
    """Every `--flag` a planned command passes that its script's own `--help` does not list, as "script: --flag". [] is a plan the trainers accept.
    A retrain that fails on a flag typo in its last stage has already spent the Codespace hours."""
    problems: list[str] = []
    for stage, command in plan:
        if not command:
            continue
        python, rest = command[0], command[1:]
        target = rest[:2] if rest and rest[0] == "-m" else rest[:1]
        result = runner([python, *target, "--help"], capture_output=True, text=True)
        if result.returncode != 0:
            problems.append(f"{stage}: `{' '.join(target)} --help` exit {result.returncode}")
            continue
        text = (result.stdout or "") + (result.stderr or "")
        problems.extend(f"{target[-1]}: {flag}" for flag in sorted({token for token in command if token.startswith("--")}) if flag not in text)
    return problems


def retrain_due(*, sessions_since_retrain: int | None, decay_states: Mapping[str, str], every_sessions: int = RETRAIN_EVERY_SESSIONS) -> dict[str, Any]:
    """By the calendar, or because the book's generation is decaying. It reports; it starts nothing."""
    decaying = sorted(name for name, state in decay_states.items() if state in ("decaying", "dead", "tripped"))
    if decaying:
        return {"due": True, "reason": f"{', '.join(decaying)} decaying or off the book"}
    if sessions_since_retrain is None:
        return {"due": True, "reason": "no retrain on record"}
    return {"due": int(sessions_since_retrain) >= int(every_sessions), "reason": f"{int(sessions_since_retrain)} sessions since the last retrain, every {int(every_sessions)}"}


def due_actions(
    generations: Mapping[str, Mapping], judged: Mapping[str, Any], *, session: str | None, sessions_behind: int = 0, sessions_since_retrain: int | None = None, broker_keys: bool = False, policy_enabled: bool = False,
    record_started: bool = True, model_age_days: float | None = None, max_model_age_days: float = 180.0,
) -> list[dict]:
    """What a person or a job should do next, most urgent first."""
    actions: list[dict] = []
    if judged.get("chain_valid") is False:
        actions.append({"action": "investigate", "why": f"the generations' chain is broken at row {judged.get('first_broken_row')}: no figure from it can be used", "urgency": "now"})
    if not record_started:
        actions.append({"action": "gh workflow run research-cycle.yml", "why": "record not started: the generations' ledger has no row, and a missed session can't be backfilled", "urgency": "now"})
    if sessions_behind > STALE_LEDGER_SESSIONS:
        actions.append({"action": "gh workflow enable research-cycle.yml", "why": f"the last row is {sessions_behind} sessions old: GitHub disables a schedule after 60 days of no repo activity", "urgency": "now"})
    latest = judged.get("latest_allocation") or {}
    states = dict(latest.get("states") or {})
    for name, row in sorted((judged.get("generations") or {}).items()):
        sessions = int(row.get("sessions") or 0)
        for mark in JUDGE_SESSIONS:
            if sessions == mark:
                actions.append({"action": f"aq evaluate --forward-ledger, then judge {name}", "why": f"{name} has reached {mark} forward sessions", "urgency": "today"})
    for name, entry in sorted(generations.items()):
        stage, state = entry.get("stage"), states.get(name)
        if stage in ("active", "ramping", "fading", "winding_down") and state in ("dead", "tripped"):
            actions.append({"action": f"aq cycle promote --generation {name} --to retired", "why": f"{name} is {state}: its capital left at the last row, and the registry should say so", "urgency": "today"})
        if stage == "ramping" and float((latest.get("shares") or {}).get(name, 0.0)) >= 1.0:
            actions.append({"action": f"aq cycle promote --generation {name} --to active", "why": f"{name} holds the whole book", "urgency": "today"})
        if stage == "winding_down" and name in (latest.get("shares") or {}) and float(latest["shares"][name]) == 0.0:
            actions.append({"action": f"aq cycle promote --generation {name} --to retired", "why": f"{name} has wound down to nothing", "urgency": "today"})
    due = retrain_due(sessions_since_retrain=sessions_since_retrain, decay_states=states)
    if any(entry.get("kind") == "model" for entry in generations.values()):
        if due["due"]:
            actions.append({"action": "aq cycle retrain --host codespace", "why": due["reason"], "urgency": "when convenient"})
        if model_age_days is not None and model_age_days >= max_model_age_days - MODEL_AGE_WARNING_DAYS and not due["due"]:
            days_left = max(0.0, max_model_age_days - model_age_days)
            actions.append({"action": "aq cycle retrain --host codespace --procedure stack", "why": (f"the installed models are {model_age_days:.0f} days old and the kill switch stops a model book at "
                                                                                   f"{max_model_age_days:.0f} ({days_left:.0f} days left)"), "urgency": "when convenient"})
    elif any(state in ("decaying", "dead", "tripped") for state in states.values()):
        actions.append({"action": "aq cycle research: write a new round (RUNBOOK: Research cycle)", "why": "the book's rule is decaying and there is no model to refit", "urgency": "when convenient"})
    if not broker_keys:
        actions.append({"action": "bring the IB and Coinbase API keys (RUNBOOK: When the keys arrive)", "why": "the paper book can't start without them", "urgency": "owner"})
    if not policy_enabled and any(entry.get("stage") == "ramping" for entry in generations.values()):
        actions.append({"action": "set enabled in ml/generations/policy.json (owner decision)", "why": "a generation is ramping, and the book isn't reading the blended file", "urgency": "owner"})
    return actions


def status_view(generations: Mapping[str, Mapping], judged: Mapping[str, Any], actions: Sequence[Mapping], *, session: str | None, policy: Mapping[str, Any]) -> dict[str, Any]:
    """The one view `aq cycle status`, the API and the dashboard all read. No secret and no path outside the repo."""
    latest = judged.get("latest_allocation") or {}
    # Before the first allocation row, the book is whatever is active: that is what `scripts/cycle_daily.py` starts from.
    active = [name for name, entry in generations.items() if entry.get("stage") == "active"]
    # An installed blend (V6.6.9, R-INSTALL2) fixes its shares by the owner's rule, not by the glide: say those, not an equal split nobody computed.
    installed = {str(name): float(share) for name, share in (policy.get("installed_shares") or {}).items() if name in generations}
    shares = latest.get("shares") or installed or {name: 1.0 / len(active) for name in active}
    rows = []
    for name, entry in sorted(generations.items()):
        forward = (judged.get("generations") or {}).get(name) or {}
        rows.append({
            "id": name, "stage": entry.get("stage"), "tier": entry.get("tier"), "kind": entry.get("kind"), "share": float(shares.get(name, 0.0)), "state": (latest.get("states") or {}).get(name),
            "sessions": forward.get("sessions"), "sharpe": forward.get("sharpe"), "alpha_t": (forward.get("alpha") or {}).get("t_hac"), "note": entry.get("note", ""),
        })
    return {
        "session": session, "enabled": bool(policy.get("enabled")), "tbills": latest.get("tbills"), "chain_valid": judged.get("chain_valid"), "generations": rows, "due": list(actions),
        "glide_policy": policy.get("glide_policy"), "glide": policy.get("glide"),
    }


def render_schedule(platform: str, *, repo: Path, python: str = "python", host: str = "local") -> str:
    """The text of a weekly retrain-if-due job, Sunday 03:00. It renders only: `aq cycle schedule install` is what registers it, on a machine that passes the preflight."""
    repo = Path(repo)
    command = f"{python} aq_cli.py cycle retrain --host {host} --if-due"
    if platform == "linux":
        return f"0 3 * * 0 cd {repo} && {command} >> ml/cycle/schedule.log 2>&1\n"
    if platform == "windows":
        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
            "  <Triggers><CalendarTrigger><StartBoundary>2026-11-08T03:00:00</StartBoundary><ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Sunday/></DaysOfWeek></ScheduleByWeek></CalendarTrigger></Triggers>\n"
            "  <Settings><StartWhenAvailable>true</StartWhenAvailable><DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings>\n"
            f"  <Actions><Exec><Command>{python}</Command><Arguments>aq_cli.py cycle retrain --host {host} --if-due</Arguments><WorkingDirectory>{repo}</WorkingDirectory></Exec></Actions>\n</Task>\n"
        )
    raise ValueError(f"unknown platform {platform!r}; expected windows or linux")


def install_command(platform: str, *, task_file: Path) -> list[str]:
    """What registers the rendered job. Returned, not run, so a test can read it and a person can check it first."""
    if platform == "windows":
        return ["schtasks", "/Create", "/TN", "AetherQuantRetrain", "/XML", str(task_file), "/F"]
    if platform == "linux":
        return ["crontab", str(task_file)]
    raise ValueError(f"unknown platform {platform!r}")


def sessions_since_retrain(run_root: Path, sessions: Sequence[str]) -> int | None:
    """Sessions recorded since the newest real retrain finished. A smoke run registers no procedure, so it never counts. None with none on record."""
    newest = None
    for state_path in Path(run_root).glob("retrain_*/state.json"):
        state = read_json_or(state_path, {})
        register = (state.get("done") or {}).get("register") or {}
        if isinstance(register.get("result"), dict) and register["result"].get("procedure"):
            stamp = str(register.get("at"))[:10]
            newest = stamp if newest is None or stamp > newest else newest
    return None if newest is None else sum(1 for day in sessions if day > newest)


def read_json_or(path: Path, default: Any) -> Any:
    """A JSON file's content, or `default` when the file does not exist."""
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
