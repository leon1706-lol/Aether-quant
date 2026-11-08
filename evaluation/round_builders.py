"""Table builders a research round's rule file can name (V6.6.4): `"builder": "low_vol", "params": {...}` instead of a recipe over stored features.

Each builder is a pure function of the cell (its prices, its membership mask, the features the cell holds, and the reference files under its data root) and returns a session x name
table, higher is better. The set is closed: a round names a builder from `BUILDERS`, and a name that isn't there is an error, so a rule file can't reach code by name. A builder whose
input file is absent raises `MissingInput`, which the runner reads as "this trial did not run" (it still counts in N).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pandas as pd

from portfolio import crypto_signals, filing_signals


class MissingInput(FileNotFoundError):
    """A builder's input isn't on this host."""


def _reference_rows(cell, name: str) -> pd.DataFrame:
    if cell.root is None:
        raise MissingInput("this cell was built without a data root")
    path = Path(cell.root) / str(cell.data_dir) / "reference" / name
    if not path.exists():
        raise MissingInput(f"{path} is not here (build it with scripts/build_filing_signals.py)")
    return pd.read_csv(path, dtype=str)


def _known(cell) -> pd.DataFrame:
    return cell.context.panel.known


def _feature(cell, name: str) -> pd.DataFrame:
    if name not in cell.features:
        raise MissingInput(f"the cell holds no {name!r} feature")
    return cell.features[name]


def _fundamentals(cell) -> pd.DataFrame:
    frames = [_reference_rows(cell, "edgar_fundamentals.csv.gz"), _reference_rows(cell, "edgar_fundamentals_ext.csv.gz")]
    return pd.concat(frames, ignore_index=True)


def _fred_known(cell) -> pd.DataFrame:
    """The 10-year, 3-month and Baa-spread series from the cell's own root, as a session knows them (one session late)."""
    from data_pipeline.fred_backfill import load_cached_fred_series
    from portfolio.premia_signals import fred_series_table

    if cell.root is None:
        raise MissingInput("this cell was built without a data root")
    directory = Path(cell.root) / str(cell.data_dir) / "reference" / "fred_series"
    if not directory.exists():
        raise MissingInput(f"{directory} is not here")
    keys = ("treasury_10yr", "treasury_3mo", "credit_spread_baa10y")
    return filing_signals.fred_as_known(fred_series_table(load_cached_fred_series(directory), keys), _known(cell).index, keys=keys)


BUILDERS: dict[str, Callable[[object, Mapping], pd.DataFrame]] = {
    "low_vol": lambda cell, p: crypto_signals.low_vol(_known(cell), **p),
    "lottery_max": lambda cell, p: crypto_signals.lottery_max(_known(cell), **p),
    "amihud": lambda cell, p: crypto_signals.amihud(_known(cell), _feature(cell, "quote_volume"), **p),
    "volume_trend": lambda cell, p: crypto_signals.volume_trend(_feature(cell, "quote_volume").reindex(columns=_known(cell).columns), **p),
    "high_proximity": lambda cell, p: crypto_signals.high_proximity(_known(cell), **p),
    "short_reversal": lambda cell, p: crypto_signals.short_reversal(_known(cell), **p),
    "low_beta": lambda cell, p: crypto_signals.low_beta(_known(cell), **p),
    "idio_vol": lambda cell, p: crypto_signals.idio_vol(_known(cell), **p),
    "trend_votes": lambda cell, p: crypto_signals.trend_votes(_known(cell), **p),
    "funding_filtered_trend": lambda cell, p: crypto_signals.funding_filtered_trend(_known(cell), cell.features.get("funding"), **p),
    "breadth_timing": lambda cell, p: crypto_signals.breadth_timing(_known(cell), _feature(cell, "liquid"), **p),
    "core_constant": lambda cell, p: crypto_signals.core_constant(_known(cell), **p),
    "similarity_table": lambda cell, p: filing_signals.similarity_table(_reference_rows(cell, "filing_similarity.csv.gz").assign(similarity=lambda f: f["similarity"].astype(float)), _known(cell).index, _known(cell).columns, **p),
    "announcement_proximity": lambda cell, p: filing_signals.announcement_proximity(_reference_rows(cell, "earnings_dates.csv.gz"), _known(cell).index, _known(cell).columns, **p),
    "announcement_return": lambda cell, p: filing_signals.announcement_return(_reference_rows(cell, "earnings_dates.csv.gz"), _known(cell), **p),
    "same_month_seasonality": lambda cell, p: filing_signals.same_month_seasonality(_known(cell), **p),
    "opportunistic_buying": lambda cell, p: filing_signals.opportunistic_buying(_reference_rows(cell, "insider_trades.csv.gz"), _known(cell).index, _known(cell).columns, **p),
    "cash_profitability": lambda cell, p: filing_signals.cash_profitability(_fundamentals(cell).assign(value=lambda f: f["value"].astype(float)), _known(cell).index, _known(cell).columns, **p),
    "term_credit_timing": lambda cell, p: filing_signals.term_credit_timing(_fred_known(cell), _known(cell), **p),
    "cross_asset_trend": lambda cell, p: filing_signals.cross_asset_trend(_known(cell), **p),
}


def build_trial_table(builder: str, params: Mapping | None, cell) -> pd.DataFrame:
    """One builder's table on this cell. `cross_asset_trend` takes its `tickers` from the params."""
    if builder not in BUILDERS:
        raise KeyError(f"unknown builder {builder!r}; expected one of {sorted(BUILDERS)}")
    arguments = dict(params or {})
    if builder == "cross_asset_trend" and "tickers" in arguments:
        arguments["tickers"] = tuple(arguments["tickers"])
    return BUILDERS[builder](cell, arguments)


def apply_gate(table: pd.DataFrame, gate: str | None, cell) -> pd.DataFrame:
    """An optional gate on the finished table. `regime`: no signal while BTC is below its 120-session average."""
    if not gate:
        return table
    if gate == "regime":
        return crypto_signals.regime_gate(table, _known(cell))
    raise KeyError(f"unknown gate {gate!r}")
