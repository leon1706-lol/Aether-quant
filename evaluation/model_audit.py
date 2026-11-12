"""What the models could know (V6.6.1): rank IC of six fixed feature groups at three horizons, and how much fundamental data each year holds.

These 18 looks read cell S, so each counts in N: a report that informs a round is a look at its data. Groups are equal-weight rank means with the
sign published work gives each feature, so there is nothing to fit, and a single feature's IC is never shown.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from evaluation.research_cells import CELLS, FREE_CELLS
from features.wide_panel import wide_label
from portfolio.wide_signals import rank_mean
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from evaluation.wide_context import WideCell

# name: sign, higher is better after the sign. `resrev_5` already holds minus the return.
FEATURE_GROUPS: dict[str, dict[str, float]] = {
    "price_momentum": {"ret_60": 1.0, "ret_120": 1.0, "ret_252": 1.0, "mom_12_1": 1.0, "resmom_60": 1.0, "resmom_252": 1.0, "dist_52w_high": 1.0, "overnight_ret_252": 1.0},
    "price_reversal": {"ret_1": -1.0, "ret_5": -1.0, "ret_20": -1.0, "resrev_5": 1.0, "overnight_ret_20": -1.0, "intraday_ret_20": -1.0},
    "volatility_beta": {"vol_20": -1.0, "vol_60": -1.0, "beta_252": -1.0, "idio_vol_60": -1.0, "max_ret_20": -1.0, "range_20": -1.0},
    "liquidity": {"amihud_20": 1.0, "log_dollar_volume_20": -1.0, "volume_z_20": -1.0},
    "fundamental_level": {"gp_assets": 1.0, "roe": 1.0, "cfo_assets": 1.0, "accruals": -1.0, "leverage": -1.0, "book_to_market": 1.0, "earnings_yield": 1.0},
    "fundamental_growth": {"asset_growth": -1.0, "net_issuance": -1.0, "sue": 1.0, "days_since_filing": -1.0},
}
HORIZONS = (5, 21, 63)
COVERAGE_FIELDS = ("gp_assets", "accruals", "asset_growth", "net_issuance", "book_to_market", "earnings_yield", "leverage", "cfo_assets", "accruals_ttm", "noa", "capex_growth")


def group_table(features: Mapping[str, pd.DataFrame], group: str, member: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """The group's fixed composite, from whichever of its features this cell holds. None if it holds none."""
    present = [features[name] * sign for name, sign in FEATURE_GROUPS[group].items() if name in features]
    if not present:
        return None
    table = rank_mean(present, minimum=1)
    if member is None:
        return table
    return table.where(member.reindex(index=table.index, columns=table.columns, fill_value=False))


def fundamental_coverage(features: Mapping[str, pd.DataFrame], member: pd.DataFrame) -> dict[str, Any]:
    """{field: {year: share of member rows with a value}}, on member rows only. The early years of training windows read this."""
    report: dict[str, dict[str, float]] = {}
    for name in COVERAGE_FIELDS:
        if name not in features:
            continue
        mask = member.reindex(index=features[name].index, columns=features[name].columns, fill_value=False)
        known = features[name].notna() & mask
        years = pd.Index(features[name].index).str[:4]
        report[name] = {
            str(year): round(float(known[years == year].to_numpy().sum() / max(1, mask[years == year].to_numpy().sum())), 4)
            for year in sorted(set(years))
        }
    return report


def feature_group_ic(cell: WideCell, *, horizons: tuple[int, ...] = HORIZONS, ic_fn: Callable[..., Any] | None=None) -> dict[str, Any]:
    """{group: {horizon: mean IC, non-overlapping t, IC by year}} on the cell's own dates. Refuses a cell outside the free ones: this is a report,
    and no freeze stands behind it."""
    if cell.cell.name not in FREE_CELLS or CELLS[cell.cell.name] != cell.cell:
        raise PermissionError(f"the model audit reads free cells only, not {cell.cell.name}")
    if ic_fn is None:
        from evaluation.wide_context import signal_ic_t as ic_fn
    report: dict[str, dict] = {}
    labels = {horizon: (cell.label if horizon == 21 and cell.label is not None else wide_label(cell.bars, cell.sectors, horizon=horizon)) for horizon in horizons}
    for group in FEATURE_GROUPS:
        table = group_table(cell.features, group, cell.member)
        if table is None:
            report[group] = {str(horizon): None for horizon in horizons}
            continue
        report[group] = {
            str(horizon): ic_fn(table, labels[horizon], start=cell.cell.start, end=cell.cell.end, horizon=horizon, min_names=20)
            for horizon in horizons
        }
    return report


def audit_trial_ids() -> list[str]:
    """The 18 looks, as the trial ledger counts them."""
    return [f"audit:{group}:{horizon}" for group in FEATURE_GROUPS for horizon in HORIZONS]
