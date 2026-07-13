"""Tests for data_pipeline.fred_backfill. urllib.request.urlopen is always
replaced via monkeypatch - zero real network access happens in this file."""

import io
from datetime import date
from unittest.mock import patch

from data_pipeline.fred_backfill import (
    DEFAULT_BOND_REFERENCE_SERIES,
    bond_reference_series,
    cache_csv_to_rows,
    fetch_all_bond_reference_series,
    fetch_fred_series,
    parse_fred_csv,
    rows_to_cache_csv,
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
