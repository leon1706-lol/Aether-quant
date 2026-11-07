"""evaluation/research_round.py: the guards, and round 2 recomputed from its stored scores. The scored runs need the wide data and are not repeated here."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation.research_cells import CELLS, record_holdout_read
from evaluation.research_round import (
    count_unrun_trials,
    gate_report,
    holdouts_spent,
    load_round,
    passes_earlier_clauses,
    pbo_report,
    r_hold1,
    score_file_table,
    stage_freeze,
    trial_table,
    write_rules,
)
from evaluation.trial_ledger import read_ledger

ROOT = Path(__file__).resolve().parents[1]
V660 = ROOT / "ml" / "evaluation" / "v660"
DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2011-01-03", periods=40)]
TICKERS = [f"T{number:02d}" for number in range(40)]


def _payload(tmp_path: Path) -> dict:
    return {
        "name": "t", "cell": "S", "side": "A", "bar": "R-SLEEVE3", "rule": "R-T", "out_dir": str(tmp_path / "out"), "ledger": str(tmp_path / "ledger.jsonl"),
        "trials": {
            "a1": {"kind": "pooled", "rebalance_every": 20, "recipe": {"op": "single", "parts": ["f"], "signs": {"f": -1.0}}},
            "a2": {"kind": "pooled", "rebalance_every": 20, "score_file": "a2"},
            "a3": {"kind": "pooled", "rebalance_every": 20, "recipe": {"op": "rank_mean", "parts": ["a1", "a2"], "optional_parts": True, "minimum": 2}},
        },
    }


def _table(seed: int = 1) -> pd.DataFrame:
    return pd.DataFrame(np.random.default_rng(seed).normal(size=(len(DATES), len(TICKERS))), index=DATES, columns=TICKERS)


class _Context:
    def __init__(self, known):
        self.panel = type("Panel", (), {"known": known, "extras": {}})()


class _Cell:
    def __init__(self):
        self.features = {"f": _table(1)}
        self.tables = {}
        self.member = pd.DataFrame(True, index=DATES, columns=TICKERS)
        self.member[TICKERS[0]] = False
        self.context = _Context(_table(2))
        self.sectors = {ticker: "tech" for ticker in TICKERS}
        self.cell = CELLS["S"]
        self.label = _table(3)


def test_rules_are_written_once_and_a_change_stops_the_round(tmp_path):
    path = tmp_path / "round.json"
    digest = write_rules(_payload(tmp_path), path)
    assert (tmp_path / "round.sha256").read_text(encoding="utf-8").strip() == digest
    with pytest.raises(FileExistsError):
        write_rules(_payload(tmp_path), path)
    spec = load_round(path)
    assert spec.name == "t" and list(spec.trials) == ["a1", "a2", "a3"]
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_round(path)


def test_a_round_with_no_recorded_hash_does_not_load(tmp_path):
    path = tmp_path / "round.json"
    path.write_text(json.dumps(_payload(tmp_path)), encoding="utf-8")
    with pytest.raises(SystemExit):
        load_round(path)


def test_trial_tables_mask_to_members_and_wait_for_a_missing_model(tmp_path):
    path = tmp_path / "round.json"
    write_rules(_payload(tmp_path), path)
    spec = load_round(path)
    cell = _Cell()
    built: dict[str, pd.DataFrame] = {}
    built["a1"] = trial_table(spec, "a1", cell, built, score_dir=tmp_path)
    assert built["a1"][TICKERS[0]].isna().all()
    pd.testing.assert_series_equal(built["a1"][TICKERS[1]], -cell.features["f"][TICKERS[1]])
    assert trial_table(spec, "a2", cell, built, score_dir=tmp_path) is None
    assert trial_table(spec, "a3", cell, built, score_dir=tmp_path) is None, "a composite that names a model which didn't run needs at least two parts"
    frame = cell.features["f"].stack().rename("score").rename_axis(["date", "ticker"]).reset_index()
    frame.to_csv(tmp_path / "a2.csv", index=False)
    built["a2"] = trial_table(spec, "a2", cell, built, score_dir=tmp_path)
    assert built["a2"].notna().any().any()
    assert trial_table(spec, "a3", cell, built, score_dir=tmp_path).notna().any().any()


def test_a_score_file_that_is_not_there_reads_as_absent(tmp_path):
    assert score_file_table(tmp_path / "gone.csv", DATES, TICKERS) is None


def test_earlier_clauses_are_all_needed():
    good = {"sharpe": 0.6, "sharpe_first_half": 0.5, "sharpe_second_half": 0.5, "live_names": {"median": 160.0}, "ic": {"nonoverlap_t": 2.1}}
    assert passes_earlier_clauses(good, min_live_names=150)
    assert not passes_earlier_clauses({**good, "sharpe_second_half": 0.39}, min_live_names=150)
    assert not passes_earlier_clauses({**good, "live_names": {"median": 149.0}}, min_live_names=150)
    assert not passes_earlier_clauses({**good, "ic": {"nonoverlap_t": 1.99}}, min_live_names=150)
    assert not passes_earlier_clauses({**good, "ic": None}, min_live_names=150)


def test_gate_report_names_unscored_trials():
    daily = pd.DataFrame({"a": np.random.default_rng(1).normal(size=40)}, index=DATES)
    good = {"sharpe": 0.6, "sharpe_first_half": 0.5, "sharpe_second_half": 0.5, "live_names": {"median": 160.0}, "ic": {"nonoverlap_t": 2.1}}
    passed = gate_report({"a": good}, {"a": {"asset_block": {"p": 0.01}, "time_shift": {"p": 0.02}}}, daily, trials=["a", "b"])
    assert passed["survivors"] == ["a"] and passed["unscored"] == ["b"]
    failed = gate_report({"a": good}, {"a": {"asset_block": {"p": 0.2}, "time_shift": {"p": 0.02}}}, daily, trials=["a"])
    assert failed["survivors"] == [] and failed["failed"] == {"a": "placebo"}
    no_placebo = gate_report({"a": good}, {}, daily, trials=["a"])
    assert no_placebo["survivors"] == []


def test_a_trial_that_did_not_run_still_counts_once(tmp_path):
    path = tmp_path / "round.json"
    write_rules(_payload(tmp_path), path)
    spec = load_round(path)
    assert count_unrun_trials(spec, ["a2"]) == ["a2"]
    assert count_unrun_trials(spec, ["a2"]) == []
    rows = read_ledger(spec.ledger)
    assert [row["trial_id"] for row in rows] == ["a2"] and rows[0]["role"] == "candidate" and rows[0]["annualised_sharpe"] is None


def test_a_holdout_is_read_once_whatever_the_freeze_file_is_called(tmp_path):
    ledger = tmp_path / "holdouts.jsonl"
    record_holdout_read(ledger, candidate="k01", cells=("V1", "V2", "V3"), digest="d", created_at="2026-11-06")
    assert holdouts_spent(ledger) == ["V1", "V2", "V3"]
    with pytest.raises(PermissionError):
        record_holdout_read(ledger, candidate="k02", cells=("V3",), digest="e", created_at="2026-11-07")
    record_holdout_read(ledger, candidate="k02", cells=("P",), digest="e", created_at="2026-11-07")


def test_a_second_candidate_can_not_freeze_once_the_holdouts_are_spent(tmp_path):
    path = tmp_path / "round.json"
    write_rules(_payload(tmp_path), path)
    spec = load_round(path)
    ledger = tmp_path / "holdouts.jsonl"
    freeze, digest = stage_freeze(spec, {"trial": "a1"}, holdout_ledger=ledger)
    assert freeze.name == "freeze_a1.json" and digest
    with pytest.raises(FileExistsError):
        stage_freeze(spec, {"trial": "a1"}, holdout_ledger=ledger)
    record_holdout_read(ledger, candidate="a1", cells=("V3",), digest=digest, created_at="2026-11-06")
    with pytest.raises(PermissionError):
        stage_freeze(spec, {"trial": "a3"}, holdout_ledger=ledger)


@pytest.mark.parametrize("reads,passed", [
    ({"V1": {"sharpe": 0.1}, "V2": {"sharpe": 0.1}, "V3": {"sharpe": 0.5, "alpha_t": 2.0}}, True),
    ({"V1": {"sharpe": 0.0}, "V2": {"sharpe": 0.1}, "V3": {"sharpe": 0.5, "alpha_t": 2.0}}, False),
    ({"V1": {"sharpe": 0.1}, "V2": {"sharpe": 0.1}, "V3": {"sharpe": 0.49, "alpha_t": 2.0}}, False),
    ({"V1": {"sharpe": 0.1}, "V2": {"sharpe": 0.1}, "V3": {"sharpe": 0.5, "alpha_t": 1.99}}, False),
    ({"V1": {"sharpe": 0.1}, "V2": {"sharpe": None}, "V3": {"sharpe": 0.5, "alpha_t": 2.0}}, False),
    ({"V1": {"sharpe": 0.1}, "V2": {"sharpe": float("nan")}, "V3": {"sharpe": 0.5, "alpha_t": 2.0}}, False),
    ({}, False),
])
def test_r_hold1_clauses(reads, passed):
    assert r_hold1(reads)["passed"] is passed


def test_pbo_report_names_what_is_absent_and_reads_a_late_trial_as_flat():
    rng = np.random.default_rng(4)
    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2011-01-03", periods=800)]
    frame = pd.DataFrame(rng.normal(size=(800, 6)), index=dates, columns=list("abcdef"))
    frame.iloc[:400, 5] = np.nan
    report = pbo_report([frame], [*"abcdef", "gone"], window=(dates[0], dates[-1]), blocks=8)
    assert report["num_trials"] == 6 and report["absent"] == ["gone"] and 0.0 <= report["pbo"] <= 1.0


@pytest.mark.skipif(not (V660 / "selection_daily_r2.parquet").exists() or not (V660 / "selection_scores_r2.json").exists(), reason="needs round 2's stored evidence")
def test_the_runner_recomputes_round_two_exactly():
    pytest.importorskip("pyarrow")
    scores = json.loads((V660 / "selection_scores_r2.json").read_text(encoding="utf-8"))
    placebos_path = V660 / "selection_placebos_r2.json"
    placebos = json.loads(placebos_path.read_text(encoding="utf-8")) if placebos_path.exists() else {}
    daily = pd.read_parquet(V660 / "selection_daily_r2.parquet")
    gate = gate_report(scores, placebos, daily, trials=list(scores))
    stored = json.loads((V660 / "selection_gate_r2.json").read_text(encoding="utf-8"))
    for key in ("survivors", "failed", "failed_earlier_clauses", "unscored"):
        assert gate[key] == stored[key], key
    rules = json.loads((V660 / "rules.json").read_text(encoding="utf-8"))
    prior = rules["trials"]["pbo_columns"]
    pbo = pbo_report([pd.read_parquet(V660 / "selection_daily.parquet"), daily], [*prior, *scores], window=("2011-01-01", "2018-12-31"), blocks=16)
    assert pbo["pbo"] == pytest.approx(json.loads((V660 / "selection_pbo_r2.json").read_text(encoding="utf-8"))["pbo"])
