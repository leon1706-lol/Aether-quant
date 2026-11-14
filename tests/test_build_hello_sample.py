"""scripts/build_hello_sample.py (V6.6.6): the bundled sample, byte-identical for the same bars, its README and the --check."""

from __future__ import annotations

import gzip
import hashlib
from datetime import date

import pandas as pd

from script_loader import ROOT, load_script


def _bars():
    frame = pd.DataFrame({"date": [date(2021, 6, 2), date(2021, 6, 1)], "open": [1.123456789, 2.0], "close": [1.5, 2.25]})
    return {"BTCUSD": frame, "ADAUSD": frame.iloc[:1]}


def test_the_sample_is_sorted_rounded_and_reproducible():
    module = load_script("build_hello_sample")
    payload = module.sample_bytes(_bars())
    assert payload == module.sample_bytes(_bars()), "gzip with mtime 0: the same bars give the same bytes"
    lines = gzip.decompress(payload).decode("utf-8").splitlines()
    assert lines == ["date,ticker,open,close", "2021-06-01,BTCUSD,2,2.25", "2021-06-02,ADAUSD,1.1234568,1.5", "2021-06-02,BTCUSD,1.1234568,1.5"]
    text = module.readme_text("abc", 3)
    assert "`abc`" in text and "3 rows" in text and "<!--fact:sample.first-->2021-06-01<!--/fact-->" in text


def test_the_check_reads_the_shipped_sample():
    module = load_script("build_hello_sample")
    assert module.main(["--check"]) == 0


def test_a_rebuild_writes_the_sample_and_its_readme_and_refuses_a_failed_coin(tmp_path, monkeypatch, capsys):
    module = load_script("build_hello_sample")
    folder = tmp_path / "aether_quant" / "_sample"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SAMPLE_DIR", folder)
    monkeypatch.setattr(module, "SAMPLE", folder / "coinbase_daily.csv.gz")
    monkeypatch.setattr(module, "README", folder / "README.md")
    monkeypatch.setattr(module, "fetch_daily_bars", lambda tickers, start, end, cache_dir, today: (_bars(), []))
    assert module.main([]) == 0
    digest = hashlib.sha256((folder / "coinbase_daily.csv.gz").read_bytes()).hexdigest()
    assert f"`{digest}`" in (folder / "README.md").read_text(encoding="utf-8") and module.main(["--check"]) == 0
    (folder / "README.md").write_text("changed", encoding="utf-8")
    assert module.main(["--check"]) == 1 and "DIFFERS" in capsys.readouterr().out
    monkeypatch.setattr(module, "fetch_daily_bars", lambda tickers, start, end, cache_dir, today: ({}, ["XRPUSD"]))
    assert module.main([]) == 1 and "failed coins" in capsys.readouterr().err
    assert (ROOT / "aether_quant" / "_sample" / "coinbase_daily.csv.gz").exists()
