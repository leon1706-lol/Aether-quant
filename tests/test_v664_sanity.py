"""scripts/v664_sanity.py (V6.6.6): the crypto path's oracle, reversal and random signal, and the verdict on them."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import block_path_writes, load_script, run_script


def test_the_verdict_needs_a_large_oracle_a_negative_reversal_and_a_quiet_random():
    module = load_script("v664_sanity")
    report = lambda oracle, reverse, random: {"oracle": {"sharpe": oracle}, "reversed_oracle": {"sharpe": reverse}, "random": {"sharpe": random}}  # noqa: E731
    assert module.verdict(report(2.5, -2.2, 0.2))["path_can_see_an_edge"] is True
    failed = module.verdict(report(None, -0.5, 0.2))
    assert failed["checks"] == {"oracle_large": False, "reversal_negative": False, "random_near_zero": False}


@pytest.mark.parametrize(("sharpes", "code"), [({"oracle": 2.6, "reversed_oracle": -2.2, "random": 0.1}, 0), ({"oracle": 0.5, "reversed_oracle": -0.4, "random": 0.1}, 1)])
def test_run_as_a_script_it_scores_the_three_and_writes_the_verdict(monkeypatch, capsys, sharpes, code):
    import evaluation.premia_research as research
    import evaluation.wide_context as wide

    days = [f"2024-01-{day:02d}" for day in range(1, 31)]
    known = pd.DataFrame(np.linspace(1.0, 2.0, 60).reshape(30, 2), index=days, columns=["BTCUSD", "ETHUSD"])
    cell = SimpleNamespace(context=SimpleNamespace(panel=SimpleNamespace(known=known, extras={})), member=known.notna(),
                           cell=SimpleNamespace(start=days[0], split=days[15], end=days[-1]))
    monkeypatch.setattr(wide, "crypto_cell", lambda root, base, name: cell)
    monkeypatch.setattr(research, "score_sleeve", lambda spec, context, **kwargs: {"daily": [], "sharpe": sharpes[spec.id], "sharpe_first_half": 0.0,
                                                                                    "sharpe_second_half": 0.0, "mean_gross": 0.5, "turnover": 1.0})
    writes = block_path_writes(monkeypatch)
    assert run_script("v664_sanity", [], monkeypatch) == code
    (args,) = [args for method, path, args in writes if method == "write_text"]
    assert json.loads(args[0])["verdict"]["path_can_see_an_edge"] is (code == 0) and "oracle" in capsys.readouterr().out
