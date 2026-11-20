"""Resumable runs (V6.6.10): one folder per long run, holding what it needs to continue after a stop (a reboot, a pause for the night).

A run folder keeps `resume.json` (the run's settings, written when it starts) and `state.json` (each finished step, written after it).
`aq cycle retrain --resume`, `aq train --resume` and `aq pipeline run --resume` find the run to continue here, and `--list-runs` lists
them. A run is finished when its record says so or its last step is in its state; anything else can be resumed. Stdlib only.
"""

from __future__ import annotations

import datetime
import json
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Any

RECORD = "resume.json"
STATE = "state.json"


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def new_run_id() -> str:
    """A date-stamped id that sorts in time and does not collide."""
    return f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%d}_{secrets.token_hex(3)}"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    """Written beside its final name and renamed into place: a stop mid-write never leaves a torn record to resume from."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8", newline="\n")
    partial.replace(path)


def start_record(folder: Path, record: dict[str, Any]) -> dict[str, Any]:
    """The run's record, written once when it starts (an existing one is kept: a resumed run keeps its own settings)."""
    existing = read_json(Path(folder) / RECORD)
    if isinstance(existing, dict):
        return existing
    payload = {"started": now(), "finished": False, **record}
    write_json(Path(folder) / RECORD, payload)
    return payload


def update_record(folder: Path, **changes: Any) -> dict[str, Any]:
    """The run's record with `changes` merged in, written back (a version id once chosen, or `finished=True` at the end)."""
    record = {**(read_json(Path(folder) / RECORD, {}) or {}), **changes}
    write_json(Path(folder) / RECORD, record)
    return record


def done_steps(folder: Path) -> list[str]:
    """The steps a run has finished, in the order they finished."""
    return list((read_json(Path(folder) / STATE, {}) or {}).get("done", {}))


def mark_done(folder: Path, step: str, result: Any = None) -> None:
    """Records `step` as finished, with its time and result: a resumed run skips it."""
    state = read_json(Path(folder) / STATE, {}) or {}
    state.setdefault("done", {})[step] = {"at": now(), "result": result}
    write_json(Path(folder) / STATE, state)


def is_finished(folder: Path, *, last_step: str | None = None) -> bool:
    """Whether the run ended: its record says so, or its `last_step` is done."""
    record = read_json(Path(folder) / RECORD, {}) or {}
    return bool(record.get("finished")) or (last_step is not None and last_step in done_steps(folder))


def find_resumable(root: Path, prefix: str, run_id: str | None = None, *, last_step: str | None = None) -> Path | None:
    """The run folder to continue: `<root>/<prefix><run_id>` when named (finished or not, so a finished run reports itself rather
    than vanishing), else the newest one with a record that has not finished."""
    if run_id:
        folder = Path(root) / f"{prefix}{run_id}"
        return folder if (folder / RECORD).exists() else None
    unfinished = [folder for folder in Path(root).glob(f"{prefix}*") if (folder / RECORD).exists() and not is_finished(folder, last_step=last_step)]
    return max(unfinished, key=lambda folder: (folder / RECORD).stat().st_mtime) if unfinished else None


def list_runs(root: Path, prefixes: Sequence[str], *, last_step: str | None = None) -> list[dict[str, Any]]:
    """Every run under `root` with a record, newest first: its id, kind, start, finished steps and whether it can be resumed."""
    rows = []
    for prefix in prefixes:
        for folder in Path(root).glob(f"{prefix}*"):
            record = read_json(folder / RECORD)
            if not isinstance(record, dict):
                continue
            finished = is_finished(folder, last_step=last_step)
            rows.append({"run_id": folder.name[len(prefix):], "kind": prefix.rstrip("_"), "started": record.get("started"), "done": done_steps(folder),
                         "finished": finished, "resumable": not finished, "_mtime": (folder / RECORD).stat().st_mtime})
    rows.sort(key=lambda row: row.pop("_mtime"), reverse=True)
    return rows


def render_runs(rows: Sequence[dict[str, Any]]) -> str:
    """`list_runs`' rows as a table for a terminal: run id, kind, start, state and the steps done."""
    if not rows:
        return "no runs with a resume record yet"
    lines = [f"{'run':<26} {'kind':<9} {'started':<26} {'state':<10} steps done"]
    for row in rows:
        state = "finished" if row["finished"] else "resumable"
        lines.append(f"{row['run_id']:<26} {row['kind']:<9} {row['started']!s:<26} {state:<10} {', '.join(row['done']) or '-'}")
    return "\n".join(lines)
