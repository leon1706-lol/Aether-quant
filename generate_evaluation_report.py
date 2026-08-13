"""Regenerates README.md's Offline Evaluation, Walk-Forward Training/Testing,
and Other Metrics subsections (siblings of Lean Backtest, which
generate_backtest_report.py already owns) from whatever `aq evaluate`/`aq
train --walk-forward` last wrote to ml/evaluation/ and ml/versions/.

Same practical-substitute-for-live-update approach as generate_backtest_report.py:
`aq evaluate` calls this module after any of --rank-book/--capacity/--stress/
--all/--reconcile-book-history/--replay-kill-switch/--walk-forward-summary,
and it rewrites the relevant marker-delimited sections in-place. Every
section degrades gracefully (an em-dash placeholder table row, not a
crash/traceback) when its source file doesn't exist yet - a fresh checkout
that has never run `aq evaluate` still gets a readable README, matching
monitoring/evaluation_state.py's own "not_evaluated" contract.

Data sources (all optional, independently missing-tolerant):
- ml/evaluation/rank_book_simulation_{sequence,multitask}.json (this
  module's own additive per-model copies - see aq_cli.py::cmd_evaluate())
- ml/evaluation/capacity_report_{sequence,multitask}.json
- ml/evaluation/cost_stress_report_{sequence,multitask}.json
- ml/versions/walk-forward-*/walk_forward_summary.json (newest by mtime)
- ml/evaluation/book_history_reconciliation.json
- ml/evaluation/kill_switch_replay.json
- The latest real Lean backtest result JSON (reuses
  generate_backtest_report.py's own loader - same "latest complete run"
  definition, so the Lean-vs-offline comparison in Other Metrics never
  compares against a stale/different backtest than what Lean Backtest
  itself displays).

Usage:
    python generate_evaluation_report.py [--readme README.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from generate_backtest_report import (
    README_PATH,
    _atomic_write,
    _replace_between_markers,
    find_latest_backtest_result_json,
    load_backtest_summary,
)

ROOT_DIR = Path(__file__).resolve().parent
ML_DIR = ROOT_DIR / "ml"
EVALUATION_DIR = ML_DIR / "evaluation"
VERSIONS_DIR = ML_DIR / "versions"

EVAL_MARKER_START = "<!-- AQ:EVAL_START -->"
EVAL_MARKER_END = "<!-- AQ:EVAL_END -->"
EVAL_FULL_STATS_MARKER_START = "<!-- AQ:EVAL_FULL_STATS_START -->"
EVAL_FULL_STATS_MARKER_END = "<!-- AQ:EVAL_FULL_STATS_END -->"

WALKFORWARD_MARKER_START = "<!-- AQ:WALKFORWARD_START -->"
WALKFORWARD_MARKER_END = "<!-- AQ:WALKFORWARD_END -->"
WALKFORWARD_FULL_STATS_MARKER_START = "<!-- AQ:WALKFORWARD_FULL_STATS_START -->"
WALKFORWARD_FULL_STATS_MARKER_END = "<!-- AQ:WALKFORWARD_FULL_STATS_END -->"

OTHER_METRICS_MARKER_START = "<!-- AQ:OTHER_METRICS_START -->"
OTHER_METRICS_MARKER_END = "<!-- AQ:OTHER_METRICS_END -->"

_MODEL_KINDS = ("sequence", "multitask")


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _fmt(value: object, spec: str = "") -> str:
    """Formats a number with `spec`, or returns an em-dash for
    None/missing - every table cell in this module goes through this so a
    partial `aq evaluate` run degrades to a clean placeholder, never a
    KeyError/TypeError."""
    if value is None:
        return "—"
    try:
        return format(value, spec) if spec else str(value)
    except (ValueError, TypeError):
        return str(value)


def _updated_at() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# --------------------------------------------------------------------------
# Offline Evaluation
# --------------------------------------------------------------------------


def load_offline_evaluation_summary() -> dict[str, dict | None]:
    """Per-model rank_book/capacity/stress reports, keyed by model_kind -
    each value is None (not the whole function) when that model has never
    been evaluated, so a report with only a sequence run still renders a
    complete multitask="not yet run" row instead of omitting the section."""
    summary: dict[str, dict | None] = {}
    for model_kind in _MODEL_KINDS:
        rank_book = _load_json(EVALUATION_DIR / f"rank_book_simulation_{model_kind}.json")
        capacity = _load_json(EVALUATION_DIR / f"capacity_report_{model_kind}.json")
        stress = _load_json(EVALUATION_DIR / f"cost_stress_report_{model_kind}.json")
        if rank_book is None and capacity is None and stress is None:
            summary[model_kind] = None
            continue
        summary[model_kind] = {"rank_book": rank_book, "capacity": capacity, "stress": stress}
    return summary


def _build_eval_compact_markdown(summary: dict[str, dict | None]) -> str:
    lines = [
        "| Metric | Multitask | Sequence |",
        "|---|---|---|",
    ]
    row_specs: list[tuple[str, str, str]] = [
        ("Gross Sharpe", "rank_book.gross_sharpe", ".3f"),
        ("Net Sharpe", "rank_book.net_sharpe", ".3f"),
        ("Net total return", "rank_book.net_total_return", ".2%"),
        ("Max drawdown", "rank_book.net_max_drawdown", ".2%"),
        ("Annualized turnover", "rank_book.annualized_turnover", ".2f"),
        ("Cost drag (bps/yr)", "rank_book.cost_drag_annual_bps", ".1f"),
        ("Capacity (USD)", "capacity.capacity_usd", ",.0f"),
    ]
    for label, dotted_path, spec in row_specs:
        section, field = dotted_path.split(".")
        cells = []
        for model_kind in ("multitask", "sequence"):
            model_summary = summary.get(model_kind)
            value = (model_summary.get(section) or {}).get(field) if model_summary else None
            cells.append(_fmt(value, spec))
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")
    body = "\n".join(lines)
    body += f"\n\n_Backtest split, full history. Last updated {_updated_at()} (auto-generated by `aq evaluate --all`)._"
    return body


def _build_eval_full_stats_markdown(summary: dict[str, dict | None]) -> str:
    sections: list[str] = []
    for model_kind in ("multitask", "sequence"):
        model_summary = summary.get(model_kind)
        sections.append(f"**{model_kind.capitalize()} model**")
        if model_summary is None:
            sections.append(f"_Not yet evaluated - run `aq evaluate --all --model {model_kind}`._")
            continue

        rank_book = model_summary.get("rank_book") or {}
        lines = ["| Metric | Value |", "|---|---|"]
        for key in (
            "gross_sharpe", "net_sharpe", "gross_total_return", "net_total_return", "net_max_drawdown",
            "annualized_turnover", "cost_drag_annual_bps", "num_rebalances", "num_dates_used",
            "mean_names_long", "mean_names_short",
        ):
            if key in rank_book:
                lines.append(f"| {key} | {rank_book[key]} |")
        sections.append("\n".join(lines))

        capacity = model_summary.get("capacity")
        if capacity:
            cap_lines = [
                "",
                f"Capacity: ${capacity.get('capacity_usd', 0):,.0f} (binding: {capacity.get('binding_ticker', '—')})",
                "",
                "| top_n | Net Sharpe |",
                "|---|---|",
            ]
            for row in capacity.get("per_top_n", []):
                cap_lines.append(f"| {row.get('top_n')} | {row.get('net_sharpe', 0):.4f} |")
            sections.append("\n".join(cap_lines))

        stress = model_summary.get("stress")
        if stress and stress.get("stress"):
            stress_lines = ["", "| Cost multiplier | Gross Sharpe | Net Sharpe | Cost drag (bps/yr) |", "|---|---|---|---|"]
            for row in stress["stress"]:
                stress_lines.append(
                    f"| {row.get('cost_multiplier')}x | {row.get('gross_sharpe', 0):.4f} | "
                    f"{row.get('net_sharpe', 0):.4f} | {row.get('cost_drag_annual_bps', 0):.1f} |"
                )
            sections.append("\n".join(stress_lines))

    return "\n\n".join(sections)


# --------------------------------------------------------------------------
# Walk-Forward Training/Testing
# --------------------------------------------------------------------------


def load_latest_walk_forward_summary() -> dict | None:
    """Newest ml/versions/walk-forward-*/walk_forward_summary.json by
    mtime - same "latest run" definition as
    monitoring/evaluation_state.py::_latest_walk_forward_summary()."""
    if not VERSIONS_DIR.exists():
        return None
    candidates = sorted(
        VERSIONS_DIR.glob("walk-forward-*/walk_forward_summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return _load_json(candidates[0]) if candidates else None


def _build_walk_forward_compact_markdown(summary: dict | None) -> str:
    if summary is None:
        return "_No walk-forward run found yet - run `aq train --walk-forward` first._"

    run_id = summary.get("run_id", "unknown")
    num_windows = summary.get("num_windows", 0)
    stability = summary.get("stability_by_metric") or {}
    net_perf = summary.get("net_performance_by_window") or []

    lines = ["| Metric | Mean | 95% CI | Stable? |", "|---|---|---|---|"]
    for metric_name in ("backtest_mcc", "rank_5d_ic", "rank_20d_ic", "residual_rank_20d_ic"):
        stats = stability.get(metric_name)
        if not stats:
            continue
        bootstrap = stats.get("bootstrap", {})
        stable_label = "yes" if stats.get("stable") else "**NO**"
        lines.append(
            f"| {metric_name} | {_fmt(stats.get('mean'), '.4f')} | "
            f"[{_fmt(bootstrap.get('lower_bound'), '.4f')}, {_fmt(bootstrap.get('upper_bound'), '.4f')}] | "
            f"{stable_label} |"
        )

    if net_perf:
        net_sharpes = [w.get("simulation", {}).get("net_sharpe") for w in net_perf if w.get("simulation")]
        net_sharpes = [s for s in net_sharpes if s is not None]
        if net_sharpes:
            mean_sharpe = sum(net_sharpes) / len(net_sharpes)
            num_positive = sum(1 for s in net_sharpes if s > 0)
            lines.append(
                f"| net_sharpe (per-window) | {mean_sharpe:.3f} | — | "
                f"{num_positive}/{len(net_sharpes)} windows positive |"
            )

    body = "\n".join(lines)
    body += (
        f"\n\n{num_windows} expanding/rolling windows, run `{run_id}`. "
        f"Last updated {_updated_at()} (auto-generated by `aq train --walk-forward`)."
    )
    return body


def _build_walk_forward_full_stats_markdown(summary: dict | None) -> str:
    if summary is None:
        return "_No walk-forward run found yet._"

    window_results = summary.get("window_results") or []
    net_perf_by_window = {w.get("window_index"): w for w in (summary.get("net_performance_by_window") or [])}

    lines = [
        "| Window | Backtest period | Model | Backtest MCC | Gross Sharpe | Net Sharpe | Net return | Max DD | Turnover |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for index, window in enumerate(window_results):
        backtest_window = window.get("window", {}).get("backtest", {})
        period = f"{backtest_window.get('start', '?')} → {backtest_window.get('end', '?')}"
        net_perf = net_perf_by_window.get(index, {})
        sim = net_perf.get("simulation", {})
        lines.append(
            f"| {index} | {period} | {net_perf.get('model_kind', '—')} | "
            f"{_fmt(window.get('backtest_mcc'), '.4f')} | {_fmt(sim.get('gross_sharpe'), '.3f')} | "
            f"{_fmt(sim.get('net_sharpe'), '.3f')} | {_fmt(sim.get('net_total_return'), '.2%')} | "
            f"{_fmt(sim.get('net_max_drawdown'), '.2%')} | {_fmt(sim.get('annualized_turnover'), '.2f')}x |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Other Metrics (Lean vs. offline comparison, reconciliation, kill-switch)
# --------------------------------------------------------------------------


def _load_lean_sharpe() -> tuple[float | None, str | None]:
    """Returns (sharpe, backtest_window_label) from the same latest
    complete Lean run generate_backtest_report.py's own Lean Backtest
    section displays - never a different/staler run, so the comparison
    below is always apples-to-apples with what's shown just above it."""
    result_json_path = find_latest_backtest_result_json()
    if result_json_path is None:
        return None, None
    lean_summary = load_backtest_summary(result_json_path)
    statistics = lean_summary["statistics"]
    sharpe_str = statistics.get("Sharpe Ratio")
    try:
        sharpe = float(sharpe_str) if sharpe_str is not None else None
    except ValueError:
        sharpe = None
    start_date, end_date = lean_summary["start_date"], lean_summary["end_date"]
    window = f"{start_date.date().isoformat()} to {end_date.date().isoformat()}" if start_date and end_date else None
    return sharpe, window


def _count_real_kill_switch_trips() -> int | None:
    """Counts `kill_switch_tripped` occurrences in the same latest-complete
    run's own Lean log (`<algorithm-id>-log.txt`, sibling to the
    `<algorithm-id>.json` result file `_load_lean_sharpe()` reads) - the
    real-world side of the kill-switch comparison. Returns None (not 0) when
    no log is found, so "never ran" and "ran with zero trips" stay visibly
    different in the rendered table."""
    result_json_path = find_latest_backtest_result_json()
    if result_json_path is None:
        return None
    log_path = result_json_path.with_name(f"{result_json_path.stem}-log.txt")
    if not log_path.exists():
        return None
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return log_text.count("kill_switch_tripped")


def _build_other_metrics_markdown(
    eval_summary: dict[str, dict | None],
    walk_forward_summary: dict | None,
    reconciliation: dict | None,
    kill_switch_replay: dict | None,
) -> str:
    lean_sharpe, lean_window = _load_lean_sharpe()
    sequence_net_sharpe = (eval_summary.get("sequence") or {}).get("rank_book", {}).get("net_sharpe")
    multitask_net_sharpe = (eval_summary.get("multitask") or {}).get("rank_book", {}).get("net_sharpe")
    walk_forward_net_perf = (walk_forward_summary or {}).get("net_performance_by_window") or []
    walk_forward_net_sharpes = [
        w.get("simulation", {}).get("net_sharpe") for w in walk_forward_net_perf if w.get("simulation")
    ]
    walk_forward_net_sharpes = [s for s in walk_forward_net_sharpes if s is not None]
    walk_forward_mean_sharpe = (
        sum(walk_forward_net_sharpes) / len(walk_forward_net_sharpes) if walk_forward_net_sharpes else None
    )

    lines = [
        "**Sharpe: real Lean backtest vs. offline estimates** — offline numbers are consistently more "
        "optimistic than the real backtest; treat the gap itself as the headline number, not either side alone.",
        "",
        "| Source | Sharpe |",
        "|---|---|",
        f"| Real Lean backtest{f' ({lean_window})' if lean_window else ''} | {_fmt(lean_sharpe, '.3f')} |",
        f"| Offline evaluation — sequence model (full backtest split) | {_fmt(sequence_net_sharpe, '.3f')} |",
        f"| Offline evaluation — multitask model (full backtest split) | {_fmt(multitask_net_sharpe, '.3f')} |",
        f"| Walk-forward mean (out-of-sample, per-window) | {_fmt(walk_forward_mean_sharpe, '.3f')} |",
    ]

    if lean_sharpe is not None and sequence_net_sharpe is not None:
        lines.append(f"| Gap: sequence offline − real Lean | {sequence_net_sharpe - lean_sharpe:+.3f} |")
    if lean_sharpe is not None and walk_forward_mean_sharpe is not None:
        lines.append(f"| Gap: walk-forward − real Lean | {walk_forward_mean_sharpe - lean_sharpe:+.3f} |")

    lines.append("")
    lines.append("**Book-history reconciliation** (real Lean selections vs. a fresh offline re-derivation of the same dates)")
    lines.append("")
    if reconciliation and reconciliation.get("summary"):
        recon_summary = reconciliation["summary"]
        lines.extend(
            [
                "| Metric | Value |",
                "|---|---|",
                f"| Dates reconciled | {recon_summary.get('num_dates', '—')} |",
                f"| Exact matches | {recon_summary.get('num_dates_exact_match', '—')} |",
                f"| Mean overlap fraction | {_fmt(recon_summary.get('mean_overlap_fraction'), '.2%')} |",
                f"| Mean raw-score delta | {_fmt(recon_summary.get('mean_raw_score_delta_abs'), '.4f')} |",
                f"| Replay mode | {reconciliation.get('mode', '—')} |",
            ]
        )
        diversion = reconciliation.get("diversion_summary") or {}
        action_counts = diversion.get("action_counts") or {}
        if action_counts:
            total_decisions = sum(action_counts.values())
            lines.append("")
            lines.append(f"Book-member decision outcomes ({total_decisions} total, real Lean run):")
            lines.append("")
            lines.append("| Action | Count | Share |")
            lines.append("|---|---|---|")
            for action, count in sorted(action_counts.items(), key=lambda item: -item[1]):
                lines.append(f"| {action} | {count} | {count / total_decisions:.1%} |")
    else:
        lines.append("_Not yet reconciled - run `aq evaluate --reconcile-book-history --replay-hysteresis` first._")

    lines.append("")
    lines.append("**Kill-switch: real trips vs. offline replay estimate**")
    lines.append("")
    real_trip_count = _count_real_kill_switch_trips()
    has_kill_switch_data = real_trip_count is not None or (kill_switch_replay and kill_switch_replay.get("summary"))
    if has_kill_switch_data:
        lines.append("| Source | Trips | Locked days |")
        lines.append("|---|---|---|")
        lines.append(f"| Real Lean backtest{f' ({lean_window})' if lean_window else ''} | {_fmt(real_trip_count)} | — |")
        if kill_switch_replay and kill_switch_replay.get("summary"):
            ks_summary = kill_switch_replay["summary"]
            lines.append(
                f"| Offline replay (approximation, see Disclaimer) | {ks_summary.get('trip_count', '—')} | "
                f"{_fmt(ks_summary.get('locked_day_fraction'), '.1%')} |"
            )
        else:
            lines.append("| Offline replay | _not yet replayed - run `aq evaluate --replay-kill-switch`_ | — |")
    else:
        lines.append("_Not yet available - run a Lean backtest and `aq evaluate --replay-kill-switch`._")

    lines.append("")
    lines.append(f"_Last updated {_updated_at()} (auto-generated by `aq evaluate`)._")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def update_readme_evaluation_sections(readme_path: Path = README_PATH) -> bool:
    """Idempotently rebuilds Offline Evaluation, Walk-Forward Training/
    Testing, and Other Metrics from whatever currently exists on disk -
    never raises (mirrors generate_backtest_report.py::
    update_readme_backtest_section()'s own contract), so a report-
    generation bug never fails the `aq evaluate`/`aq train` command that
    triggered it. Returns True if the README was actually modified."""
    if not readme_path.exists():
        return False
    text = readme_path.read_text(encoding="utf-8")
    changed = False

    eval_summary = load_offline_evaluation_summary()
    walk_forward_summary = load_latest_walk_forward_summary()
    reconciliation = _load_json(EVALUATION_DIR / "book_history_reconciliation.json")
    kill_switch_replay = _load_json(EVALUATION_DIR / "kill_switch_replay.json")

    updated = _replace_between_markers(text, EVAL_MARKER_START, EVAL_MARKER_END, _build_eval_compact_markdown(eval_summary))
    if updated is not None:
        text, changed = updated, True

    updated = _replace_between_markers(
        text, EVAL_FULL_STATS_MARKER_START, EVAL_FULL_STATS_MARKER_END, _build_eval_full_stats_markdown(eval_summary)
    )
    if updated is not None:
        text, changed = updated, True

    updated = _replace_between_markers(
        text, WALKFORWARD_MARKER_START, WALKFORWARD_MARKER_END, _build_walk_forward_compact_markdown(walk_forward_summary)
    )
    if updated is not None:
        text, changed = updated, True

    updated = _replace_between_markers(
        text,
        WALKFORWARD_FULL_STATS_MARKER_START,
        WALKFORWARD_FULL_STATS_MARKER_END,
        _build_walk_forward_full_stats_markdown(walk_forward_summary),
    )
    if updated is not None:
        text, changed = updated, True

    updated = _replace_between_markers(
        text,
        OTHER_METRICS_MARKER_START,
        OTHER_METRICS_MARKER_END,
        _build_other_metrics_markdown(eval_summary, walk_forward_summary, reconciliation, kill_switch_replay),
    )
    if updated is not None:
        text, changed = updated, True

    if changed:
        _atomic_write(readme_path, text)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate README.md's Offline Evaluation / Walk-Forward / Other Metrics sections."
    )
    parser.add_argument("--readme", type=Path, default=README_PATH)
    args = parser.parse_args()

    updated = update_readme_evaluation_sections(args.readme)
    if updated:
        print(f"Updated {args.readme} with the latest evaluation/walk-forward results.")
        return 0
    print("Nothing to update (no source files found, or README markers missing).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
