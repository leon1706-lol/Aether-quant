"""scripts/cycle_decide.py (V6.6.6): a host's decision for a generation that needs one, written once, never with a bad weight."""

from __future__ import annotations

import json
import shutil

import pytest

from script_loader import ROOT, load_script


def _weights(tmp_path, rows):
    path = tmp_path / "weights.csv"
    path.write_text("ticker,weight\n" + "".join(f"{ticker},{weight}\n" for ticker, weight in rows), encoding="utf-8")
    return path


def test_a_decision_is_written_once_and_only_for_a_generation_that_needs_a_host(tmp_path, capsys):
    module = load_script("cycle_decide")
    registry = tmp_path / "registry.json"
    shutil.copyfile(ROOT / "ml" / "generations" / "registry.json", registry)
    ledger = tmp_path / "decisions.jsonl"
    weights = _weights(tmp_path, [("AAA", 0.1), ("BBB", -0.05)])
    argv = ["--registry", str(registry), "--generation", "g0005", "--weights", str(weights), "--ledger", str(ledger), "--session", "2026-11-13"]
    assert module.main(argv) == 0 and "2026-11-13 g0005: 2 weights" in capsys.readouterr().out
    assert module.main(argv) == 0 and "already decided" in capsys.readouterr().out
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert row["payload"]["decided"] == {"AAA": 0.1, "BBB": -0.05} and row["payload"]["vintage"] is None

    with pytest.raises(ValueError, match="decides on the runner"):
        module.write_decision(registry, "g0001", {}, ledger, session="s", created_at="t")
    with pytest.raises(KeyError, match="g9999"):
        module.write_decision(registry, "g9999", {}, ledger, session="s", created_at="t")


def test_a_non_finite_weight_never_reaches_the_record(tmp_path):
    module = load_script("cycle_decide")
    with pytest.raises(ValueError, match="non-finite weight for BBB"):
        module.read_weights(_weights(tmp_path, [("AAA", 0.1), ("BBB", "nan")]))
