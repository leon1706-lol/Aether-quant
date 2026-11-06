"""The model track's rows for one cell: one side's names, as float32 parquet, under data_wide/reference/.

    python scripts/v660_build_panel.py TA --out data_wide/reference/panel_TA.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.wide_context import equity_cell  # noqa: E402
from features.wide_panel import long_frame  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cell")
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze", default=None)
    parser.add_argument("--freeze-digest", default=None)
    args = parser.parse_args(argv)
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cell = equity_cell(ROOT, base, args.cell, freeze_path=Path(args.freeze) if args.freeze else None, freeze_digest=args.freeze_digest)
    frame = long_frame(cell.features, cell.label, cell.sectors, cell.member)
    frame = frame[frame["date"] >= cell.cell.start]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out)
    print(f"{args.cell}: {len(frame)} rows, {frame['ticker'].nunique()} names, {frame['date'].min()}..{frame['date'].max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
