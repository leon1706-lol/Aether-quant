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

GIB = 1024.0 ** 3
JUDGE_SESSIONS = (60, 252)
RETRAIN_EVERY_SESSIONS = 252
STALE_LEDGER_SESSIONS = 3
RETRAIN_STAGES = ("refresh_data", "build_panel", "walk_forward", "score", "round", "register", "report")
BOOTSTRAP_STAGE = "bootstrap_data"
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


def ram_preflight(host: str, *, total_bytes: int | None = None, min_gb: float = 14.0) -> dict:
    """Whether this host may train. A local machine below the minimum refuses with the numbers: a retrain killed for memory hours in costs more than a clear no. Unknown RAM refuses too."""
    if host not in HOSTS:
        raise ValueError(f"unknown host {host!r}; expected one of {HOSTS}")
    if host == "codespace":
        return {"host": host, "ok": True, "reason": "the Codespace is the host: this machine only drives it"}
    total = total_memory_bytes() if total_bytes is None else int(total_bytes)
    if total is None:
        return {"host": host, "ok": False, "total_gb": None, "min_gb": float(min_gb), "reason": "this machine's RAM could not be read: refusing rather than guessing"}
    gigabytes = total / GIB
    ok = gigabytes >= float(min_gb)
    reason = f"{gigabytes:.1f} GB of RAM, {float(min_gb):.0f} GB needed" + ("" if ok else ": use --host codespace, or --smoke to prove the plumbing on this machine")
    return {"host": host, "ok": ok, "total_gb": round(gigabytes, 1), "min_gb": float(min_gb), "reason": reason}


def retrain_stages(*, data_present: bool) -> list[str]:
    """A fresh checkout builds its own data first, from public sources and the user's own SEC contact: this is what lets anyone retrain."""
    return ([] if data_present else [BOOTSTRAP_STAGE]) + list(RETRAIN_STAGES)


def retrain_due(*, sessions_since_retrain: int | None, decay_states: Mapping[str, str], every_sessions: int = RETRAIN_EVERY_SESSIONS) -> dict:
    """By the calendar, or because the book's generation is decaying. It reports; it starts nothing."""
    decaying = sorted(name for name, state in decay_states.items() if state in ("decaying", "dead", "tripped"))
    if decaying:
        return {"due": True, "reason": f"{', '.join(decaying)} decaying or off the book"}
    if sessions_since_retrain is None:
        return {"due": True, "reason": "no retrain on record"}
    return {"due": int(sessions_since_retrain) >= int(every_sessions), "reason": f"{int(sessions_since_retrain)} sessions since the last retrain, every {int(every_sessions)}"}


def due_actions(
    generations: Mapping[str, Mapping], judged: Mapping, *, session: str | None, sessions_behind: int = 0, sessions_since_retrain: int | None = None, broker_keys: bool = False, policy_enabled: bool = False,
    record_started: bool = True,
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
    elif any(state in ("decaying", "dead", "tripped") for state in states.values()):
        actions.append({"action": "aq cycle research: write a new round (RUNBOOK: Research cycle)", "why": "the book's rule is decaying and there is no model to refit", "urgency": "when convenient"})
    if not broker_keys:
        actions.append({"action": "bring the IB and Coinbase API keys (RUNBOOK: When the keys arrive)", "why": "the paper book can't start without them", "urgency": "owner"})
    if not policy_enabled and any(entry.get("stage") == "ramping" for entry in generations.values()):
        actions.append({"action": "set enabled in ml/generations/policy.json (owner decision)", "why": "a generation is ramping, and the book isn't reading the blended file", "urgency": "owner"})
    return actions


def status_view(generations: Mapping[str, Mapping], judged: Mapping, actions: Sequence[Mapping], *, session: str | None, policy: Mapping) -> dict:
    """The one view `aq cycle status`, the API and the dashboard all read. No secret and no path outside the repo."""
    latest = judged.get("latest_allocation") or {}
    # Before the first allocation row, the book is whatever is active: that is what `scripts/cycle_daily.py` starts from.
    active = [name for name, entry in generations.items() if entry.get("stage") == "active"]
    shares = latest.get("shares") or {name: 1.0 / len(active) for name in active}
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


def read_json_or(path: Path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
