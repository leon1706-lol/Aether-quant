"""scripts/build_crypto_wide_root.py (V6.6.6): pairs with no bars, a token swap cut, progress every 5 pairs, the pause, and the
CLI's three outcomes. tests/test_binance_archive.py covers the root's contents."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from script_loader import load_script, run_script
from test_binance_archive import _fixture_root, _kline_payload, _page


def test_every_pair_is_handled_and_progress_is_saved(tmp_path, monkeypatch, capsys):
    import build_crypto_wide_root as module

    wide, source = _fixture_root(tmp_path)
    jan_2021 = 1609459200000
    coins = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "NONEUSDT"]

    def get_bytes(url):
        if "fundingRate" in url or "NONEUSDT" in url:
            return None
        return _kline_payload(jan_2021)

    sleeps = []
    monkeypatch.setattr(module._time, "sleep", sleeps.append)
    swaps = iter(["2021-01-10"])  # the first pair carries a swap, the others none
    monkeypatch.setattr(module, "truncate_at_swap", lambda rows: (rows, next(swaps, None)))
    manifest = module.build_root(tmp_path / "crypto", get_text=lambda url: _page(coins, False), get_bytes=get_bytes, source=source, wide_root=wide,
                                 start="2021-01-01", end="2021-02-01", pause_seconds=0.01)
    assert manifest["left_out"]["NONE"] == "no bars" and len(manifest["coins"]) == 5
    assert manifest["cut_at_a_swap"] == {"AAA": "2021-01-10"} and sleeps and "5 of 6" in capsys.readouterr().out


def test_the_cli_cuts_swaps_builds_or_stops_on_an_outage(tmp_path, monkeypatch, capsys):
    module = load_script("build_crypto_wide_root")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "cut_swaps", lambda root: {"cut": [root.name]})
    monkeypatch.setattr(module.sys, "argv", ["x", "--cut-swaps"])
    assert module.main() == 0 and '"cut"' in capsys.readouterr().out

    answers = {"listing": SimpleNamespace(text="<xml/>"), "zip": SimpleNamespace(content=b"PK")}
    monkeypatch.setattr(module.net_retry, "fetch", lambda url, get, timeout: answers.get(url))

    def build(out, get_text, get_bytes):
        assert get_text("listing") == "<xml/>" and get_bytes("zip") == b"PK" and get_bytes("gone") is None
        with pytest.raises(SystemExit, match="the listing itself is gone"):
            get_text("gone")
        return {"coins": {"BTC": {"last": "2026-10-30"}}, "left_out": {}}

    monkeypatch.setattr(module, "build_root", build)
    monkeypatch.setattr(module.sys, "argv", ["x", "--out", "crypto"])
    assert module.main() == 0 and "1 coins, 0 stopped" in capsys.readouterr().out

    def outage(out, get_text, get_bytes):
        raise module.net_retry.NetworkOutage("down")

    monkeypatch.setattr(module, "build_root", outage)
    assert module.main() == 3 and "network outage" in capsys.readouterr().err


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("build_crypto_wide_root", ["--help"], monkeypatch) == 0 and "--cut-swaps" in capsys.readouterr().out
