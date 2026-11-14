"""scripts/v660_crypto_splices.py (V6.6.6): finds the coins whose daily zip carries a price break and writes the list."""

from __future__ import annotations

import json
import zipfile

from script_loader import block_path_writes, load_script, run_script


def _zip(path, closes):
    lines = [f"2021010{day} 00:00,1,1,1,{close},1" for day, close in enumerate(closes, start=1)]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", "\n".join(lines) + "\n")


def test_breaks_are_found_and_written(tmp_path, monkeypatch, capsys):
    module = load_script("v660_crypto_splices")
    daily = tmp_path / "daily"
    daily.mkdir()
    _zip(daily / "abcusd_trade.zip", [1.0, 1.01, 0.001, 0.00101])
    _zip(daily / "xyzusd_trade.zip", [5.0, 5.1, 5.05])
    assert module.closes_of(daily / "xyzusd_trade.zip") == {"2021-01-01": 5.0, "2021-01-02": 5.1, "2021-01-03": 5.05}
    monkeypatch.setattr(module, "DAILY", daily)
    monkeypatch.setattr(module, "OUT", tmp_path / "breaks.json")
    monkeypatch.setattr(module, "price_breaks", lambda closes: [{"from": "2021-01-02", "to": "2021-01-03", "ratio": 0.001}] if min(closes.values()) < 0.01 else [])
    assert module.main() == 0
    report = json.loads((tmp_path / "breaks.json").read_text(encoding="utf-8"))
    assert report["coins"] == 2 and list(report["breaks"]) == ["ABCUSD"] and "ABCUSD" in capsys.readouterr().out


def test_run_as_a_script_it_writes_only_its_report(monkeypatch, capsys):
    writes = block_path_writes(monkeypatch)
    assert run_script("v660_crypto_splices", [], monkeypatch) == 0
    assert [path.name for _method, path, _args in writes] == ["crypto_price_breaks.json"] and '"coins"' in capsys.readouterr().out
