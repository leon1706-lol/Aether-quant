"""`aq hello` and evaluation/hello_world.py (V6.6.5, #343)."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

from aether_quant import samples
from evaluation.hello_world import HELLO_RULE, RESEARCH_TRIALS, known_at_sessions, load_closes, render_html, render_text, rule_weights, run_hello

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def report():
    return run_hello(samples.load_sample_prices())


def test_the_demo_rule_is_the_shipped_forward_definition():
    candidates = json.loads((ROOT / "ml" / "forward" / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    candidate = next(item for item in candidates if item.get("installed"))
    for key in ("id", "kind", "family", "universe", "rebalance_every", "params"):
        assert HELLO_RULE[key] == candidate[key], key
    assert sorted(samples.load_sample_prices().columns) == sorted(candidate["tickers"])


def test_the_trial_count_is_the_research_records():
    assert f"The deflated-Sharpe N is now {RESEARCH_TRIALS}." in (ROOT / "development" / "Problems.md").read_text(encoding="utf-8")


def test_a_session_reads_only_the_bar_dated_before_it():
    closes = pd.DataFrame({"BTCUSD": [1.0, 2.0, 3.0, 4.0]}, index=["2024-01-05", "2024-01-06", "2024-01-07", "2024-01-08"])
    known = known_at_sessions(closes, ["2024-01-05", "2024-01-08"])
    assert math.isnan(known.loc["2024-01-05", "BTCUSD"]) and known.loc["2024-01-08", "BTCUSD"] == 3.0


def test_a_future_bar_changes_no_earlier_decision():
    closes = samples.load_sample_prices()
    base = rule_weights(closes, start="2023-01-01", end="2023-06-30")
    shocked = closes.copy()
    shocked.loc[shocked.index > "2023-04-01"] *= 3.0
    after = rule_weights(shocked, start="2023-01-01", end="2023-06-30")
    early = base.index <= "2023-04-01"
    pd.testing.assert_frame_equal(base[early], after[early])


def test_report_numbers_are_finite_and_stable(report):
    assert report.start == "2022-01-01" and report.end == "2026-10-31" and len(report.coins) == 11
    assert math.isclose(report.strategy.sharpe, 0.43, abs_tol=0.01)
    assert 0.0 < report.strategy.average_gross < 0.2 and report.strategy.cost_bps > 0
    assert 0.0 <= report.pbo <= 1.0 and 0.0 <= report.psr <= 1.0 and 0.0 <= report.dsr_grid <= 1.0
    assert report.haircut_sharpe <= report.strategy.sharpe
    assert len(report.grid_sharpes) == 8
    assert report.equity.iloc[0] == 1.0


def test_text_json_and_html(report, tmp_path):
    text = render_text(report)
    for needle in ("Shipped rule", "BTC buy & hold", "PBO", "Deflated Sharpe", "No verified edge"):
        assert needle in text
    payload = report.to_dict()
    encoded = json.dumps(payload, allow_nan=False)
    assert json.loads(encoded)["rule"] == HELLO_RULE["id"]
    page = render_html(report)
    assert page.startswith("<!doctype html>") and "<svg" in page and "<script" not in page


def test_offline_and_fallback(monkeypatch):
    closes, source, notice = load_closes(offline=True)
    assert notice is None and "sample" in source and closes.shape[1] == 11

    def broken(url: str):
        raise ConnectionError("no network")

    closes, source, notice = load_closes(offline=False, get_json=broken, cache_dir=None)
    assert "sample" in source and notice and "bundled sample" in notice


def test_aq_hello_offline_runs_and_writes_files(tmp_path):
    env = {**os.environ, "AQ_SKIP_UPDATE_CHECK": "1", "PYTHONPATH": str(ROOT)}
    began = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-c", "import aq_cli; aq_cli.main()", "hello", "--offline", "--json", str(tmp_path / "h.json"), "--html", str(tmp_path / "h.html")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600,
    )
    elapsed = time.perf_counter() - began
    assert result.returncode == 0, result.stderr[-3000:]
    assert "[4/4] Report" in result.stdout and "Sharpe" in result.stdout
    assert (tmp_path / "h.json").is_file() and (tmp_path / "h.html").is_file()
    assert elapsed < 180, elapsed  # 26 s on the 4 GB dev PC


def test_an_empty_decision_closes_the_book_on_every_pandas(monkeypatch):
    import evaluation.hello_world as hello_world

    closes = samples.load_sample_prices()
    monkeypatch.setattr(hello_world, "signal_to_weights", lambda *args, **kwargs: {"2023-01-02": {"BTCUSD": 0.1}, "2023-01-09": {}})
    weights = hello_world.rule_weights(closes, start="2023-01-01", end="2023-01-31")
    assert weights.loc["2023-01-02", "BTCUSD"] == 0.1
    assert (weights.loc["2023-01-09"] == 0.0).all()  # pandas 2's from_dict dropped this row and the book was held instead
    assert weights.loc["2023-01-03"].isna().all()
