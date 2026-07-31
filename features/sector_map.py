"""Ticker -> sector-neutral-ranking bucket (V5.1 Phase 0, Problems.md #75).

Pure, dependency-light, imported by BOTH train.py (torch-bound) and main.py
(the Lean runtime, which cannot import train.py) - the same train/inference
parity convention every other module in features/ follows. This module
existed only inside train.py before V5.1; train.py::load_sector_mapping()
is now a thin delegate to load_sector_mapping() here so both callers share
one implementation instead of main.py duplicating the file-read/strip logic.
"""

from __future__ import annotations

import json
from pathlib import Path

UNKNOWN_SECTOR_LABEL = "Unknown"

# Mirrors train.py::SECTOR_MAPPING_PATH (DATA_DIR / "reference" / "sector_mapping.json") -
# this file lives at <repo_root>/features/sector_map.py, so .parent.parent is <repo_root>.
DEFAULT_SECTOR_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "reference" / "sector_mapping.json"


def load_sector_mapping(config: dict, *, default_path: Path = DEFAULT_SECTOR_MAPPING_PATH) -> dict[str, str]:
    """Ticker -> sector bucket, from the checked-in data/reference/sector_mapping.json
    (or an override path via config phase1.target.ranking.sector_neutral.mapping_path).

    Same defensive posture as every other reference-file loader in this
    codebase: returns {} (never raises) when the file is missing or
    unparseable, so a caller degrades to every ticker resolving to
    UNKNOWN_SECTOR_LABEL rather than crashing over a missing reference file.
    `_`-prefixed keys are comments and are stripped.
    """
    mapping_path_str = (
        config.get("phase1", {}).get("target", {}).get("ranking", {}).get("sector_neutral", {}).get("mapping_path")
    )
    mapping_path = Path(mapping_path_str) if mapping_path_str else default_path
    if not mapping_path.exists():
        return {}

    try:
        raw = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    return {ticker: sector for ticker, sector in raw.items() if not ticker.startswith("_")}


def resolve_sector(ticker: str, sector_by_ticker: dict[str, str]) -> str:
    """sector_by_ticker.get(ticker, UNKNOWN_SECTOR_LABEL) - the one-line
    lookup every caller (book_neutrality.py, rank_book_simulator.py,
    train.py's residual-rank sector dummies) needs, kept in one place so
    the UNKNOWN_SECTOR_LABEL default can never drift between callers."""
    return sector_by_ticker.get(ticker, UNKNOWN_SECTOR_LABEL)
