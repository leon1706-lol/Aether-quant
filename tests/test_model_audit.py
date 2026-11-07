"""evaluation/model_audit.py: fixed groups, exact coverage, free cells only."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from evaluation.model_audit import COVERAGE_FIELDS, FEATURE_GROUPS, HORIZONS, audit_trial_ids, feature_group_ic, fundamental_coverage, group_table
from evaluation.research_cells import CELLS
from features.wide_panel import INFO_FEATURES, PRICE_FEATURES

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2011-01-03", periods=60)]
TICKERS = ["AAA", "BBB", "CCC", "DDD"]


def test_every_group_name_is_a_real_feature():
    known = set(PRICE_FEATURES) | set(INFO_FEATURES)
    for features in FEATURE_GROUPS.values():
        assert set(features) <= known


def test_there_are_eighteen_looks_to_count():
    ids = audit_trial_ids()
    assert len(ids) == 18 == len(set(ids)) == len(FEATURE_GROUPS) * len(HORIZONS)


def test_group_table_applies_the_published_sign_and_the_membership():
    table = pd.DataFrame(np.arange(240.0).reshape(60, 4), index=DATES, columns=TICKERS)
    member = pd.DataFrame(True, index=DATES, columns=TICKERS)
    member["DDD"] = False
    out = group_table({"accruals": table}, "fundamental_level", member)
    assert out["DDD"].isna().all()
    assert out.loc[DATES[0], "AAA"] > out.loc[DATES[0], "CCC"], "low accruals rank high"


def test_group_with_no_feature_here_is_none():
    assert group_table({}, "liquidity") is None


def test_coverage_counts_member_rows_only():
    table = pd.DataFrame(1.0, index=DATES, columns=TICKERS)
    table["AAA"] = np.nan
    member = pd.DataFrame(True, index=DATES, columns=TICKERS)
    member["DDD"] = False
    report = fundamental_coverage({"accruals": table, "not_a_field": table}, member)
    assert set(report) == {"accruals"} and set(report) <= set(COVERAGE_FIELDS)
    assert report["accruals"]["2011"] == pytest.approx(2.0 / 3.0, abs=1e-3)


@dataclass
class _Cell:
    cell: object
    features: dict
    member: pd.DataFrame | None
    label: pd.DataFrame | None
    bars: object = None
    sectors: dict | None = None


def test_ic_runs_on_a_free_cell_and_passes_each_horizon_on():
    table = pd.DataFrame(np.random.default_rng(1).normal(size=(60, 4)), index=DATES, columns=TICKERS)
    seen = []

    def fake_ic(score, label, *, start, end, horizon, min_names):
        seen.append(horizon)
        return {"mean_ic": 0.0}

    cell = _Cell(CELLS["S"], {"accruals": table}, None, table)
    report = feature_group_ic(cell, horizons=(21,), ic_fn=fake_ic)
    assert report["fundamental_level"]["21"] == {"mean_ic": 0.0}
    assert report["liquidity"] == {"21": None}
    assert seen == [21]


@pytest.mark.parametrize("name", ["V1", "V2", "V3", "P", "CV"])
def test_a_held_out_cell_is_refused(name):
    with pytest.raises(PermissionError):
        feature_group_ic(_Cell(CELLS[name], {}, None, None))
