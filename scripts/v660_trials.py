"""The V6.6.0 trial list: every selectable candidate, fixed before any of them is scored (rules.json carries a copy)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.wide_context import BOND_ETF_CLASS, SECTOR_ETF_CLASS, SECTORS  # noqa: E402
from portfolio.premia_signals import DIRECT, TS, XS, SleeveSpec  # noqa: E402

TOP_K = 5
CRYPTO_TOP_K = 10
WINDOW_BY_TRACK = {"W": "S", "M": "S", "E": "S", "C": "CS"}


def _wide(trial: str, every: int = 20, **params) -> SleeveSpec:
    return SleeveSpec(trial, "W", XS, "external_score", SECTORS, every, {"table": trial, "top_k": TOP_K, **params})


W = [_wide(f"w{number:02d}") for number in range(1, 14)] + [_wide("w14", every=5), _wide("w15")]
WINDOW_OVERRIDES = {"w13": "SV"}
M = [SleeveSpec(trial, "M", XS, "external_score", SECTORS, 20, {"table": trial, "top_k": TOP_K}) for trial in ("m1", "m2", "m3", "m4", "m5")]
C = [
    SleeveSpec("c1", "C", XS, "external_score", ("crypto",), 20, {"table": "c1", "top_k": CRYPTO_TOP_K}),
    SleeveSpec("c2", "C", XS, "external_score", ("crypto",), 20, {"table": "c2", "top_k": CRYPTO_TOP_K}),
    SleeveSpec("c3", "C", XS, "external_score", ("crypto",), 20, {"table": "c3", "top_k": CRYPTO_TOP_K}),
    SleeveSpec("c4", "C", XS, "external_score", ("crypto",), 20, {"table": "c4", "top_k": CRYPTO_TOP_K}),
    SleeveSpec("c5", "C", TS, "external_score", ("crypto",), 5, {"table": "c5"}),
]
E = [
    SleeveSpec("e1", "E", XS, "cross_sectional_return", (SECTOR_ETF_CLASS,), 20, {"lookback": 126}),
    SleeveSpec("e2", "E", XS, "cross_sectional_return", (BOND_ETF_CLASS,), 20, {"lookback": 126}),
    SleeveSpec("e3", "E", DIRECT, "external_score", ("benchmark",), 21, {"table": "e3"}),
]
ALL_SPECS = [*W, *M, *C, *E]
COMBINATION_IDS = ["t1", "t2"]
CRYPTO_CORE = ("BTCUSD", "ETHUSD")
# Time-series and single-asset trials have no cross-section for the rank-IC clause.
NO_IC_CLAUSE = ("c5", "e3")
# The fewest names a sleeve must be able to rank, on its rebalance days, for its score to mean anything.
MIN_LIVE_NAMES = {"W": 150, "M": 150, "C": 12, "E": 5}
# These hold a fixed few names by design.
MIN_LIVE_NAMES_BY_TRIAL = {"c5": 2, "e3": 1}
MIN_IC_NAMES = {"W": 20, "M": 20, "C": 8, "E": 5}
PBO_COLUMNS = (
    "w01", "w02", "w03", "w04", "w05", "w06", "w07", "w08", "w09", "w10", "w11", "w12", "w14", "w15", "m1", "m2", "m3", "m4", "m5", "e1", "e2", "e3",
)


def cell_of(spec: SleeveSpec) -> str:
    return WINDOW_OVERRIDES.get(spec.id, WINDOW_BY_TRACK[spec.track])


def min_live_names(trial: str, track: str) -> int:
    return MIN_LIVE_NAMES_BY_TRIAL.get(trial, MIN_LIVE_NAMES[track])
