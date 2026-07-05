"""Manual trade-lock override for Aether Quant V2.

`main.py`'s sticky total-drawdown lock (see `_refresh_risk_state()`) never
auto-clears on its own once tripped - by design, a capital-preservation
circuit breaker requiring a deliberate decision to resume trading. This
module is that deliberate decision, expressed as a single config value:
`phase_v2.risk.manual_trade_lock_override` (`true` = force-lock, `false` =
force-clear, absent/`null` = leave today's automatic behavior untouched).

Two callers, both read-modify-write the same key:
- `aq_cli.py`'s `trade-lock` command - a human flips the switch directly.
- `retraining/orchestrator.py::promote()` - a successful promotion clears it
  automatically, tying "trading resumes" to "a genuinely new model shipped".

This is the first place in the codebase where a Python process writes to
`config.json` (every other reader treats it as human-edited, read-only
input) - a deliberate, narrow exception, not a new general pattern. It is a
*standing* switch, not one-shot: it stays in effect until explicitly changed
again, so `main.py` itself never writes back to `config.json` - it only
reads this one key once per session rollover (see `_refresh_risk_state()`).
"""

from __future__ import annotations

import json
from pathlib import Path

from execution.config_cache import read_cached

_PHASE_V2_KEY = "phase_v2"
_RISK_KEY = "risk"
_OVERRIDE_KEY = "manual_trade_lock_override"


def read_manual_trade_lock_override(config_path: Path) -> bool | None:
    """Returns True/False if a manual override is set, None if absent/unset
    or the config file doesn't exist yet - never raises. Mtime-gated cache
    (see execution/config_cache.py) - picks up an edit as soon as the file's
    mtime changes, not on a fixed schedule."""
    return read_cached(config_path, _read_manual_trade_lock_override_uncached)


def _read_manual_trade_lock_override_uncached(config_path: Path) -> bool | None:
    if not config_path.exists():
        return None
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    value = config.get(_PHASE_V2_KEY, {}).get(_RISK_KEY, {}).get(_OVERRIDE_KEY)
    return value if isinstance(value, bool) else None


def write_manual_trade_lock_override(value: bool | None, config_path: Path) -> None:
    """Read-modify-write config.json, setting only
    phase_v2.risk.manual_trade_lock_override - every other key is preserved
    untouched. value=None removes the override key entirely (returns to
    fully automatic behavior)."""
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    phase_v2 = config.setdefault(_PHASE_V2_KEY, {})
    risk = phase_v2.setdefault(_RISK_KEY, {})
    if value is None:
        risk.pop(_OVERRIDE_KEY, None)
    else:
        risk[_OVERRIDE_KEY] = value

    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
        f.write("\n")
