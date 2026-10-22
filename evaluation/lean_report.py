"""`aq evaluate --lean-report` (V6.3.0): the run-folder tools for one finished Lean run, in the order the README needs
them. This module is the pure plan (which `aq evaluate` flags, with which extra arguments); `aq_cli._run_lean_report`
executes it step by step, each step best-effort so one failing tool never hides the others' results."""

from __future__ import annotations

# (label, the `aq evaluate` flag attribute set on a copy of the parsed args)
LEAN_REPORT_FLAGS = (
    ("lean statistics", "lean_stats"),
    ("Lean Monte Carlo", "lean_monte_carlo"),
    ("order-level audit", "audit_backtest"),
    ("P&L attribution", "attribute_lean"),
    ("fill prices", "audit_fills"),
    ("backtest statistics", "backtest_stats"),
    ("classification parity", "classification_parity"),
)


def split_periods(config: dict, names: tuple[str, ...] = ("backtest", "holdout")) -> list[str]:
    """`START..END` of the configured windows a Lean run spans (the README's Lean-vs-offline block reads one per split)."""
    windows = (config.get("phase1", {}) or {}).get("windows", {}) or {}
    periods = []
    for name in names:
        window = windows.get(name) or {}
        if window.get("start") and window.get("end"):
            periods.append(f"{window['start']}..{window['end']}")
    return periods


def lean_report_steps(config: dict) -> list[tuple[str, dict]]:
    """[(label, {arg: value})]: every step switches its own flag on and the others off; the audit and the attribution
    get the split periods."""
    flags = [flag for _label, flag in LEAN_REPORT_FLAGS]
    steps = []
    for label, flag in LEAN_REPORT_FLAGS:
        overrides = {other: other == flag for other in flags}
        overrides["lean_report"] = False
        if flag in ("audit_backtest", "attribute_lean"):
            overrides["period"] = split_periods(config)
        steps.append((label, overrides))
    return steps
