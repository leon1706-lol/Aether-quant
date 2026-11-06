"""evaluation/research_cells.py: the gate between selection and the data held out from it."""

from __future__ import annotations

import pandas as pd
import pytest

from evaluation.research_cells import (
    CELLS,
    FREE_CELLS,
    assert_cell_open,
    blank_stale,
    coin_side,
    freeze_digest_of,
    membership_mask,
    name_side,
    names_in_cell,
    window_rows,
    write_freeze,
)


def test_sides_are_stable_and_roughly_balanced():
    names = [f"T{i}" for i in range(2000)]
    sides = [name_side(name) for name in names]
    assert sides == [name_side(name) for name in names]
    assert 0.45 < sides.count("A") / len(sides) < 0.55


def test_share_classes_and_renames_land_on_one_side():
    for first, second in (("GOOG", "GOOGL"), ("FOX", "FOXA"), ("FB", "META"), ("NWS", "NWSA")):
        assert name_side(first) == name_side(second), first


def test_a_name_any_phase_has_read_is_always_side_a():
    # find a name that hashes to B, then make it a project name
    name = next(f"X{i}" for i in range(1000) if name_side(f"X{i}") == "B")
    assert name_side(name, [name]) == "A"
    assert name_side("GOOG", ["GOOGL"]) == "A"


def test_coin_side_ignores_the_quote_currency():
    assert coin_side("LUNAUSD") == coin_side("LUNAUSDT") == coin_side("LUNA")
    coin = next(f"C{i}" for i in range(1000) if coin_side(f"C{i}") == "B")
    assert coin_side(f"{coin}USD", [f"{coin}USD"]) == "A"


def test_names_in_cell_never_mix_sides():
    names = [f"T{i}" for i in range(200)]
    a = set(names_in_cell(CELLS["S"], names, []))
    b = set(names_in_cell(CELLS["V3"], names, []))
    assert a and b and not a & b and a | b == set(names)
    assert set(names_in_cell(CELLS["P"], names, [])) == set(names)


def test_selection_cells_are_free_and_the_rest_need_the_freeze(tmp_path):
    assert FREE_CELLS == {"TA", "S", "SV", "CS"}
    for name in FREE_CELLS:
        assert assert_cell_open(name, None, None).name == name
    for name in ("V1", "V2", "V3", "CV", "P"):
        with pytest.raises(PermissionError):
            assert_cell_open(name, None, None)


def test_a_wrong_digest_or_a_changed_freeze_is_refused(tmp_path):
    path = tmp_path / "freeze.json"
    digest = write_freeze(path, {"candidate": "x"})
    assert assert_cell_open("V3", path, digest).side == "B"
    with pytest.raises(PermissionError):
        assert_cell_open("V3", path, "0" * 64)
    path.write_text("edited")
    with pytest.raises(PermissionError):
        assert_cell_open("V3", path, digest)
    with pytest.raises(PermissionError):
        assert_cell_open("V3", tmp_path / "absent.json", digest)


def test_a_candidate_is_frozen_once(tmp_path):
    path = tmp_path / "freeze.json"
    digest = write_freeze(path, {"a": 1})
    assert freeze_digest_of(path) == digest
    with pytest.raises(FileExistsError):
        write_freeze(path, {"a": 2})


def test_an_unknown_cell_is_an_error():
    with pytest.raises(ValueError):
        assert_cell_open("Z", None, None)


def test_a_selection_cell_cannot_reach_past_its_end():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2018-01-01", "2019-12-31")]
    rows = window_rows(dates, CELLS["S"])
    assert max(rows) <= "2018-12-31"
    assert "2019-01-02" not in rows


def test_warm_up_rows_stop_at_the_requested_count():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2009-01-01", "2012-12-31")]
    rows = window_rows(dates, CELLS["S"], warmup=10)
    assert rows[10] >= "2011-01-01" and rows[9] < "2011-01-01" and len([d for d in rows if d < "2011-01-01"]) == 10


def test_a_name_whose_bars_stopped_loses_its_signal_after_the_stale_limit():
    dates = [f"2020-01-{day:02d}" for day in range(1, 21)]
    closes = pd.DataFrame({"AAA": [1.0] * 10 + [float("nan")] * 10}, index=dates)
    known = closes.ffill()
    out = blank_stale(known, closes, rows=5)
    assert out["AAA"].iloc[12] == 1.0, "a short gap is not a death"
    assert out["AAA"].iloc[-1] != out["AAA"].iloc[-1], "NaN once stale"


def test_blank_stale_reads_only_the_past():
    dates = [f"2020-01-{day:02d}" for day in range(1, 21)]
    closes = pd.DataFrame({"AAA": [1.0] * 20}, index=dates)
    cut = closes.iloc[:10]
    pd.testing.assert_series_equal(blank_stale(closes.ffill(), closes)["AAA"].iloc[:10], blank_stale(cut.ffill(), cut)["AAA"])


def test_membership_mask_follows_the_intervals():
    dates = ["2020-01-01", "2020-06-01", "2021-01-01"]
    mask = membership_mask({"AAA": [("2020-02-01", "2021-01-01")]}, dates, ["AAA", "BBB"])
    assert mask["AAA"].tolist() == [False, True, False] and not mask["BBB"].any()
