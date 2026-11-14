"""The last unreached lines of the aether_quant facades (V6.6.6, #359)."""

from __future__ import annotations

import importlib
import json

import numpy as np
import pandas as pd


def test_the_version_falls_back_when_the_package_is_not_installed(monkeypatch):
    import importlib.metadata as metadata

    import aether_quant

    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    try:
        assert importlib.reload(aether_quant).__version__ == "0.0.0+local"
    finally:
        monkeypatch.undo()
        importlib.reload(aether_quant)


def test_hello_run_prints_a_notice_and_save_writes_both_files(tmp_path, monkeypatch, capsys):
    from aether_quant import hello

    seen = {}
    monkeypatch.setattr(hello, "load_closes", lambda **kwargs: (pd.DataFrame(), "sample", "download failed: using the sample"))
    monkeypatch.setattr(hello, "run_hello", lambda closes, start, end, data_source: seen.update(source=data_source) or "report")
    assert hello.run(offline=False, cache=False) == "report" and "using the sample" in capsys.readouterr().out and seen["source"] == "sample"
    monkeypatch.setattr(hello, "load_closes", lambda **kwargs: (pd.DataFrame(), "sample", None))
    hello.run(offline=True)
    assert capsys.readouterr().out == ""

    report = type("Report", (), {"to_dict": lambda self: {"sharpe": float("nan"), "n": 1}})()
    monkeypatch.setattr(hello, "render_html", lambda report: "<html></html>")
    hello.save(report, html_path=tmp_path / "r.html", json_path=tmp_path / "r.json")
    assert (tmp_path / "r.html").read_text(encoding="utf-8") == "<html></html>" and json.loads((tmp_path / "r.json").read_text(encoding="utf-8")) == {"sharpe": None, "n": 1}
    hello.save(report)


def test_hrp_weights_sum_to_one():
    from aether_quant.portfolio import compute_hrp_weights

    rng = np.random.default_rng(0)
    returns = pd.DataFrame(rng.normal(size=(200, 4)), columns=list("ABCD"))
    weights = compute_hrp_weights(returns)
    assert abs(float(weights.sum()) - 1.0) < 1e-9 and sorted(weights.index) == list("ABCD")
