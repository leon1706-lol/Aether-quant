"""Tests for data_pipeline.fred_backfill. urllib.request.urlopen is always
replaced via monkeypatch - zero real network access happens in this file."""

import io
from datetime import date
from unittest.mock import patch

from data_pipeline.fred_backfill import (
    DEFAULT_ALT_DATA_REFERENCE_SERIES,
    DEFAULT_BOND_REFERENCE_SERIES,
    alt_data_reference_series,
    bond_reference_series,
    cache_csv_to_rows,
    fetch_all_bond_reference_series,
    fetch_fred_series,
    parse_fred_csv,
    reference_series,
    rows_to_cache_csv,
    series_change_asof,
    series_value_asof,
    write_fred_series_cache,
)


# ---------------------------------------------------------------------------
# parse_fred_csv
# ---------------------------------------------------------------------------


def test_parse_fred_csv_basic():
    text = "observation_date,DGS10\n2023-01-03,3.79\n2023-01-04,3.71\n"
    rows = parse_fred_csv(text, "DGS10", "2020-01-01", "2030-01-01")
    assert rows == [
        {"date": date(2023, 1, 3), "value": 3.79},
        {"date": date(2023, 1, 4), "value": 3.71},
    ]


def test_parse_fred_csv_drops_dot_missing_values():
    text = "observation_date,DGS10\n2023-01-03,3.79\n2023-01-04,.\n"
    rows = parse_fred_csv(text, "DGS10", "2020-01-01", "2030-01-01")
    assert len(rows) == 1
    assert rows[0]["date"] == date(2023, 1, 3)


def test_parse_fred_csv_drops_empty_string_missing_values():
    text = "observation_date,DGS10\n2023-01-03,3.79\n2023-01-04,\n"
    rows = parse_fred_csv(text, "DGS10", "2020-01-01", "2030-01-01")
    assert len(rows) == 1


def test_parse_fred_csv_clips_to_date_range():
    text = "observation_date,DGS10\n2010-01-01,3.0\n2023-01-03,3.79\n2030-01-01,4.0\n"
    rows = parse_fred_csv(text, "DGS10", "2020-01-01", "2025-01-01")
    assert rows == [{"date": date(2023, 1, 3), "value": 3.79}]


def test_parse_fred_csv_handles_legacy_date_header():
    # FRED's date column header has varied historically ("DATE" vs
    # "observation_date") - parsed positionally, not by hardcoded name.
    text = "DATE,DGS10\n2023-01-03,3.79\n"
    rows = parse_fred_csv(text, "DGS10", "2020-01-01", "2030-01-01")
    assert rows == [{"date": date(2023, 1, 3), "value": 3.79}]


def test_parse_fred_csv_empty_text_returns_empty():
    assert parse_fred_csv("", "DGS10", "2020-01-01", "2030-01-01") == []


def test_parse_fred_csv_skips_malformed_rows_without_raising():
    text = "observation_date,DGS10\nnot-a-date,3.79\n2023-01-04,not-a-number\n2023-01-05,3.71\n"
    rows = parse_fred_csv(text, "DGS10", "2020-01-01", "2030-01-01")
    assert rows == [{"date": date(2023, 1, 5), "value": 3.71}]


# ---------------------------------------------------------------------------
# rows_to_cache_csv / cache_csv_to_rows round trip
# ---------------------------------------------------------------------------


def test_cache_csv_round_trip():
    rows = [{"date": date(2023, 1, 4), "value": 3.71}, {"date": date(2023, 1, 3), "value": 3.79}]
    text = rows_to_cache_csv(rows)
    recovered = cache_csv_to_rows(text)
    assert recovered == [{"date": date(2023, 1, 3), "value": 3.79}, {"date": date(2023, 1, 4), "value": 3.71}]


def test_rows_to_cache_csv_empty():
    assert rows_to_cache_csv([]) == ""


# ---------------------------------------------------------------------------
# fetch_fred_series - urllib.request.urlopen mocked, never real network
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str):
        self._buffer = io.BytesIO(text.encode("utf-8"))

    def read(self):
        return self._buffer.read()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_fred_series_success():
    text = "observation_date,DGS10\n2023-01-03,3.79\n"
    with patch("data_pipeline.fred_backfill.urllib.request.urlopen", return_value=_FakeResponse(text)):
        rows = fetch_fred_series("DGS10", "2020-01-01", "2030-01-01")
    assert rows == [{"date": date(2023, 1, 3), "value": 3.79}]


def test_fetch_fred_series_never_raises_on_network_failure():
    with patch("data_pipeline.fred_backfill.urllib.request.urlopen", side_effect=OSError("connection refused")):
        rows = fetch_fred_series("DGS10", "2020-01-01", "2030-01-01")
    assert rows == []


def test_fetch_fred_series_empty_response_returns_empty():
    with patch("data_pipeline.fred_backfill.urllib.request.urlopen", return_value=_FakeResponse("observation_date,DGS10\n")):
        rows = fetch_fred_series("DGS10", "2020-01-01", "2030-01-01")
    assert rows == []


# ---------------------------------------------------------------------------
# fetch_all_bond_reference_series - one bad series never aborts the others
# ---------------------------------------------------------------------------


def test_fetch_all_bond_reference_series_independent_failure():
    config = {"phase1": {"features": {"bond_reference_series": {"a": "GOOD", "b": "BAD"}}}}

    def _fake_fetch(series_id, start, end):
        if series_id == "BAD":
            raise AssertionError("should be caught inside fetch_fred_series, not propagate here")
        return [{"date": date(2023, 1, 1), "value": 1.0}]

    def _urlopen_side_effect(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        if "BAD" in url:
            raise OSError("simulated failure")
        return _FakeResponse("observation_date,GOOD\n2023-01-01,1.0\n")

    with patch("data_pipeline.fred_backfill.urllib.request.urlopen", side_effect=_urlopen_side_effect):
        result = fetch_all_bond_reference_series(config, "2020-01-01", "2030-01-01")

    assert result["a"] == [{"date": date(2023, 1, 1), "value": 1.0}]
    assert result["b"] == []


# ---------------------------------------------------------------------------
# bond_reference_series - config override with defaults fallback
# ---------------------------------------------------------------------------


def test_bond_reference_series_defaults_without_config_override():
    assert bond_reference_series({}) == DEFAULT_BOND_REFERENCE_SERIES


def test_bond_reference_series_config_override_merges():
    config = {"phase1": {"features": {"bond_reference_series": {"treasury_10yr": "CUSTOM10"}}}}
    result = bond_reference_series(config)
    assert result["treasury_10yr"] == "CUSTOM10"
    assert result["treasury_2yr"] == DEFAULT_BOND_REFERENCE_SERIES["treasury_2yr"]


# ---------------------------------------------------------------------------
# write_fred_series_cache / load_cached_fred_series round trip
# ---------------------------------------------------------------------------


def test_write_fred_series_cache_and_load_round_trip(tmp_path):
    from data_pipeline.fred_backfill import load_cached_fred_series

    rows = [{"date": date(2023, 1, 3), "value": 3.79}]
    write_fred_series_cache(tmp_path, "treasury_10yr", rows)
    loaded = load_cached_fred_series(tmp_path)
    assert loaded["treasury_10yr"] == rows


def test_load_cached_fred_series_missing_directory_returns_empty(tmp_path):
    from data_pipeline.fred_backfill import load_cached_fred_series

    loaded = load_cached_fred_series(tmp_path / "does_not_exist")
    assert loaded == {}


# ---------------------------------------------------------------------------
# alt_data_reference_series / reference_series (development/Problems.md #71)
# ---------------------------------------------------------------------------


def test_alt_data_reference_series_defaults_without_config_override():
    assert alt_data_reference_series({}) == DEFAULT_ALT_DATA_REFERENCE_SERIES


def test_alt_data_reference_series_config_override_merges():
    config = {"phase1": {"features": {"alt_data_reference_series": {"implied_volatility_vix": "CUSTOMVIX"}}}}
    result = alt_data_reference_series(config)
    assert result["implied_volatility_vix"] == "CUSTOMVIX"
    assert result["financial_conditions_nfci"] == DEFAULT_ALT_DATA_REFERENCE_SERIES["financial_conditions_nfci"]


def test_reference_series_group_bond_alt_all():
    config = {}
    assert reference_series(config, "bond") == DEFAULT_BOND_REFERENCE_SERIES
    assert reference_series(config, "alt") == DEFAULT_ALT_DATA_REFERENCE_SERIES
    merged = reference_series(config, "all")
    assert merged == {**DEFAULT_BOND_REFERENCE_SERIES, **DEFAULT_ALT_DATA_REFERENCE_SERIES}


def test_bond_reference_series_unchanged_by_alt_addition():
    # Explicit regression guard: adding alt_data_reference_series()/
    # reference_series() must not have touched bond_reference_series()'s
    # own behavior at all.
    assert bond_reference_series({}) == DEFAULT_BOND_REFERENCE_SERIES


# ---------------------------------------------------------------------------
# V5.1 Phase 2 (item 8 / F2) - the 3 new cross-asset sensitivity driver
# series (features/cross_asset_sensitivity.py)
# ---------------------------------------------------------------------------


def test_default_alt_data_reference_series_includes_the_3_sensitivity_drivers():
    assert DEFAULT_ALT_DATA_REFERENCE_SERIES["treasury_10yr_real"] == "DFII10"
    assert DEFAULT_ALT_DATA_REFERENCE_SERIES["breakeven_inflation_10y"] == "T10YIE"
    assert DEFAULT_ALT_DATA_REFERENCE_SERIES["dollar_index"] == "DTWEXBGS"


def test_alt_data_publication_lag_days_includes_the_3_sensitivity_drivers():
    from data_pipeline.fred_backfill import ALT_DATA_PUBLICATION_LAG_DAYS

    assert ALT_DATA_PUBLICATION_LAG_DAYS["treasury_10yr_real"] == 0
    assert ALT_DATA_PUBLICATION_LAG_DAYS["breakeven_inflation_10y"] == 0
    # DTWEXBGS is a Federal Reserve Board H.10 release, published the
    # following business day - NOT a same-day mark like the Treasury-desk
    # series above.
    assert ALT_DATA_PUBLICATION_LAG_DAYS["dollar_index"] == 1


# ---------------------------------------------------------------------------
# series_value_asof / series_change_asof (development/Problems.md #71 -
# the shared, publication-lag-aware lookup train.py and main.py BOTH use,
# so the lookahead rule cannot drift between them)
# ---------------------------------------------------------------------------


def _rows(*pairs):
    return [{"date": date(*d), "value": v} for d, v in pairs]


def test_series_value_asof_zero_lag_matches_existing_bisect_behavior():
    rows = _rows(((2023, 1, 2), 3.5), ((2023, 1, 3), 3.6), ((2023, 1, 5), 3.8))
    # Same-day observation is used (no lag).
    assert series_value_asof(rows, date(2023, 1, 3), publication_lag_days=0) == 3.6
    # Between observations - most recent prior value.
    assert series_value_asof(rows, date(2023, 1, 4), publication_lag_days=0) == 3.6
    # Before any observation.
    assert series_value_asof(rows, date(2023, 1, 1), publication_lag_days=0) is None


def test_series_value_asof_publication_lag_excludes_unpublished_observation():
    # NFCI-shaped: a Friday-dated observation not usable until 7 days later.
    rows = _rows(((2020, 3, 20), 0.5))
    # Same day as the observation's own date - NOT yet published (lag 7).
    assert series_value_asof(rows, date(2020, 3, 20), publication_lag_days=7) is None
    # One day before the full lag elapses - still not published.
    assert series_value_asof(rows, date(2020, 3, 26), publication_lag_days=7) is None
    # Lag fully elapsed - now visible.
    assert series_value_asof(rows, date(2020, 3, 27), publication_lag_days=7) == 0.5


def test_series_value_asof_empty_rows_returns_none():
    assert series_value_asof([], date(2020, 1, 1)) is None


def test_series_change_asof_insufficient_history_returns_none():
    rows = _rows(((2020, 1, 3), 1.0), ((2020, 1, 10), 1.5))
    # Only 2 observations exist - periods_back=4 needs 5.
    assert series_change_asof(rows, date(2020, 1, 20), publication_lag_days=0, periods_back=4) is None


def test_series_change_asof_matches_hand_computation():
    rows = _rows(
        ((2020, 1, 3), 0.10),
        ((2020, 1, 10), 0.20),
        ((2020, 1, 17), 0.30),
        ((2020, 1, 24), 0.40),
        ((2020, 1, 31), 0.90),
    )
    # As-of 2020-02-01, most recent = 0.90 (2020-01-31), 4 back = 0.10 (2020-01-03).
    change = series_change_asof(rows, date(2020, 2, 1), publication_lag_days=0, periods_back=4)
    assert change == 0.90 - 0.10


def test_series_change_asof_respects_publication_lag():
    rows = _rows(
        ((2020, 1, 3), 0.10),
        ((2020, 1, 10), 0.20),
        ((2020, 1, 17), 0.30),
        ((2020, 1, 24), 0.40),
        ((2020, 1, 31), 0.90),
    )
    # A 7-day lag pushes the effective date back before 2020-01-31 was
    # published, so only the 4 earlier observations (2020-01-03..01-24)
    # are usable - computing a 4-periods-back change needs a 5th
    # (index -1, out of range), so this must return None, not silently
    # substitute the unpublished 2020-01-31 value.
    change = series_change_asof(rows, date(2020, 2, 1), publication_lag_days=7, periods_back=4)
    assert change is None


def test_series_change_asof_empty_rows_returns_none():
    assert series_change_asof([], date(2020, 1, 1)) is None
