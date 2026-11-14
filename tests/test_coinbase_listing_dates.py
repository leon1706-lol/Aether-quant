"""scripts/coinbase_listing_dates.py (V6.6.6): listing, suspension and delisting from daily candles; the fetch retries,
pages and gives up; the CLI prints and, with --apply, writes. No network: urlopen is a stand-in."""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone

import pytest

from script_loader import load_script, run_script


def _stamp(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def test_product_id_and_listing_entry():
    module = load_script("coinbase_listing_dates")
    assert module.product_id("BTCUSD") == "BTC-USD"
    assert module.listing_entry([], min_gap_days=7) == {"listed": None, "last": None, "suspended": [], "delisted": None}
    days = [date(2021, 1, 1), date(2021, 1, 2), date(2021, 3, 1), date(2021, 3, 2)]
    entry = module.listing_entry(days, min_gap_days=7, end=date(2021, 6, 1))
    assert entry == {"listed": "2021-01-01", "last": "2021-03-02", "suspended": [["2021-01-03", "2021-03-01"]], "delisted": "2021-03-03"}
    assert module.listing_entry(days, min_gap_days=7, end=date(2021, 3, 5))["delisted"] is None


def test_fetch_retries_pages_and_reads_every_candle(monkeypatch):
    module = load_script("coinbase_listing_dates")
    responses = [OSError("reset"), [[_stamp("2021-01-01"), 1, 2, 3, 4, 5]], {"message": "not a list"}]
    urls = []

    def urlopen(request, timeout):
        urls.append(request.full_url)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(json.dumps(item).encode("utf-8"))

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(module._time, "sleep", lambda seconds: None)
    days = module.fetch_candle_days("BTC-USD", date(2021, 1, 1), date(2021, 12, 1), pause=0)
    assert days == [date(2021, 1, 1)] and len(urls) == 3 and "start=2021-10-28" in urls[-1]


def test_fetch_gives_up_after_four_attempts(monkeypatch):
    module = load_script("coinbase_listing_dates")

    def urlopen(request, timeout):
        raise OSError("down")

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(module._time, "sleep", lambda seconds: None)
    with pytest.raises(OSError, match="down"):
        module.fetch_candle_days("BTC-USD", date(2021, 1, 1), date(2021, 1, 5))


def test_main_prints_every_coin_and_writes_only_with_apply(tmp_path, monkeypatch, capsys):
    module = load_script("coinbase_listing_dates")
    monkeypatch.setattr(module, "fetch_candle_days", lambda product, start, end: [date(2021, 1, 1), date(2021, 1, 2)])
    output = tmp_path / "listing.json"
    monkeypatch.setattr(module.sys, "argv", ["x", "--output", str(output), "--end", "2021-01-03"])
    assert module.main() == 0 and not output.exists() and "BTCUSD" in capsys.readouterr().out
    monkeypatch.setattr(module.sys, "argv", ["x", "--output", str(output), "--end", "2021-01-03", "--apply"])
    assert module.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["assets"]["BTCUSD"]["listed"] == "2021-01-01"


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("coinbase_listing_dates", ["--help"], monkeypatch) == 0
    assert "--apply" in capsys.readouterr().out
