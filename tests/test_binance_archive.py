"""data_pipeline/binance_archive.py and scripts/build_crypto_wide_root.py, on fixtures: no network."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_pipeline.binance_archive import (
    base_asset,
    daily_funding,
    list_symbols,
    liquid_universe,
    months_between,
    parse_funding_zip,
    parse_kline_zip,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _page(prefixes: list[str], truncated: bool, marker: str | None = None) -> str:
    entries = "".join(f"<CommonPrefixes><Prefix>data/spot/monthly/klines/{name}/</Prefix></CommonPrefixes>" for name in prefixes)
    next_marker = f"<NextMarker>data/spot/monthly/klines/{marker}/</NextMarker>" if marker else ""
    return (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>{next_marker}{entries}</ListBucketResult>"
    )


def _zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("file.csv", text)
    return buffer.getvalue()


def test_listing_follows_every_page():
    calls = []

    def get_text(url):
        calls.append(url)
        if "marker=" not in url:
            return _page(["AAAUSDT", "BBBUSDT"], True, "BBBUSDT")
        return _page(["CCCUSDT"], False)

    assert list_symbols(get_text) == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    assert len(calls) == 2


@pytest.mark.parametrize("symbol, base", [
    ("BTCUSDT", "BTC"), ("LUNAUSDT", "LUNA"), ("ETHBTC", None), ("USDCUSDT", None), ("BTCUPUSDT", None), ("ETHBEARUSDT", None), ("XRPBULLUSDT", None),
])
def test_base_asset(symbol, base):
    assert base_asset(symbol) == base


def test_klines_read_both_timestamp_units_and_skip_a_header():
    milliseconds = 1609459200000  # 2021-01-01
    microseconds = 1735689600000000  # 2025-01-01
    text = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,tb,tq,ignore\n"
        f"{milliseconds},1,2,0.5,1.5,10,0,15,0,0,0,0\n"
        f"{microseconds},2,3,1,2.5,20,0,50,0,0,0,0\n"
        f"{milliseconds + 86400000},0,0,0,0,0,0,0,0,0,0,0\n"
    )
    rows = parse_kline_zip(_zip(text))
    assert [row["date"] for row in rows] == ["2021-01-01", "2025-01-01"]
    assert rows[0]["close"] == 1.5 and rows[1]["quote_volume"] == 50.0


def test_funding_sums_a_days_settlements():
    day = 1609459200000
    text = f"calc_time,funding_interval_hours,last_funding_rate\n{day},8,0.0001\n{day + 28800000},8,0.0002\n{day + 86400000},8,-0.0003\n"
    assert daily_funding(parse_funding_zip(_zip(text))) == pytest.approx({"2021-01-01": 0.0003, "2021-01-02": -0.0003})


def test_months_between():
    assert months_between("2021-11-15", "2022-02-01") == ["2021-11", "2021-12", "2022-01", "2022-02"]


def test_liquid_universe_reads_only_past_volume():
    dates = pd.date_range("2021-01-01", periods=10).strftime("%Y-%m-%d")
    volume = pd.DataFrame({"AAA": [100.0] * 10, "BBB": [50.0] * 10, "CCC": [1.0] * 10}, index=dates)
    mask = liquid_universe(volume, top_n=2, window=3)
    assert not mask.iloc[:3].any().any(), "a coin needs a full window before the day"
    assert mask.iloc[5].tolist() == [True, True, False]
    # a volume spike on a day doesn't change that day's membership
    spike = volume.copy()
    spike.loc[dates[5], "CCC"] = 1e9
    assert liquid_universe(spike, top_n=2, window=3).iloc[5].tolist() == [True, True, False]
    assert liquid_universe(spike, top_n=2, window=3).iloc[6].tolist() == [True, False, True]


def test_a_coin_that_died_stops_being_liquid():
    dates = pd.date_range("2021-01-01", periods=12).strftime("%Y-%m-%d")
    volume = pd.DataFrame({"LIVE": [10.0] * 12, "DEAD": [100.0] * 5 + [np.nan] * 7}, index=dates)
    mask = liquid_universe(volume, top_n=2, window=3)
    assert not mask["DEAD"].iloc[-1]


def _kline_payload(day_ms: int, count: int = 3) -> bytes:
    lines = [f"{day_ms + i * 86400000},1,2,0.5,1.5,10,0,15,0,0,0,0" for i in range(count)]
    return _zip("\n".join(lines) + "\n")


def _fixture_root(tmp_path):
    from data_pipeline.yfinance_backfill import write_lean_zip

    wide = tmp_path / "wide"
    daily = wide / "equity" / "usa" / "daily"
    daily.mkdir(parents=True)
    import datetime

    for name in ("spy", "agg", "bil"):
        write_lean_zip(daily / f"{name}.zip", name.upper(), [{"date": datetime.date(2021, 1, 4), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}], merge_with_existing=False)
    source = tmp_path / "source"
    (source / "symbol-properties").mkdir(parents=True)
    (source / "symbol-properties" / "symbol-properties-database.csv").write_text(
        "market,symbol,type,description,quote_currency,contract_multiplier,minimum_price_variation,lot_size,market_ticker,minimum_order_size\n"
        "coinbase,BTCUSD,crypto,Bitcoin,USD,1,0.01,0.00000001,BTC-USD,0.00000001\n", encoding="utf-8")
    return wide, source


def test_build_root_writes_lean_zips_keeps_dead_coins_and_resumes(tmp_path):
    import build_crypto_wide_root as module

    wide, source = _fixture_root(tmp_path)
    jan_2021 = 1609459200000
    fetched = []

    def get_bytes(url):
        fetched.append(url)
        if "fundingRate" in url:
            return _zip(f"{jan_2021},8,0.0001\n") if "BTCUSDT-fundingRate-2021-01" in url else None
        if "LUNAUSDT-1d-2021-01" in url or "BTCUSDT-1d-2021-01" in url:
            return _kline_payload(jan_2021)
        return None

    out = tmp_path / "crypto"
    listing = _page(["BTCUSDT", "LUNAUSDT", "USDCUSDT", "ETHBTC"], False)

    def get_text(url):
        if "fundingRate/BTCUSDT" in url:
            return '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Contents><Key>data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2021-01.zip</Key></Contents></ListBucketResult>'
        return listing

    manifest = module.build_root(out, get_text=get_text, get_bytes=get_bytes, source=source, wide_root=wide, start="2021-01-01", end="2021-02-01", pause_seconds=0.0)

    assert set(manifest["coins"]) == {"BTC", "LUNA"}
    assert (out / "crypto" / "coinbase" / "daily" / "lunausd_trade.zip").exists()
    assert (out / "crypto" / "coinbase" / "daily" / "lunausd_quote.zip").exists()
    assert (out / "equity" / "usa" / "daily" / "spy.zip").exists(), "without an equity there are no sessions"
    assert manifest["symbol_properties_added"] == 1
    assert "coinbase,LUNAUSD" in (out / "symbol-properties" / "symbol-properties-database.csv").read_text()
    assert pd.read_parquet(out / "reference" / "funding.parquet")["BTCUSD"].dropna().tolist() == [pytest.approx(0.0001)]
    assert pd.read_parquet(out / "reference" / "quote_volume.parquet")["LUNAUSD"].dropna().iloc[0] == 15.0

    report = module.write_coverage(tmp_path / "coverage.json", manifest)
    assert report["coins"] == 2 and "LUNA" in report["last_bar"]
    assert "close" not in json.dumps(report)

    fetched.clear()
    module.build_root(out, get_text=get_text, get_bytes=get_bytes, source=source, wide_root=wide, start="2021-01-01", end="2021-02-01", pause_seconds=0.0)
    assert fetched == [], "a rerun resumes"


def test_lean_rows_keep_one_bar_per_date():
    import build_crypto_wide_root as module

    rows = [
        {"date": "2021-01-02", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "quote_volume": 1.0},
        {"date": "2021-01-01", "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0, "quote_volume": 2.0},
        {"date": "2021-01-02", "open": 3.0, "high": 3.0, "low": 3.0, "close": 3.0, "volume": 3.0, "quote_volume": 3.0},
    ]
    bars = module.lean_rows(rows)
    assert [bar["date"].isoformat() for bar in bars] == ["2021-01-01", "2021-01-02"]
    assert bars[1]["close"] == 3.0


def test_listed_months_read_keys_and_say_when_there_are_none():
    from data_pipeline.binance_archive import listed_months

    page = (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<Contents><Key>p/X-1d-2021-03.zip</Key></Contents><Contents><Key>p/X-1d-2021-03.zip.CHECKSUM</Key></Contents>"
        "<Contents><Key>p/X-1d-2021-01.zip</Key></Contents></ListBucketResult>"
    )
    assert listed_months(lambda url: page, "p/") == ["2021-01", "2021-03"]
    assert listed_months(lambda url: _page([], False), "p/") is None


def test_fetch_series_keeps_month_order_with_threads():
    from data_pipeline.binance_archive import fetch_series

    rows = fetch_series(lambda symbol, month: month, lambda payload: [payload.decode()], "X", "2021-01-01", "2021-12-31", lambda url: url.encode(), months=["2021-01", "2021-02", "2021-03", "2020-12"])
    assert rows == ["2021-01", "2021-02", "2021-03"], "in order, and only inside the window"


def test_a_price_break_is_found_across_a_gap_and_an_ordinary_move_is_not():
    from data_pipeline.binance_archive import price_breaks

    closes = {"2021-01-20": 0.0003, "2021-01-21": 0.0004, "2021-02-12": 0.7, "2021-02-13": 0.9, "2021-02-14": 0.05}
    found = price_breaks(closes)
    assert [(row["from"], row["to"]) for row in found] == [("2021-01-21", "2021-02-12"), ("2021-02-13", "2021-02-14")]
    assert price_breaks({"2021-01-01": 1.0, "2021-01-02": 3.0, "2021-01-03": float("nan"), "2021-01-04": 1.0}) == []


def test_a_swap_across_a_gap_ends_the_pair_and_a_collapse_without_one_does_not():
    from data_pipeline.binance_archive import truncate_at_swap

    rows = [{"date": date, "close": close} for date, close in (("2021-01-18", 0.0003), ("2021-01-19", 0.0004), ("2021-01-23", 0.5), ("2021-01-24", 0.6))]
    kept, swap = truncate_at_swap(rows)
    assert [row["date"] for row in kept] == ["2021-01-18", "2021-01-19"] and swap["to"] == "2021-01-23"
    crash = [{"date": "2022-05-10", "close": 30.0}, {"date": "2022-05-11", "close": 1.0}, {"date": "2022-05-12", "close": 0.5}]
    assert truncate_at_swap(crash) == (crash, None)


def test_cut_swaps_ends_an_existing_pair_at_its_swap_and_leaves_the_others(tmp_path):
    import json
    import zipfile

    import build_crypto_wide_root as module

    daily = tmp_path / "crypto" / "coinbase" / "daily"
    daily.mkdir(parents=True)

    def write(ticker, rows):
        with zipfile.ZipFile(daily / f"{ticker.lower()}_trade.zip", "w") as archive:
            archive.writestr(f"{ticker.lower()}.csv", "".join(f"{date} 00:00,{close},{close},{close},{close},5\n" for date, close in rows))

    write("SWAPUSD", [("20210118", 0.001), ("20210119", 0.001), ("20210123", 1.0), ("20210124", 1.1)])
    write("PLAINUSD", [("20210118", 2.0), ("20210119", 2.1)])
    coins = {"SWAP": {"ticker": "SWAPUSD", "rows": 4, "last": "2021-01-24"}, "PLAIN": {"ticker": "PLAINUSD", "rows": 2, "last": "2021-01-19", "sha256": "untouched"}}
    (tmp_path / "crypto_wide_manifest.json").write_text(json.dumps({"coins": coins}), encoding="utf-8")

    cut = module.cut_swaps(tmp_path)

    manifest = json.loads((tmp_path / "crypto_wide_manifest.json").read_text(encoding="utf-8"))
    assert set(cut) == {"SWAP"} and set(manifest["cut_at_a_swap"]) == {"SWAP"}
    assert manifest["coins"]["SWAP"]["last"] == "2021-01-19" and manifest["coins"]["SWAP"]["rows"] == 2
    assert manifest["coins"]["PLAIN"]["sha256"] == "untouched"
    with zipfile.ZipFile(daily / "swapusd_trade.zip") as archive:
        assert len(archive.read(archive.namelist()[0]).decode().strip().splitlines()) == 2
    assert (daily / "swapusd_quote.zip").exists()
