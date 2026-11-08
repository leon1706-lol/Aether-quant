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
    _write_verdict(spec, survivors=["a1", "a3"], pbo=0.3)
    freeze, digest = stage_freeze(spec, {"trial": "a1"}, holdout_ledger=ledger)
    assert freeze.name == "freeze_a1.json" and digest
    with pytest.raises(FileExistsError):
        stage_freeze(spec, {"trial": "a1"}, holdout_ledger=ledger)
    record_holdout_read(ledger, candidate="a1", cells=("V3",), digest=digest, created_at="2026-11-06")
    with pytest.raises(PermissionError):
        stage_freeze(spec, {"trial": "a3"}, holdout_ledger=ledger)


def _write_verdict(spec, *, survivors, pbo):
    from evaluation.research_round import _paths

    paths = _paths(spec)
    paths["gate"].parent.mkdir(parents=True, exist_ok=True)
    paths["gate"].write_text(json.dumps({"survivors": survivors}), encoding="utf-8")
    paths["pbo"].write_text(json.dumps({"pbo": pbo}), encoding="utf-8")


def test_a_freeze_needs_a_stored_survivor_and_a_pbo_below_half(tmp_path):
    path = tmp_path / "round.json"
    write_rules(_payload(tmp_path), path)
    spec = load_round(path)
    ledger = tmp_path / "holdouts.jsonl"
    with pytest.raises(PermissionError, match="not a survivor"):
        stage_freeze(spec, {"trial": "a1"}, holdout_ledger=ledger)
    _write_verdict(spec, survivors=["a1"], pbo=0.5)
    with pytest.raises(PermissionError, match="PBO"):
        stage_freeze(spec, {"trial": "a1"}, holdout_ledger=ledger)
    _write_verdict(spec, survivors=["a2"], pbo=0.2)
    with pytest.raises(PermissionError, match="not a survivor"):
        stage_freeze(spec, {"trial": "a1"}, holdout_ledger=ledger)
    assert not (spec.out_dir / "freeze_a1.json").exists()


def test_a_crypto_read_leaves_the_equity_holdouts_open_and_a_second_crypto_read_is_shut(tmp_path):
    crypto = {**_payload(tmp_path), "cell": "CS", "name": "c", "out_dir": str(tmp_path / "out_c")}
    equity = {**_payload(tmp_path), "name": "e", "out_dir": str(tmp_path / "out_e")}
    path_c, path_e = tmp_path / "c.json", tmp_path / "e.json"
    write_rules(crypto, path_c)
    write_rules(equity, path_e)
    spec_c, spec_e = load_round(path_c), load_round(path_e)
    ledger = tmp_path / "holdouts.jsonl"
    _write_verdict(spec_c, survivors=["a1", "a3"], pbo=0.1)
    _write_verdict(spec_e, survivors=["a1"], pbo=0.1)
    _, digest = stage_freeze(spec_c, {"trial": "a1"}, holdout_ledger=ledger)
    record_holdout_read(ledger, candidate="a1", cells=("CV",), digest=digest, created_at="2026-11-08")
    stage_freeze(spec_e, {"trial": "a1"}, holdout_ledger=ledger)  # the equity holdouts are untouched by a crypto read
    with pytest.raises(PermissionError):
        stage_freeze(spec_c, {"trial": "a3"}, holdout_ledger=ledger)


def test_r_hold1_crypto_needs_both_clauses_and_a_missing_figure_fails():
    from evaluation.research_round import r_hold1_crypto

    assert r_hold1_crypto({"CV": {"sharpe": 0.6, "alpha_t": 2.1}})["passed"] is True
    assert r_hold1_crypto({"CV": {"sharpe": 0.6, "alpha_t": 1.9}})["passed"] is False
    assert r_hold1_crypto({"CV": {"sharpe": 0.49, "alpha_t": 3.0}})["passed"] is False
    assert r_hold1_crypto({"CV": {"sharpe": None, "alpha_t": 3.0}})["passed"] is False
    assert r_hold1_crypto({})["passed"] is False


def test_a_trial_without_an_ic_clause_or_with_its_own_minimum_is_judged_by_its_own_terms():
    from evaluation.research_round import clause_overrides

    score = {"id": "x10", "sharpe": 0.7, "sharpe_first_half": 0.6, "sharpe_second_half": 0.6, "live_names": {"median": 2.0}, "ic": None}
    assert passes_earlier_clauses(score, min_live_names=12) is False
    assert passes_earlier_clauses(score, min_live_names=2, no_ic=True) is True
    assert passes_earlier_clauses(score, min_live_names=2) is False, "without the exemption the IC clause still binds"
    spec = type("Spec", (), {"trials": {"x10": {"min_live_names": 2}, "x01": {}}, "no_ic_clause": ("x10",)})()
    assert clause_overrides(spec) == {"x10": {"min_live_names": 2, "no_ic": True}}
    daily = pd.DataFrame({"x10": np.random.default_rng(0).normal(0.001, 0.01, 300)})
    gate = gate_report({"x10": score}, {"x10": {"asset_block": {"p": 0.01}, "time_shift": {"p": 0.01}}}, daily, trials=["x10"], min_live_names=12, overrides=clause_overrides(spec))
    assert gate["survivors"] == ["x10"]
    assert gate_report({"x10": score}, {"x10": {"asset_block": {"p": 0.01}}}, daily, trials=["x10"], min_live_names=12)["survivors"] == [], "no overrides: the old rule"


def test_a_gated_trial_counts_live_names_where_its_gate_is_on():
    from evaluation.research_round import live_rows
    from portfolio.wide_signals import live_names_per_rebalance

    index = [f"d{i:03d}" for i in range(100)]
    table = pd.DataFrame(np.nan, index=index, columns=list("ABCDEFGHIJKLMN"))
    table.iloc[:30] = 1.0  # the gate is on for the first 30 rows only
    assert live_names_per_rebalance(table, 5)["median"] == 0.0, "counted over every row the gate reads as no names"
    assert live_names_per_rebalance(live_rows(table, {"gate": "regime"}), 5)["median"] == 14.0
    assert live_rows(table, {}) is table, "an ungated trial counts every row, as before"


def _crypto_spec_cell(seed: int = 5):
    """A fake cell with a coin panel for the builder trials."""
    days = [day.strftime("%Y-%m-%d") for day in pd.date_range("2021-01-01", periods=300)]
    coins = ["BTCUSD", "ETHUSD", "AAAUSD", "BBBUSD"]
    steps = np.random.default_rng(seed).normal(0.001, 0.03, (300, 4))
    known = pd.DataFrame(100.0 * np.exp(np.cumsum(steps, axis=0)), index=days, columns=coins)
    cell = _Cell()
    cell.context = _Context(known)
    cell.member = pd.DataFrame(True, index=days, columns=coins)
    cell.features = {"liquid": cell.member, "quote_volume": pd.DataFrame(1e6, index=days, columns=coins)}
    cell.root = None
    cell.data_dir = ""
    return cell, days


def test_a_named_builder_makes_the_trials_table_and_a_gate_can_switch_it_off(tmp_path):
    cell, days = _crypto_spec_cell()
    payload = _payload(tmp_path)
    payload["trials"] = {
        "x01": {"kind": "cross_sectional", "rebalance_every": 20, "builder": "low_vol", "params": {"window": 30}},
        "x12": {"kind": "cross_sectional", "rebalance_every": 20, "builder": "low_vol", "params": {"window": 30}, "gate": "regime"},
        "x99": {"kind": "cross_sectional", "rebalance_every": 20, "builder": "similarity_table", "params": {}},
    }
    path = tmp_path / "round.json"
    write_rules(payload, path)
    spec = load_round(path)
    plain = trial_table(spec, "x01", cell, {}, score_dir=tmp_path)
    gated = trial_table(spec, "x12", cell, {}, score_dir=tmp_path)
    assert plain.iloc[60:].notna().all().all() and gated.isna().all(axis=1).any() and gated.notna().any().any()
    assert trial_table(spec, "x99", cell, {}, score_dir=tmp_path) is None, "a builder whose input file is absent is a trial that did not run"
    cut = 200
    changed, _ = _crypto_spec_cell()
    changed.context.panel.known.iloc[cut:] *= 4.0
    pd.testing.assert_frame_equal(plain.iloc[:cut], trial_table(spec, "x01", changed, {}, score_dir=tmp_path).iloc[:cut])
    pd.testing.assert_frame_equal(gated.iloc[:cut], trial_table(spec, "x12", changed, {}, score_dir=tmp_path).iloc[:cut])


def test_an_unknown_builder_is_an_error_not_a_different_trial(tmp_path):
    cell, _ = _crypto_spec_cell()
    payload = _payload(tmp_path)
    payload["trials"] = {"bad": {"kind": "pooled", "rebalance_every": 20, "builder": "os.system"}}
    path = tmp_path / "round.json"
    write_rules(payload, path)
    with pytest.raises(KeyError):
        trial_table(load_round(path), "bad", cell, {}, score_dir=tmp_path)


def test_every_trial_kind_and_universe_resolves(tmp_path):
    from evaluation.research_round import KINDS, universe_for

    assert set(KINDS) == {"pooled", "cross_sectional", "time_series", "direct"}
    payload = {**_payload(tmp_path), "cell": "CS", "name": "c"}
    payload["trials"] = {
        "x10": {"kind": "time_series", "rebalance_every": 5, "builder": "core_constant"},
        "e5": {"kind": "direct", "rebalance_every": 21, "builder": "core_constant", "universe": ["benchmark"]},
    }
    path = tmp_path / "c.json"
    write_rules(payload, path)
    spec = load_round(path)
    assert universe_for(spec, "x10") == ("crypto",) and universe_for(spec, "e5") == ("benchmark",)


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


# --- V6.6.4 (Problems #336): a time-series or direct trial holds the assets it names, not the cell's members ---------------------------------------------

def test_a_time_series_trial_that_names_etfs_is_not_masked_to_index_members():
    from evaluation.research_round import tradable_mask

    cell = _Cell()  # TICKERS[0] is not a member
    table = _table(4)
    entry = {"kind": "time_series", "params": {"tickers": [TICKERS[0], TICKERS[1]]}}
    mask = tradable_mask(entry, table, cell)
    assert mask.shape == table.shape and bool(mask[TICKERS[0]].all()) and bool(mask[TICKERS[1]].all()) and not mask[TICKERS[2]].any()
    assert table.where(mask)[TICKERS[0]].notna().all(), "the non-member named asset survives"
    direct = tradable_mask({"kind": "direct", "params": {"ticker": TICKERS[0]}}, table, cell)
    assert bool(direct[TICKERS[0]].all()) and not direct[TICKERS[1]].any()


def test_pooled_cross_sectional_and_unnamed_time_series_trials_still_mask_to_members():
    from evaluation.research_round import tradable_mask

    cell = _Cell()
    for entry in ({"kind": "pooled"}, {"kind": "cross_sectional", "params": {"tickers": [TICKERS[0]]}}, {"kind": "time_series", "params": {"window": 5}}, {"kind": "time_series"}):
        assert tradable_mask(entry, _table(5), cell) is cell.member
