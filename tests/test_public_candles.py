"""data_pipeline/public_candles.py and the bundled sample (V6.6.5, #343)."""

from __future__ import annotations

import hashlib
import math
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_pipeline.public_candles import bars_to_panel, candle_windows, candles_url, coinbase_product, fetch_daily_bars, parse_candles

ROOT = Path(__file__).resolve().parents[1]


def _stamp(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def _rows(start: date, end: date, price: float = 100.0) -> list[list[float]]:
    rows, day = [], end
    while day >= start:  # newest first, as Coinbase returns them
        rows.append([_stamp(day), price - 1, price + 1, price, price + 0.5, 10.0])
        day -= timedelta(days=1)
    return rows


def test_product_names():
    assert coinbase_product("BTCUSD") == "BTC-USD"
    assert coinbase_product("dogeusd") == "DOGE-USD"
    assert coinbase_product("ETH-USD") == "ETH-USD"


def test_windows_cover_the_range_without_overlap_or_gaps():
    windows = candle_windows(date(2021, 1, 1), date(2023, 6, 30))
    assert windows[0][0] == date(2021, 1, 1) and windows[-1][1] == date(2023, 6, 30)
    for (_, stop), (start, _) in zip(windows, windows[1:]):
        assert start == stop + timedelta(days=1)
    assert all((stop - start).days + 1 <= 299 for start, stop in windows)
    assert candle_windows(date(2022, 1, 2), date(2022, 1, 1)) == []


def test_url_is_iso_and_inclusive():
    url = candles_url("BTC-USD", date(2024, 1, 1), date(2024, 2, 1))
    assert "products/BTC-USD/candles" in url and "start=2024-01-01T00:00:00Z" in url and "end=2024-02-01T23:59:59Z" in url


def test_parse_drops_malformed_non_finite_and_duplicate_rows_and_sorts():
    day = date(2024, 3, 1)
    rows = [
        [_stamp(day + timedelta(days=1)), 1, 2, 1.5, 1.8, 5],
        [_stamp(day), 1, 2, 1.5, 1.7, 5],
        [_stamp(day), 1, 2, 1.5, 9.9, 5],  # duplicate date: the first kept
        [_stamp(day + timedelta(days=2)), 1, 2, float("nan"), 1.8, 5],
        [_stamp(day + timedelta(days=3)), 1, 2, float("inf"), 1.8, 5],
        [_stamp(day + timedelta(days=4)), 1, 2, -1.0, 1.8, 5],
        ["x", 1, 2, 3, 4, 5],
        [1, 2],
        "junk",
    ]
    frame = parse_candles(rows)
    assert list(frame["date"]) == ["2024-03-01", "2024-03-02"]
    assert frame.loc[0, "close"] == 1.7
    assert parse_candles({"message": "NotFound"}).empty


def test_fetch_pages_never_keeps_today_and_names_a_failed_coin(tmp_path):
    calls: list[str] = []
    today = date(2024, 12, 31)

    def get_json(url: str):
        calls.append(url)
        if "BAD-USD" in url:
            raise ConnectionError("delisted")
        return _rows(date(2024, 1, 1), today)  # the server would include today's forming bar

    bars, failed = fetch_daily_bars(["BTCUSD", "BADUSD"], date(2024, 1, 1), today, get_json=get_json, cache_dir=tmp_path, today=today)
    assert failed == ["BADUSD"]
    assert bars["BTCUSD"]["date"].max() == "2024-12-30"
    assert bars["BTCUSD"]["date"].min() == "2024-01-01"
    assert bars["BTCUSD"]["date"].is_unique
    assert sum("BTC-USD" in url for url in calls) == len(candle_windows(date(2024, 1, 1), date(2024, 12, 30)))


def test_a_cache_hit_makes_no_call(tmp_path):
    today = date(2024, 6, 30)
    fetch_daily_bars(["ETHUSD"], date(2024, 1, 1), today, get_json=lambda url: _rows(date(2024, 1, 1), today), cache_dir=tmp_path, today=today)

    def refuse(url: str):
        raise AssertionError("cache should have served this")

    bars, failed = fetch_daily_bars(["ETHUSD"], date(2024, 2, 1), date(2024, 6, 1), get_json=refuse, cache_dir=tmp_path, today=today)
    assert not failed and bars["ETHUSD"]["date"].min() == "2024-02-01" and bars["ETHUSD"]["date"].max() == "2024-06-01"


def test_a_cache_for_a_later_start_is_not_reused(tmp_path):
    today = date(2024, 6, 30)
    fetch_daily_bars(["ETHUSD"], date(2024, 3, 1), today, get_json=lambda url: _rows(date(2024, 3, 1), today), cache_dir=tmp_path, today=today)
    calls: list[str] = []
    fetch_daily_bars(["ETHUSD"], date(2024, 1, 1), today, get_json=lambda url: calls.append(url) or _rows(date(2024, 1, 1), today), cache_dir=tmp_path, today=today)
    assert calls


def test_an_empty_answer_is_a_failure_not_an_empty_series(tmp_path):
    bars, failed = fetch_daily_bars(["NEWUSD"], date(2024, 1, 1), date(2024, 2, 1), get_json=lambda url: [], cache_dir=None, today=date(2024, 3, 1))
    assert failed == ["NEWUSD"] and not bars


def test_panel_aligns_coins_on_dates():
    bars = {"A": parse_candles(_rows(date(2024, 1, 1), date(2024, 1, 3))), "B": parse_candles(_rows(date(2024, 1, 2), date(2024, 1, 3)))}
    panel = bars_to_panel(bars, "close")
    assert list(panel.index) == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert math.isnan(panel.loc["2024-01-01", "B"])
    with pytest.raises(ValueError):
        bars_to_panel(bars, "vwap")


def test_the_bundled_sample_matches_its_readme_and_loads():
    from aether_quant import samples

    digest = hashlib.sha256(samples.SAMPLE_PATH.read_bytes()).hexdigest()
    assert f"`{digest}`" in samples.SAMPLE_README.read_text(encoding="utf-8")
    closes, opens = samples.load_sample_prices(), samples.load_sample_prices("open")
    assert closes.shape == opens.shape and closes.shape[1] == 11
    assert closes.index.min() == "2021-06-01" and closes.index.max() == "2026-10-31"
    values = closes.to_numpy(dtype=float).ravel()
    finite = values[np.isfinite(values)]  # NaN before a coin's first bar; DataFrame.stack treats NaN differently in pandas 2 and 3
    assert finite.size > 0.9 * values.size and (finite > 0).all()
    assert samples.sample_info()["sha256"] == digest
    assert isinstance(samples.load_sample_bars(), pd.DataFrame)
    with pytest.raises(ValueError):
        samples.load_sample_prices("volume")  # type: ignore[arg-type]


def test_the_sample_check_script_agrees():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_hello_sample.py"), "--check"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
