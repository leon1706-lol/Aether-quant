"""Round 2 of V6.6.0's selection (scripts/v660_round2.py): its trial table, its rank-IC breakdown and its guards. The scored runs need the wide data and
are not repeated here."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from v660_round2 import IB_COINS, SENSITIVITY, TRIALS, band_of, ic_by_group, spec_of  # noqa: E402
from v660_trials import PBO_COLUMNS, W  # noqa: E402


def test_every_round_two_trial_builds_from_a_round_one_table_and_never_reuses_a_round_one_id():
    round_one = {spec.id for spec in W}
    for trial, (_, tables, every, top_k, band, why) in TRIALS.items():
        assert trial not in round_one and trial not in PBO_COLUMNS
        assert all(name in round_one for name in tables)
        spec = spec_of(trial)
        assert spec.rebalance_every == every and spec.params["top_k"] == top_k and spec.params["table"] == trial
        assert band_of(trial) == band >= 0.001 and why


def test_the_sensitivity_set_is_round_ones_positive_no_cost_sleeves_and_exists_in_the_trial_list():
    assert set(SENSITIVITY) <= {spec.id for spec in W}


def test_ib_coins_are_the_press_reported_ones_and_exclude_the_four_nobody_listed():
    assert {"BTCUSD", "ETHUSD", "LTCUSD", "BCHUSD"} <= set(IB_COINS)
    assert not {"XLMUSD", "EOSUSD", "ETCUSD", "ZECUSD"} & set(IB_COINS)


def test_rank_ic_by_group_finds_a_signal_where_it_lives_and_none_where_it_does_not():
    rng = np.random.default_rng(3)
    dates = [f"{year}-{month:02d}-01" for year in (2015, 2016) for month in range(1, 13)]
    tickers = [f"T{index:02d}" for index in range(120)]
    label = pd.DataFrame(rng.normal(size=(len(dates), len(tickers))), index=dates, columns=tickers)
    informed = tickers[:60]
    table = pd.DataFrame(rng.normal(size=label.shape), index=dates, columns=tickers)
    table[informed] = label[informed] + 0.2 * rng.normal(size=(len(dates), 60))
    sector = pd.Series(["tech"] * 60 + ["bank"] * 60, index=tickers)

    report = ic_by_group(table, label, {"sector": sector}, start="2015-01-01", end="2016-12-31", step=1)

    assert report["sector"]["tech"]["ic"] > 0.8
    assert abs(report["sector"]["bank"]["ic"]) < 0.2
    assert set(report["year"]) == {"2015", "2016"}


def test_rank_ic_by_group_skips_dates_with_too_few_names():
    dates = ["2015-01-01", "2015-02-01"]
    table = pd.DataFrame(np.arange(10.0).reshape(2, 5), index=dates, columns=list("abcde"))
    assert ic_by_group(table, table, {}, start="2015-01-01", end="2015-12-31", step=1)["year"] == {}


def test_round_two_refuses_to_run_without_its_hashed_rules(tmp_path, monkeypatch):
    import v660_round2

    monkeypatch.setattr(v660_round2, "check_rules", lambda: {})
    monkeypatch.setattr(v660_round2, "RULES_R2", tmp_path / "rules_r2.json")
    monkeypatch.setattr(v660_round2, "RULES_R2_SHA", tmp_path / "rules_r2.sha256")
    (tmp_path / "rules_r2.json").write_text("{}", encoding="utf-8")
    (tmp_path / "rules_r2.sha256").write_text("0" * 64, encoding="utf-8")
    with pytest.raises(SystemExit):
        v660_round2.check_rules_r2()
