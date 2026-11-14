"""scripts/v660_round2.py's runtime (V6.6.6, #359): the hashed round-2 rules, the prepared cell, every stage and the report-only studies, with the cell and
the target-weights simulation stubbed. The trial table, the clauses and the files are the script's own."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2012-01-02", periods=80)]
TICKERS = [f"T{n:02d}" for n in range(40)]


@dataclasses.dataclass(frozen=True)
class Config:
    min_weight_change: float = 0.0
    equity_fee_bps: float = 1.0
    equity_min_fee_usd: float = 1.0
    slippage_bps_by_class: dict = dataclasses.field(default_factory=lambda: {"equity": 2.0})


@dataclasses.dataclass(frozen=True)
class Context:
    panel: object
    config: Config
    market: object
    sweep: object = None
    rf_dates: object = None
    rf_rates: object = None
    carry: object = None
    settings: object = None


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("v660_round2")
    out = tmp_path / "v660"
    out.mkdir()
    values = {"OUT": out, "DAILY": out / "selection_daily.parquet", "LEDGER": out / "trial_ledger.jsonl", "RULES_R2": out / "rules_r2.json", "RULES_R2_SHA": out / "rules_r2.sha256",
              "SCORES_R2": out / "selection_scores_r2.json", "DAILY_R2": out / "selection_daily_r2.parquet", "GATE_R2": out / "selection_gate_r2.json", "PBO_R2": out / "selection_pbo_r2.json",
              "REPORT_R2": out / "report_only_r2.json", "IB_SUBSET": out / "ib_subset.json", "ROOT": tmp_path}
    for name, value in values.items():
        monkeypatch.setattr(research, name, value)
    (out / "rules.json").write_text(json.dumps({"rules": {"R-SLEEVE3": "the bar"}}), encoding="utf-8")
    monkeypatch.setattr(research, "check_rules", lambda: {"rules": {}})
    monkeypatch.setattr(research, "assert_selection_only", lambda end: None)
    return research


def _cell(module):
    known = pd.DataFrame(100.0 + np.arange(80)[:, None] + np.arange(40)[None, :], index=DATES, columns=TICKERS)
    extras = {name: known.copy() for name in ("w03", "w04", "w06", "w09", "w10", "w11", "w14", "w15")}
    panel = SimpleNamespace(known=known, extras=extras, asset_class={ticker: "crypto" for ticker in TICKERS[:12]})
    market = SimpleNamespace(sessions=DATES)
    context = Context(panel=panel, config=Config(), market=market)
    window = SimpleNamespace(start=DATES[0], end=DATES[-1], split=DATES[40], name="S", universe="equity")
    bars = SimpleNamespace(raw_close=known, volume=known * 0 + 1000.0)
    return SimpleNamespace(cell=window, context=context, member=pd.DataFrame(True, index=DATES, columns=TICKERS), label=known.pct_change().shift(-5), bars=bars, sectors={t: f"sec{index % 3}" for index, t in enumerate(TICKERS)})


def test_the_rules_are_written_once_hashed_and_checked(module, capsys):
    assert module.stage_rules(SimpleNamespace()) == 0
    written = json.loads(module.RULES_R2.read_text(encoding="utf-8"))
    assert set(written["trials"]) == set(module.TRIALS) and capsys.readouterr().out.strip() == module.RULES_R2_SHA.read_text(encoding="utf-8").strip()
    with pytest.raises(SystemExit, match="already written"):
        module.stage_rules(SimpleNamespace())
    assert module.check_rules_r2()["cell"] == "S"
    module.RULES_R2_SHA.write_text("0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="recorded hash"):
        module.check_rules_r2()


def _ready(module, monkeypatch):
    monkeypatch.setattr(module, "check_rules_r2", lambda: {})
    cell = _cell(module)
    monkeypatch.setattr(module, "load_cells", lambda specs: {"S": cell})
    return cell


def test_the_prepared_cell_builds_one_table_and_one_context_per_trial(module, monkeypatch):
    cell = _ready(module, monkeypatch)
    prepared, contexts = module.prepared_cell()
    assert prepared is cell and set(contexts) == set(module.TRIALS) and all(trial in cell.context.panel.extras for trial in module.TRIALS)
    assert contexts["r04"].config.min_weight_change == module.band_of("r04")


def _score_stubs(monkeypatch, module, sharpe=1.0):
    monkeypatch.setattr(module, "live_names_per_rebalance", lambda table, every: {"median": 1000.0, "minimum": 500.0})
    monkeypatch.setattr(module, "score_sleeve", lambda spec, context, **kwargs: {"sharpe": sharpe, "sharpe_first_half": 0.9, "sharpe_second_half": 1.1, "turnover": 2.0,
                                                                                   "daily": {0: pd.Series(np.cos(np.arange(80)) * 0.01, index=DATES)}})
    monkeypatch.setattr(module, "_ic_clause", lambda spec, cell, signal: {"nonoverlap_t": 3.0})


def test_scoring_runs_each_round_two_trial_once(module, monkeypatch, capsys):
    _ready(module, monkeypatch)
    _score_stubs(monkeypatch, module)
    assert module.stage_score(SimpleNamespace(only=["r01", "r02"], force=False)) == 0
    assert set(json.loads(module.SCORES_R2.read_text(encoding="utf-8"))) == {"r01", "r02"} and module.DAILY_R2.exists()
    assert module.stage_score(SimpleNamespace(only=None, force=False)) == 0
    assert set(json.loads(module.SCORES_R2.read_text(encoding="utf-8"))) == set(module.TRIALS)
    assert module.stage_score(SimpleNamespace(only=["r01"], force=True)) == 0


def test_the_placebo_stage_tests_only_the_trials_that_reached_it(module, monkeypatch, capsys):
    _ready(module, monkeypatch)
    assert module.stage_placebo(SimpleNamespace(draws=3, force=False)) == 0 and "none" in capsys.readouterr().out
    module.write_json(module.SCORES_R2, {"r01": {"sharpe": 1.0, "sharpe_first_half": 1.0, "sharpe_second_half": 1.0, "live_names": {"median": 1000.0}, "ic": {"nonoverlap_t": 3.0}}})
    monkeypatch.setattr(module, "passes_earlier_clauses", lambda name, track, score: True)
    monkeypatch.setattr(module, "nulls_for", lambda spec: ["shuffle", "shift"])
    monkeypatch.setattr(module, "placebo_sharpes", lambda spec, context, mode, start, end, draws: [] if mode == "shift" else [0.1, 0.2])
    monkeypatch.setattr(module, "placebo_p_value", lambda observed, sharpes: 0.03)
    assert module.stage_placebo(SimpleNamespace(draws=3, force=False)) == 0
    assert module.stage_placebo(SimpleNamespace(draws=3, force=False)) == 0
    done = json.loads((module.OUT / "selection_placebos_r2.json").read_text(encoding="utf-8"))
    assert done["r01"]["shuffle"]["draws"] == 2 and done["r01"]["shift"]["median"] is None


def test_the_gate_names_why_a_trial_failed_early(module, monkeypatch, capsys):
    monkeypatch.setattr(module, "check_rules_r2", lambda: {})
    good = {"sharpe": 1.0, "sharpe_first_half": 1.0, "sharpe_second_half": 1.0, "live_names": {"median": 1000.0}, "ic": {"nonoverlap_t": 3.0}}
    module.write_json(module.SCORES_R2, {"r01": good, "r02": {**good, "live_names": {"median": 0.0}}, "r03": {**good, "sharpe": 0.1}, "r04": {**good, "ic": {"nonoverlap_t": 0.1}}})
    pd.DataFrame({"r01": np.sin(np.arange(80)) * 0.01}, index=DATES).to_parquet(module.DAILY_R2)
    module.write_json(module.OUT / "selection_placebos_r2.json", {"r01": {"shuffle": {"p": 0.01}}})
    monkeypatch.setattr(module, "passes_earlier_clauses", lambda name, track, score: name == "r01")
    monkeypatch.setattr(module, "selection_gate", lambda rows, p_values: {"survivors": ["r01"], "failed": []})
    assert module.stage_gate(SimpleNamespace()) == 0
    gate = json.loads(module.GATE_R2.read_text(encoding="utf-8"))
    assert gate["failed_earlier_clauses"] == {"r02": "live_names", "r03": "sharpe", "r04": "ic"} and "r05" in gate["unscored"]


def test_pbo_pools_round_one_and_round_two_columns(module, monkeypatch, capsys):
    import evaluation.pbo as pbo

    monkeypatch.setattr(module, "check_rules_r2", lambda: {})
    columns_one = list(module.PBO_COLUMNS[:2])
    pd.DataFrame({name: np.sin(np.arange(80) + i) * 0.01 for i, name in enumerate(columns_one)}, index=DATES).to_parquet(module.DAILY)
    pd.DataFrame({"r01": np.cos(np.arange(80)) * 0.01}, index=DATES).to_parquet(module.DAILY_R2)
    monkeypatch.setattr(pbo, "probability_of_backtest_overfitting", lambda matrix, blocks, periods_per_year: {"pbo": 0.2})
    assert module.stage_pbo(SimpleNamespace()) == 0
    assert json.loads(module.PBO_R2.read_text(encoding="utf-8"))["num_trials"] == 3


def test_the_cost_variants_rerun_the_book_at_twice_the_costs_and_a_smaller_nav(module, monkeypatch):
    cell = _cell(module)
    monkeypatch.setattr(module, "weights_for", lambda spec, context, signal, start, end, phase_offset: [{"T00": 0.1}])
    seen = []
    monkeypatch.setattr(module, "simulate_target_weights", lambda weights, market, config, start, end, nav, **kwargs: seen.append((config.equity_fee_bps, nav)) or {"strategy_excess": pd.Series(np.sin(np.arange(80)) * 0.01, index=DATES)})
    result = module.cost_variants(cell.context, module.spec_of("r01"), cell.context.panel.known, start=DATES[0], end=DATES[-1], split=DATES[40])
    assert set(result) == {"as_is", "costs_2x", "nav_25k", "nav_25k_costs_2x"} and {(1.0, 100_000.0), (2.0, 100_000.0), (1.0, 25_000.0), (2.0, 25_000.0)} <= set(seen)
    monkeypatch.setattr(module, "annual_sharpe", lambda series, sessions=None: None)
    assert module.cost_variants(cell.context, module.spec_of("r01"), cell.context.panel.known, start=DATES[0], end=DATES[-1], split=DATES[40])["as_is"] is None


def test_the_report_only_stage_measures_ic_and_costs(module, monkeypatch):
    cell = _ready(module, monkeypatch)
    cell.context.panel.extras["m1"] = cell.context.panel.known.copy()
    monkeypatch.setattr(module, "cost_variants", lambda context, spec, signal, start, end, split: {"as_is": 0.5})
    assert module.stage_report(SimpleNamespace()) == 0
    report = json.loads(module.REPORT_R2.read_text(encoding="utf-8"))
    assert "m1" in report["ic"] and "m2" not in report["ic"] and "r01" in report["costs"] and set(module.SENSITIVITY) <= set(report["costs"])


def _venue_world(module, monkeypatch):
    import evaluation.premia_research as premia
    import portfolio.premia_signals as signals
    import v660_verdict

    known = pd.DataFrame(100.0 + np.arange(80)[:, None] + np.arange(14)[None, :], index=DATES, columns=[*module.IB_COINS, "EOSUSD", "XLMUSD", "ETCUSD", "ZECUSD", "TRXUSD", "SOLUSD"])
    panel = SimpleNamespace(known=known, asset_class={column: "crypto" for column in known.columns})
    context = SimpleNamespace(panel=panel, market=SimpleNamespace(sessions=DATES), config=None, sweep=None, rf_dates=None, rf_rates=None, carry=None, settings=None)
    monkeypatch.setattr(premia, "build_context", lambda root, base: context)
    monkeypatch.setattr(signals, "sleeve_signal", lambda spec, panel_: known.copy())
    monkeypatch.setattr(signals, "signal_to_weights", lambda table, panel_, **kwargs: [{"BTCUSD": 0.1}])
    fees = []
    monkeypatch.setattr(module, "simulate_target_weights", lambda weights, market, config, start, end, **kwargs: fees.append(kwargs["fee_fn"]) or {"strategy_excess": pd.Series(np.sin(np.arange(80)) * 0.01, index=DATES), "fees": 12.0, "gross": pd.Series(0.5, index=DATES)})
    monkeypatch.setattr(module, "base_config", lambda: {})
    assert v660_verdict.INSTALLED is not None
    return fees


def test_the_venue_studies_price_the_installed_sleeve_at_other_fees(module, monkeypatch):
    fees = _venue_world(module, monkeypatch)
    monkeypatch.setattr(module, "check_rules_r2", lambda: {})
    assert module.stage_ib_subset(SimpleNamespace()) == 0
    report = json.loads(module.IB_SUBSET.read_text(encoding="utf-8"))
    assert set(report["2014-12..2026-11"]) == {"12_coins_coinbase_fees", "11_coins_without_eos_coinbase_fees", "8_ib_coins_coinbase_fees", "8_ib_coins_ib_fees"}
    ib_fee = next(fee for fee in fees if getattr(fee, "__name__", "") == "ib_fee")
    assert ib_fee("crypto", 100.0, None, None) == 1.75 and ib_fee("crypto", 1_000_000.0, None, None) == 1500.0 and ib_fee("equity", 100.0, None, None) == 0.0
    fees.clear()
    assert module.stage_kraken_subset(SimpleNamespace()) == 0
    assert set(json.loads((module.OUT / "kraken_subset.json").read_text(encoding="utf-8"))["2014-12..2026-11"]) == {"kraken_taker_40bps", "kraken_taker_80bps"}
    taker = fees[0]
    assert taker("crypto", -1000.0, None, None) == 4.0 and taker("equity", 1000.0, None, None) == 0.0


@pytest.mark.parametrize("name", ["rules", "score", "placebo", "gate", "pbo", "report", "ib_subset", "kraken_subset"])
def test_the_command_dispatches_each_stage(module, monkeypatch, name):
    seen = []
    monkeypatch.setattr(module, f"stage_{name}", lambda args: seen.append(name) or 0)
    monkeypatch.setattr(sys, "argv", ["round2", name])
    assert module.main() == 0 and seen == [name]
    monkeypatch.setattr(sys, "argv", ["round2", "score", "--only", "r01", "--force"])
    monkeypatch.setattr(module, "stage_score", lambda args: 0)
    assert module.main() == 0
    monkeypatch.setattr(sys, "argv", ["round2", "placebo", "--draws", "5", "--force"])
    monkeypatch.setattr(module, "stage_placebo", lambda args: 0)
    assert module.main() == 0 and hashlib is not None
