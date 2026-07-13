"""Tests for data_pipeline.fetch — the `aq fetch` command's backing module.

Conventions: no test classes, module-level helpers (mirrors
tests/test_yfinance_backfill.py exactly). yfinance is never imported or
called here — fetch_yahoo_ohlcv is always replaced via the fetch_fn
injection point, so zero real network access happens in this file.
"""

import json
from datetime import date
from zipfile import ZipFile

from data_pipeline.fetch import (
    ASSET_CLASSES,
    _crypto_yahoo_symbol,
    add_asset_to_config,
    fetch_adhoc_asset,
)


def _sample_yahoo_rows() -> list[dict]:
    return [
        {"date": date(2023, 1, 1), "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 1000.0},
        {"date": date(2023, 1, 2), "open": 104.0, "high": 108.0, "low": 103.0, "close": 107.0, "volume": 1500.0},
    ]


def _sample_config(existing_assets: list[dict] | None = None) -> dict:
    return {"phase1": {"universe": {"assets": existing_assets or []}}}


# ---------------------------------------------------------------------------
# _crypto_yahoo_symbol
# ---------------------------------------------------------------------------


def test_crypto_yahoo_symbol_strips_trailing_usd():
    assert _crypto_yahoo_symbol("BTCUSD") == "BTC-USD"
    assert _crypto_yahoo_symbol("DOGEUSD") == "DOGE-USD"


def test_crypto_yahoo_symbol_passthrough_without_usd_suffix():
    assert _crypto_yahoo_symbol("BTC") == "BTC-USD"


# ---------------------------------------------------------------------------
# ASSET_CLASSES / data paths
# ---------------------------------------------------------------------------


def test_asset_classes_currently_supports_crypto_stock_futures_options():
    assert set(ASSET_CLASSES) == {"crypto", "stock", "futures", "options"}


# ---------------------------------------------------------------------------
# add_asset_to_config
# ---------------------------------------------------------------------------


def test_add_asset_to_config_appends_new_ticker(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    status = add_asset_to_config(config_path, {"ticker": "DOGEUSD", "security_type": "crypto"})

    assert status == "added"
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["phase1"]["universe"]["assets"] == [{"ticker": "DOGEUSD", "security_type": "crypto"}]


def test_add_asset_to_config_skips_existing_ticker(tmp_path):
    config_path = tmp_path / "config.json"
    existing = [{"ticker": "DOGEUSD", "security_type": "crypto", "available_from": "2020-01-01"}]
    config_path.write_text(json.dumps(_sample_config(existing), indent=4) + "\n", encoding="utf-8")

    status = add_asset_to_config(config_path, {"ticker": "DOGEUSD", "security_type": "crypto", "available_from": "1999-01-01"})

    assert status == "already_exists"
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["phase1"]["universe"]["assets"] == existing  # untouched, not overwritten


def test_add_asset_to_config_preserves_file_formatting(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    add_asset_to_config(config_path, {"ticker": "DOGEUSD"})

    text = config_path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "    " in text  # 4-space indent preserved


# ---------------------------------------------------------------------------
# fetch_adhoc_asset
# ---------------------------------------------------------------------------


def test_fetch_adhoc_asset_dry_run_writes_nothing(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    report = fetch_adhoc_asset(
        "crypto", "DOGEUSD", "2023-01-01", "2023-01-03", apply=False, fetch_fn=fake_fetch, config_path=config_path
    )

    expected_zip = tmp_path / "data" / "crypto" / "coinbase" / "daily" / "dogeusd_trade.zip"
    assert not expected_zip.exists()
    assert report["action"] == "dry_run"
    assert report["rows_fetched"] == 2
    assert report["config_status"] == "not_attempted"
    assert json.loads(config_path.read_text(encoding="utf-8")) == _sample_config()  # untouched


def test_fetch_adhoc_asset_apply_writes_crypto_zip_at_lean_path(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    report = fetch_adhoc_asset(
        "crypto", "dogeusd", "2023-01-01", "2023-01-03", apply=True, fetch_fn=fake_fetch, config_path=config_path
    )

    expected_zip = tmp_path / "data" / "crypto" / "coinbase" / "daily" / "dogeusd_trade.zip"
    assert expected_zip.exists()
    with ZipFile(expected_zip) as archive:
        assert archive.namelist() == ["dogeusd.csv"]
        content = archive.read("dogeusd.csv").decode("utf-8")
    assert "20230101 00:00,100.0,105.0,99.0,104.0,1000.0" in content  # crypto: unscaled
    assert report["ticker"] == "DOGEUSD"  # normalized to uppercase
    assert report["action"] == "written"
    assert report["config_status"] == "added"


def test_fetch_adhoc_asset_apply_writes_stock_zip_scaled_x10000(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    fetch_adhoc_asset("stock", "MSFT", "2023-01-01", "2023-01-03", apply=True, fetch_fn=fake_fetch, config_path=config_path)

    expected_zip = tmp_path / "data" / "equity" / "usa" / "daily" / "msft.zip"
    assert expected_zip.exists()
    with ZipFile(expected_zip) as archive:
        content = archive.read("msft.csv").decode("utf-8")
    assert "20230101 00:00,1000000,1050000,990000,1040000,1000.0" in content  # equity: prices x10000


def test_fetch_adhoc_asset_adds_config_block_with_relative_data_path(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    fetch_adhoc_asset("crypto", "DOGEUSD", "2023-01-01", "2023-01-03", apply=True, fetch_fn=fake_fetch, config_path=config_path)

    written = json.loads(config_path.read_text(encoding="utf-8"))
    assets = written["phase1"]["universe"]["assets"]
    assert len(assets) == 1
    block = assets[0]
    assert block["ticker"] == "DOGEUSD"
    assert block["security_type"] == "crypto"
    assert block["market"] == "coinbase"
    assert block["data_path"] == "data/crypto/coinbase/daily/dogeusd_trade.zip"  # relative, not tmp_path-absolute
    assert block["available_from"] == "2023-01-01"
    assert block["available_to"] == "2023-01-02"


def test_fetch_adhoc_asset_skips_config_write_when_ticker_already_exists(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    existing = [{"ticker": "DOGEUSD", "security_type": "crypto", "available_from": "1999-01-01", "available_to": "1999-01-02"}]
    config_path.write_text(json.dumps(_sample_config(existing), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    report = fetch_adhoc_asset("crypto", "DOGEUSD", "2023-01-01", "2023-01-03", apply=True, fetch_fn=fake_fetch, config_path=config_path)

    assert report["config_status"] == "already_exists"
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["phase1"]["universe"]["assets"] == existing  # untouched


def test_fetch_adhoc_asset_no_data_returned_writes_neither_zip_nor_config(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def empty_fetch(symbol, start, end):
        return []

    report = fetch_adhoc_asset("crypto", "NOPE", "2023-01-01", "2023-01-03", apply=True, fetch_fn=empty_fetch, config_path=config_path)

    expected_zip = tmp_path / "data" / "crypto" / "coinbase" / "daily" / "nope_trade.zip"
    assert not expected_zip.exists()
    assert report["action"] == "no_data_returned"
    assert report["config_status"] == "not_attempted"
    assert json.loads(config_path.read_text(encoding="utf-8")) == _sample_config()  # untouched


def test_fetch_adhoc_asset_never_imports_yfinance_when_fetch_fn_injected():
    """fetch_fn replaces fetch_yahoo_ohlcv entirely — yfinance is never
    imported by this test module."""
    import sys

    assert "yfinance" not in sys.modules


# ---------------------------------------------------------------------------
# futures / options - route through the same fetch_fn injection point,
# never touch data_pipeline.ib_backfill or ib_insync directly (that's
# tested in tests/test_ib_backfill.py; this module only cares that
# ASSET_CLASS_CONFIG's futures/options entries plug into the existing
# fetch_adhoc_asset() machinery correctly).
# ---------------------------------------------------------------------------


def test_fetch_adhoc_asset_apply_writes_futures_zip_unscaled(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    report = fetch_adhoc_asset("futures", "ES", "2023-01-01", "2023-01-03", apply=True, fetch_fn=fake_fetch, config_path=config_path)

    expected_zip = tmp_path / "data" / "future" / "cme" / "daily" / "es.zip"
    assert expected_zip.exists()
    with ZipFile(expected_zip) as archive:
        content = archive.read("es.csv").decode("utf-8")
    assert "20230101 00:00,100.0,105.0,99.0,104.0,1000.0" in content  # future: unscaled, like crypto
    assert report["action"] == "written"


def test_fetch_adhoc_asset_futures_config_block_carries_asset_class_and_data_source(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    fetch_adhoc_asset("futures", "ES", "2023-01-01", "2023-01-03", apply=True, fetch_fn=fake_fetch, config_path=config_path)

    written = json.loads(config_path.read_text(encoding="utf-8"))
    block = written["phase1"]["universe"]["assets"][0]
    assert block["security_type"] == "future"
    assert block["asset_class"] == "future"
    assert block["data_source"] == "ib"


def test_fetch_adhoc_asset_options_config_block_carries_asset_class_and_data_source(tmp_path, monkeypatch):
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    fetch_adhoc_asset("options", "SPY_OPT", "2023-01-01", "2023-01-03", apply=True, fetch_fn=fake_fetch, config_path=config_path)

    written = json.loads(config_path.read_text(encoding="utf-8"))
    block = written["phase1"]["universe"]["assets"][0]
    assert block["security_type"] == "option"
    assert block["asset_class"] == "option"
    assert block["data_source"] == "ib"


def test_fetch_adhoc_asset_crypto_and_stock_blocks_carry_no_extra_fields(tmp_path, monkeypatch):
    # extra_asset_fields is additive and futures/options-only - crypto/stock
    # blocks must stay byte-identical to their pre-multi-asset-class shape.
    import data_pipeline.fetch as fetch_module

    monkeypatch.setattr(fetch_module, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_sample_config(), indent=4) + "\n", encoding="utf-8")

    def fake_fetch(symbol, start, end):
        return _sample_yahoo_rows()

    fetch_adhoc_asset("crypto", "DOGEUSD", "2023-01-01", "2023-01-03", apply=True, fetch_fn=fake_fetch, config_path=config_path)

    written = json.loads(config_path.read_text(encoding="utf-8"))
    block = written["phase1"]["universe"]["assets"][0]
    assert "asset_class" not in block
    assert "data_source" not in block
