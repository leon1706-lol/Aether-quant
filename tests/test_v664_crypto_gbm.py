"""scripts/v664_crypto_gbm.py: no look-ahead in the walk-forward ranker, and the same bytes on every run (V6.6.4)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import v664_crypto_gbm as gbm  # noqa: E402

DAYS = [day.strftime("%Y-%m-%d") for day in pd.date_range("2017-06-01", periods=1300)]
COINS = ["BTCUSD", "ETHUSD"] + [f"C{i:02d}USD" for i in range(12)]


def _world(seed: int = 4):
    rng = np.random.default_rng(seed)
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.03, (len(DAYS), len(COINS))), axis=0)), index=DAYS, columns=COINS)
    volume = pd.DataFrame(np.exp(rng.normal(15, 0.4, (len(DAYS), len(COINS)))), index=DAYS, columns=COINS)
    member = pd.DataFrame(True, index=DAYS, columns=COINS)
    c1 = known / known.shift(28) - 1.0
    c2 = known.pct_change(fill_method=None).rolling(60, min_periods=60).sum()
    return known, volume, member, {"c1": c1, "c2": c2}


def _small_model():
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(max_depth=2, max_iter=15, random_state=0)


def test_refits_fall_on_january_and_july_from_2019():
    refits = gbm.refit_dates(pd.Index(DAYS))
    assert refits[0] == "2019-01-01" and refits[1] == "2019-07-01" and all(day[5:7] in ("01", "07") for day in refits)


def test_a_changed_future_label_or_price_changes_no_earlier_score():
    known, volume, member, c_tables = _world()
    features = gbm.feature_tables(known, volume, member, c_tables)
    label = gbm.label_rank(known, member)
    base = gbm.walk_forward(features, label, known.index, fit=_small_model)
    cut = DAYS.index("2020-07-01")  # scores before this refit may not know anything after it
    changed_known = known.copy()
    changed_known.iloc[cut:] *= np.linspace(1.0, 5.0, len(DAYS) - cut)[:, None] * np.random.default_rng(1).uniform(0.5, 2.0, (len(DAYS) - cut, len(COINS)))
    changed_features = gbm.feature_tables(changed_known, volume, member, {"c1": changed_known / changed_known.shift(28) - 1.0, "c2": changed_known.pct_change(fill_method=None).rolling(60, min_periods=60).sum()})
    after = gbm.walk_forward(changed_features, gbm.label_rank(changed_known, member), changed_known.index, fit=_small_model)
    pd.testing.assert_frame_equal(base.iloc[:cut], after.iloc[:cut])
    assert base.iloc[:DAYS.index("2019-01-01")].isna().all().all(), "nothing is scored before the first refit"
    assert base.iloc[DAYS.index("2019-01-01") + 5].notna().any()


def test_training_rows_end_before_their_labels_do():
    known, volume, member, c_tables = _world()
    seen: list[int] = []

    class Recorder:
        def fit(self, x, y):
            seen.append(len(y))
            return self

        def predict(self, x):
            return np.zeros(len(x))

    features = gbm.feature_tables(known, volume, member, c_tables)
    gbm.walk_forward(features, gbm.label_rank(known, member), known.index, fit=Recorder)
    assert seen == sorted(seen) and len(set(seen)) == len(seen) >= 4, "each refit trains on more finished rows than the one before"


def test_two_runs_give_identical_scores():
    known, volume, member, c_tables = _world()
    features = gbm.feature_tables(known, volume, member, c_tables)
    label = gbm.label_rank(known, member)
    first = gbm.walk_forward(features, label, known.index, fit=_small_model)
    second = gbm.walk_forward(features, label, known.index, fit=_small_model)
    pd.testing.assert_frame_equal(first, second)


def test_a_refit_with_no_or_too_little_history_scores_nothing():
    # from 2018-12-25 the first refit has no labelled history at all; from 2018-11-01 it has too few rows to fit
    for start in ("2018-12-25", "2018-11-01"):
        days = [day.strftime("%Y-%m-%d") for day in pd.date_range(start, periods=80)]
        label = pd.DataFrame(0.5, index=days, columns=["A", "B"])
        scores = gbm.walk_forward({"x01": label.copy()}, label, pd.Index(days), fit=_small_model)
        assert scores.isna().all().all(), start


def test_main_scores_cell_cs_and_refuses_any_other(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    import pytest

    import evaluation.wide_context as wide

    known, volume, member, tables = _world()
    cell = SimpleNamespace(cell=SimpleNamespace(name="CS", end=gbm_cells()["CS"].end), context=SimpleNamespace(panel=SimpleNamespace(known=known)),
                           features={"quote_volume": volume}, member=member, tables=tables)
    monkeypatch.setattr(wide, "crypto_cell", lambda root, base, name: cell)
    monkeypatch.setattr(gbm, "feature_tables", lambda known, volume, member, tables: {"x01": known})
    monkeypatch.setattr(gbm, "walk_forward", lambda features, label, index: pd.DataFrame(0.5, index=index, columns=known.columns))
    monkeypatch.setattr(gbm, "OUTPUT", tmp_path / "scores" / "x13.csv")
    assert gbm.main() == 0
    written = pd.read_csv(tmp_path / "scores" / "x13.csv")
    assert list(written.columns) == ["date", "ticker", "score"] and "wrote" in capsys.readouterr().out
    cell.cell.name = "CV"
    with pytest.raises(SystemExit, match="cell CS only"):
        gbm.main()


def gbm_cells():
    from evaluation.research_cells import CELLS

    return CELLS


def test_run_as_a_script_it_stops_at_its_first_read(monkeypatch):
    import pytest

    from script_loader import Stop, run_script, stop_at_first_read

    stop_at_first_read(monkeypatch)
    with pytest.raises(Stop, match="config.json"):
        run_script("v664_crypto_gbm", [], monkeypatch)
