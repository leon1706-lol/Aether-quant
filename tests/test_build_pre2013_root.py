"""scripts/build_pre2013_root.py: a separate root with no network and no look at a price; `data/` is never touched."""

import importlib.util
import json
from datetime import date
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_pre2013_root", Path(__file__).resolve().parent.parent / "scripts" / "build_pre2013_root.py"
)
module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(module)

CONFIG = {"phase1": {"universe": {"assets": [
    {"ticker": "AAA", "security_type": "equity", "data_path": "data/equity/usa/daily/aaa.zip"},
    {"ticker": "LATE", "security_type": "equity", "data_path": "data/equity/usa/daily/late.zip"},
    {"ticker": "BAD", "security_type": "equity", "data_path": "data/equity/usa/daily/bad.zip"},
    {"ticker": "EURUSD", "security_type": "forex", "data_path": "data/forex/oanda/daily/eurusd.zip", "market": "oanda"},
    {"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"},
]}}}


def _rows(*days):
    return [{"date": date.fromisoformat(day), "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 100} for day in days]


def _fetch(symbol, start, end):
    if symbol.startswith("LATE"):
        return []
    if symbol.startswith("BAD"):
        raise RuntimeError("boom")
    return _rows("2010-01-04", "2010-01-05", "2013-01-02")


def _build(tmp_path):
    source = tmp_path / "source"
    (source / "market-hours").mkdir(parents=True)
    (source / "market-hours" / "db.json").write_text("{}")
    (source / "alternative" / "interest-rate").mkdir(parents=True)
    (source / "alternative" / "interest-rate" / "r.csv").write_text("DATE,X\n")
    out = tmp_path / "root"
    return out, source, module.build_root(CONFIG, out, start="2002-01-01", end="2013-01-02", source=source, fetch_fn=_fetch)


def test_writes_only_tickers_with_bars_and_says_why_for_the_rest(tmp_path):
    out, _, manifest = _build(tmp_path)

    assert sorted(manifest["tickers"]) == ["AAA", "BIL", "EURUSD"]
    assert manifest["left_out"] == {"LATE": "no bars in the window", "BAD": "fetch failed: RuntimeError", "BTCUSD": "crypto"}
    assert (out / "equity" / "usa" / "daily" / "aaa.zip").exists()
    assert (out / "forex" / "oanda" / "daily" / "eurusd.zip").exists()


def test_rows_on_or_after_the_end_never_enter_the_root(tmp_path):
    _, _, manifest = _build(tmp_path)
    assert manifest["tickers"]["AAA"]["last"] == "2010-01-05"
    assert manifest["tickers"]["AAA"]["rows"] == 2


def test_manifest_holds_counts_and_hashes_but_no_prices(tmp_path):
    out, _, manifest = _build(tmp_path)
    assert json.loads((out / "pre2013_manifest.json").read_text()) == manifest
    assert set(manifest["tickers"]["AAA"]) == {"rows", "first", "last", "sha256", "security_type"}


def test_reference_files_are_copied_and_map_files_start_empty(tmp_path):
    out, source, _ = _build(tmp_path)
    assert (out / "market-hours" / "db.json").exists()
    assert (out / "alternative" / "interest-rate" / "r.csv").exists()
    assert list((out / "equity" / "usa" / "map_files").iterdir()) == []
    assert not list(source.rglob("aaa.zip"))


def test_universe_for_root_keeps_only_held_tickers(tmp_path):
    _, _, manifest = _build(tmp_path)
    tickers = [asset["ticker"] for asset in module.universe_for_root(CONFIG, manifest)["phase1"]["universe"]["assets"]]
    assert tickers == ["AAA", "EURUSD"]
