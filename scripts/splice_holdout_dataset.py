"""Refresh the holdout rows of `ml/datasets/full_dataset.csv` on the 4 GB dev PC (V6.4.2), instead of the ~8 GB `--full-splits` build.

A data refresh only appends bars (`scripts/data_append_refresh.py`), so every row before the holdout is unchanged and only the
holdout window needs building. `build_holdout_dataset.py` still builds the train and validation rows of its windows config, so
this tool hands it a windows config whose train / validation windows are one month each in 2014-15: the builder then holds
little more than the build window. The build starts a sensitivity lookback (252 rows) plus a month before the splice, because
the `sens_*` betas regress on the rows the builder kept (a build that started in 2025-03 left them at 0.0, which the guard
caught). The new rows replace the old file's rows from `--splice-from` on, streamed line by line.

The overlap guard proves the narrow build equals the full one before anything is written: every old row dated
`--splice-from`..`--compare-until` must exist in the new build with the same features (within 1e-9) and the same labels
(`--compare-until` sits a label horizon before the old data end, so those labels were resolved in both), except the four
`SAMPLE_DEPENDENT_LABELS`, whose whole-history beta moves with any rebuild; the result counts how many of their cells moved. Rows outside the
holdout (`train` / `validation` / `backtest`) are copied verbatim, so the per-split files stay valid and are not rewritten.

    python scripts/splice_holdout_dataset.py --build [--build-start 2024-05-31] [--build-end 2026-10-16]
    python scripts/splice_holdout_dataset.py --splice --splice-from 2025-07-01 --compare-until 2026-08-28
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATASETS = ROOT_DIR / "ml" / "datasets"
DEFAULT_OLD = DATASETS / "full_dataset.csv"
DEFAULT_WINDOW = DATASETS / "v642_holdout_window.csv"
DEFAULT_WINDOWS_CONFIG = ROOT_DIR / "ml" / "evaluation" / "v642" / "splice_windows.json"
KEPT_SPLITS = ("train", "validation", "backtest")
# labels built on ONE whole-history beta per asset (train.build_cross_sectional_rank_targets' beta-neutral block,
# train.build_residual_rank_targets): they move with the build's sample, so no partial build can reproduce them, and a full
# rebuild changes them on every row too. Neither head is on the shipped path (beta-neutral disabled, residual demoted, #226).
SAMPLE_DEPENDENT_LABELS = frozenset({
    "target_beta_neutral_rank_5d", "target_beta_neutral_rank_20d", "target_residual_rank_5d", "target_residual_rank_20d",
})
TOLERANCE = 1e-9
NARROW_TRAINING = {"start": "2014-12-01", "end": "2014-12-31"}
NARROW_VALIDATION = {"start": "2015-01-02", "end": "2015-01-30"}

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def default_build_start(config: dict, splice_from: str) -> str:
    """A build start that leaves every trailing per-row window whole by `splice_from`: the sensitivity betas regress on the
    last `lookback_days` ROWS the builder kept (a narrow build drops 2015..build start), so it needs that many equity sessions
    (~1.45 calendar days each) plus a month before the splice."""
    from datetime import date, timedelta

    sensitivity = config.get("phase1", {}).get("features", {}).get("cross_asset_sensitivity", {}) or {}
    lookback = int(sensitivity.get("lookback_days", 252) or 252)
    return (date.fromisoformat(splice_from) - timedelta(days=int(lookback * 1.45) + 31)).isoformat()


def narrow_windows_config(config: dict, build_start: str, build_end: str) -> dict:
    """A `--windows-config` for build_holdout_dataset.py: tiny train / validation windows, the build window as holdout."""
    windows = dict(config["phase1"]["windows"])
    windows.update(training=dict(NARROW_TRAINING), validation=dict(NARROW_VALIDATION),
                   holdout={"start": build_start, "end": build_end})
    return {"phase1": {"windows": windows}}


def values_equal(old: str, new: str, tolerance: float = TOLERANCE) -> bool:
    """CSV cells equal as text, or as finite numbers within `tolerance`, or both empty / both NaN."""
    if old == new:
        return True
    try:
        a, b = float(old), float(new)
    except ValueError:
        return False
    if math.isnan(a) and math.isnan(b):
        return True
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


def overlap_mismatches(old_rows, new_rows, header: list[str], ignore: set[str], limit: int = 20) -> dict:
    """Merge-join of two (date, ticker)-sorted row streams: {"missing": old keys absent from the new stream, "cells":
    [(key, column, old, new)], "compared": n}. Streams, so the 4 GB PC never holds the overlap in memory."""
    index = [position for position, name in enumerate(header) if name not in ignore]
    date_col, ticker_col = header.index("date"), header.index("ticker")
    missing, cells, compared = [], [], 0
    new_iter = iter(new_rows)
    new = next(new_iter, None)
    for old in old_rows:
        key = (old[date_col], old[ticker_col])
        while new is not None and (new[date_col], new[ticker_col]) < key:
            new = next(new_iter, None)
        compared += 1
        if new is None or (new[date_col], new[ticker_col]) != key:
            missing.append(key)
            continue
        for position in index:
            if len(cells) < limit and not values_equal(old[position], new[position]):
                cells.append((key, header[position], old[position], new[position]))
    return {"missing": missing, "cells": cells, "compared": compared}


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        yield header
        yield from reader


def dated(path: Path, date_from: str, date_to: str, date_col: int):
    """Rows dated date_from..date_to (ISO strings compare as dates) of a date-sorted dataset, streamed."""
    rows = _rows(path)
    next(rows)
    for row in rows:
        if row[date_col] > date_to:
            return
        if row[date_col] >= date_from:
            yield row


def splice(old_path: Path, window_path: Path, out_path: Path, splice_from: str, compare_until: str) -> dict:
    old_iter = _rows(old_path)
    header = next(old_iter)
    window_header = next(_rows(window_path))
    if window_header != header:
        raise ValueError("the window build's columns differ from the old dataset's: rebuild it with the same config")
    date_col, split_col = header.index("date"), header.index("split")

    check = overlap_mismatches(dated(old_path, splice_from, compare_until, date_col),
                               dated(window_path, splice_from, compare_until, date_col), header,
                               ignore={"split", *SAMPLE_DEPENDENT_LABELS})
    if check["missing"] or check["cells"]:
        raise ValueError(f"overlap guard failed ({check['compared']} rows compared): {len(check['missing'])} rows missing, "
                         f"first cell differences {check['cells'][:5]}")
    moved = overlap_mismatches(dated(old_path, splice_from, compare_until, date_col),
                               dated(window_path, splice_from, compare_until, date_col), header,
                               ignore=set(header) - SAMPLE_DEPENDENT_LABELS, limit=10**9)

    tmp_path = out_path.with_suffix(".splice.tmp")
    counts = {"kept": 0, "dropped_old_holdout": 0, "new_holdout": 0}
    try:
        last_new_date = _write_spliced(tmp_path, header, old_iter, window_path, splice_from, date_col, split_col, counts)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    tmp_path.replace(out_path)
    return dict(counts, compared=check["compared"], last_date=last_new_date,
                sample_dependent_cells_moved=len(moved["cells"]))


def _write_spliced(tmp_path: Path, header: list[str], old_iter, window_path: Path, splice_from: str, date_col: int,
                   split_col: int, counts: dict) -> str | None:
    last_new_date = None
    with tmp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in old_iter:
            if row[date_col] < splice_from:
                writer.writerow(row)
                counts["kept"] += 1
            elif row[split_col] in KEPT_SPLITS:
                raise ValueError(f"a {row[split_col]} row dated {row[date_col]} sits after --splice-from; pick an earlier date")
            else:
                counts["dropped_old_holdout"] += 1
        window = _rows(window_path)
        next(window)
        for row in window:
            if row[date_col] >= splice_from and row[split_col] == "backtest":
                row[split_col] = "holdout"
                writer.writerow(row)
                counts["new_holdout"] += 1
                last_new_date = max(last_new_date or row[date_col], row[date_col])
    return last_new_date


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", action="store_true", help="build the holdout window with narrow train / validation windows")
    parser.add_argument("--build-start", default=None,
                        help="default: a sensitivity lookback (252 sessions) plus a month before --splice-from")
    parser.add_argument("--build-end", default=None, help="default: phase1.windows.holdout.end of config.json")
    parser.add_argument("--splice", action="store_true", help="check the overlap, then replace the old holdout rows")
    parser.add_argument("--splice-from", default=None, help="default: phase1.windows.holdout.start of config.json")
    parser.add_argument("--compare-until", default=None, help="last date whose labels both builds resolved")
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--window", type=Path, default=DEFAULT_WINDOW)
    parser.add_argument("--out", type=Path, default=None, help="default: --old (written through a temp file)")
    args = parser.parse_args()
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    holdout = config["phase1"]["windows"]["holdout"]
    splice_from = args.splice_from or holdout["start"]
    if args.build:
        build_start = args.build_start or default_build_start(config, splice_from)
        windows_config = narrow_windows_config(config, build_start, args.build_end or holdout["end"])
        DEFAULT_WINDOWS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_WINDOWS_CONFIG.write_text(json.dumps(windows_config, indent=2), encoding="utf-8")
        command = [sys.executable, str(ROOT_DIR / "scripts" / "build_holdout_dataset.py"), "--windows-config", str(DEFAULT_WINDOWS_CONFIG),
                   "--start", build_start, "--end", args.build_end or holdout["end"], "--output", str(args.window)]
        print(" ".join(command))
        if subprocess.call(command) != 0:
            return 1
    if args.splice:
        if not args.compare_until:
            parser.error("--splice needs --compare-until (a label horizon before the old data end)")
        result = splice(args.old, args.window, args.out or args.old, splice_from, args.compare_until)
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
