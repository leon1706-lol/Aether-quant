"""scripts/v660_venue_coverage.py (V6.6.6): Coinbase, Kraken and Binance public endpoints, with requests as a stand-in."""

from __future__ import annotations

import json

import requests

from script_loader import block_path_writes, load_script, run_script


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def test_get_retries_errors_and_rate_limits_then_gives_up(monkeypatch):
    module = load_script("v660_venue_coverage")
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    answers = [requests.ConnectionError("down"), _Response(429), _Response(200, [])]

    def get(url, params, headers, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(module.requests, "get", get)
    assert module.get("u").status_code == 200
    monkeypatch.setattr(module.requests, "get", lambda url, params, headers, timeout: _Response(429))
    assert module.get("u") is None


def test_each_venue_reads_its_own_shape(monkeypatch):
    module = load_script("v660_venue_coverage")
    stamp = 1609459200  # 2021-01-01
    responses = {
        "coinbase": _Response(200, [[stamp + 86400, 1], [stamp, 1]]), "kraken": _Response(200, {"error": [], "result": {"XBTUSD": [[stamp], [stamp + 86400]], "last": 1}}),
        "binance": _Response(200, [[stamp * 1000]]),
    }
    monkeypatch.setattr(module, "get", lambda url, **params: next(value for key, value in responses.items() if key in url))
    assert module.coinbase("BTC") == {"status": 200, "bars": 2, "first": "2021-01-01", "last": "2021-01-02", "per_call_limit": 300}
    assert module.kraken("BTC")["first"] == "2021-01-01" and module.binance("BTC")["first"] == "2021-01-01"
    responses.update(coinbase=_Response(200, []), kraken=_Response(200, {"error": ["EQuery:Unknown asset pair"]}), binance=_Response(200, []))
    assert module.coinbase("X")["first"] is None and module.kraken("X") == {"status": 200, "error": "EQuery:Unknown asset pair"} and module.binance("X")["first"] is None
    responses.update(coinbase=_Response(404), kraken=_Response(500), binance=_Response(451))
    assert [module.coinbase("X")["status"], module.kraken("X")["status"], module.binance("X")["status"]] == [404, 500, 451]
    monkeypatch.setattr(module, "get", lambda url, **params: None)
    assert module.coinbase("X") == module.kraken("X") == module.binance("X") == {"status": None}


def test_run_as_a_script_it_writes_one_report(monkeypatch, capsys):
    import time

    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    monkeypatch.setattr(requests, "get", lambda url, params, headers, timeout: _Response(503))
    writes = block_path_writes(monkeypatch)
    assert run_script("v660_venue_coverage", [], monkeypatch) == 0
    ((method, path, args),) = writes
    report = json.loads(args[0])
    assert path.name == "venue_data_coverage.json" and set(report["coins"]["BTC"]) == {"coinbase", "kraken", "binance"}
    assert "BTC" in capsys.readouterr().out
