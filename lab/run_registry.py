"""A lab's runs: one folder per run (`runs/<id>/run.json` plus what the run wrote), indexed by reading the folders - no
database. The lab's trial ledger (`trials.jsonl`) counts every run toward the deflated Sharpe's N.
"""

from __future__ import annotations

import datetime as _datetime
import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from json_safety import atomic_write_json

LAB_FOLDERS = ("models", "runs", "data")
LAB_TOML = """# Lab defaults; models/<name>/config.toml overrides them (aq lab new NAME --template mlp|multitask|tcn|linear)
[data]
dataset = "data/dataset.csv"   # aq dataset build --prices closes.csv --out data/dataset.csv

[train]
seeds = [7]
memory_profile = "standard"    # low: a 4 GB machine
"""


def init_lab(folder: Path) -> list[str]:
    """Create the lab layout in `folder`; returns what was created (nothing existing is overwritten)."""
    created = []
    folder.mkdir(parents=True, exist_ok=True)
    for name in LAB_FOLDERS:
        if not (folder / name).exists():
            (folder / name).mkdir()
            created.append(f"{name}/")
    if not (folder / "lab.toml").exists():
        (folder / "lab.toml").write_text(LAB_TOML, encoding="utf-8", newline="\n")
        created.append("lab.toml")
    return created


def find_lab(start: Path) -> Path | None:
    """The nearest folder at or above `start` holding a lab.toml."""
    for folder in [start, *start.resolve().parents]:
        if (folder / "lab.toml").exists():
            return folder
    return None


def new_run_id(model: str, now: _datetime.datetime | None = None) -> str:
    """A sortable run id: the time, the model name and a short random suffix."""
    stamp = (now or _datetime.datetime.now(_datetime.timezone.utc)).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{model}_{uuid.uuid4().hex[:6]}"


def write_run(run_dir: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    """Merge `record` into run.json (created if missing) and return the whole record."""
    path = run_dir / "run.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    current.update(record)
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, current, indent=2)
    return current


def read_run(run_dir: Path) -> dict[str, Any]:
    """A run folder's `run.json`."""
    return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))


def list_runs(lab_dir: Path) -> list[dict]:
    """Every run's record, newest first; a folder without run.json is skipped."""
    rows = []
    for folder in sorted((lab_dir / "runs").glob("*/run.json"), reverse=True):
        try:
            rows.append({"id": folder.parent.name, **json.loads(folder.read_text(encoding="utf-8"))})
        except ValueError:
            continue
    return rows


def find_run(lab_dir: Path, key: str) -> Path:
    """A run folder by its id or a unique prefix of it ('latest' is the newest)."""
    runs = []
    for path in sorted((lab_dir / "runs").glob("*/run.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        runs.append(path.parent)
    if key == "latest" and runs:
        return runs[-1]
    matches = [path for path in runs if path.name == key] or [path for path in runs if path.name.startswith(key)]
    if len(matches) != 1:
        raise KeyError(f"{'no' if not matches else 'more than one'} run matches {key!r} in {lab_dir / 'runs'}")
    return matches[0]


def render_runs(rows: list[dict]) -> str:
    """`aq lab runs`'s text: one line per run."""
    if not rows:
        return "no runs yet: aq lab train MODEL"
    lines = []
    for row in rows:
        metrics = row.get("metrics") or {}
        ic = metrics.get("oof_ic_mean")
        spread = metrics.get("oof_ic_seed_std")
        ic_text = "-" if ic is None else f"{ic:+.4f}" + ("" if spread is None else f" +/-{spread:.4f}")
        lines.append(f"{row['id']}  {row.get('status', '?'):<8} {row.get('model', '?'):<14} IC {ic_text:<18} N {row.get('trials_n', '-')}  {row.get('duration_s', '-')}s")
    return "\n".join(lines)
