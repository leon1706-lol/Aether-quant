"""The trial ledger (V6.5.0): every run this phase scored, as an append-only JSONL file.

`evaluation/trial_registry.py` reads only offline `research.json` summaries and has no idea which window a Sharpe came
from. The deflated Sharpe needs both a count of the configurations ever selectable and the spread of Sharpes on the
window being judged, so each entry states its window and role:

  * `candidate`: could be selected; counts toward N and toward the variance on its window;
  * `verification`: a frozen candidate re-read on a verification window; counts in no N (it is the same trial);
  * `placebo`, `plumbing`: can never be selected (a null, a test of the machinery); they count in nothing.

N keeps the legacy registry's trials. The variance has a floor, so a handful of similar candidates cannot shrink the
bar to nothing; the legacy variance is reported next to it.

Each ledger phase states its window under its own label (V6.6.0's are `v660_selection`), so one phase's variance never mixes
with another's.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROLES = ("candidate", "verification", "placebo", "plumbing")
VARIANCE_FLOOR = 0.04
LEDGER_PHASES = ("v650", "v660")


def append_trial(
    path: Path | str,
    *,
    trial_id: str,
    track: str,
    window: str,
    role: str,
    annualised_sharpe: float | None,
    n_obs: int,
    config_sha: str = "",
    weights_sha: str = "",
    engine: str = "",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one trial's record to the append-only trial ledger."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    value = None if annualised_sharpe is None or not math.isfinite(float(annualised_sharpe)) else float(annualised_sharpe)
    entry = {
        "trial_id": str(trial_id), "track": str(track), "window": str(window), "role": role, "annualised_sharpe": value,
        "n_obs": int(n_obs), "config_sha": str(config_sha), "weights_sha": str(weights_sha), "engine": str(engine),
        "detail": detail or {},
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def read_ledger(path: Path | str) -> list[dict]:
    """The trial ledger's rows, or [] when the file does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def candidate_ids(entries: list[dict]) -> set[str]:
    """The ids of the ledger's candidate trials."""
    return {entry["trial_id"] for entry in entries if entry["role"] == "candidate"}


def legacy_trials(registry: dict[str, Any], exclude_phases: tuple[str, ...] = LEDGER_PHASES) -> list[dict]:
    """The registry's trials not already in a ledger: the registry also holds V6.5.0's ledger, which `candidate_ids` counts
    again, so N read 178 for what is 128."""
    return [trial for trial in registry.get("trials", []) if trial.get("phase") not in exclude_phases]


def deflation_inputs(entries: list[dict], legacy_registry: dict[str, Any], window: str) -> dict[str, Any]:
    """{"N", "var", "legacy_var", "same_window_trials", "floored"} for a deflated Sharpe judged on `window`. A candidate
    scored several times on a window counts once, by its last score. `entries` must hold every ledger phase's rows."""
    legacy = [float(trial["median_sharpe"]) for trial in legacy_trials(legacy_registry)]
    latest: dict[str, float] = {}
    for entry in entries:
        if entry["role"] == "candidate" and entry["window"] == window and entry["annualised_sharpe"] is not None:
            latest[entry["trial_id"]] = float(entry["annualised_sharpe"])
    values = list(latest.values())
    variance = _variance(values)
    floored = variance is None or variance < VARIANCE_FLOOR
    return {
        "N": len(legacy) + len(candidate_ids(entries)),
        "var": VARIANCE_FLOOR if floored else variance,
        "legacy_var": _variance(legacy),
        "same_window_trials": len(values),
        "floored": floored,
    }


def _variance(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)
