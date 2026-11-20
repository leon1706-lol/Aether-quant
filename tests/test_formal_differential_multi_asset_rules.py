"""evaluation/multi_asset_round's verdicts against their Lean 4 model (formal/AetherFormal/MultiAssetRules.lean), V6.6.10:
R-FLIP1's flip and shares, R-INSTALL3, and R-LOSS1's clauses."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from evaluation import multi_asset_round as mar


def _floats(mapping):
    return {key: (to_float(value) if isinstance(value, dict) or value is None else value) for key, value in mapping.items()}


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("multi_asset_rules")["cases"]):
        given, expected = case["input"], case["expected"]
        lean = _floats(given["lean"])
        flip = mar.flip_verdict(survivor="k01" if given["survivor"] else None, holdout=_floats(given["holdout"]), lean=lean,
                                parity=_floats(given["parity"]), pin_sharpe=to_float(given["pin_sharpe"]))
        assert flip["flip"] is expected["flip"], index
        assert flip["shares"]["model_book"] == pytest.approx(to_float(expected["model_share"])), index
        install = mar.install3_verdict(new_ic=to_float(given["new_ic"]), installed_ic=to_float(given["installed_ic"]), lean=lean)
        assert install["install"] is expected["install3"], index
        ics = [to_float(value) for value in given["class_ic"]]
        score = {"class_ic": dict(zip(mar.CLASSES, ics, strict=True)), "hac_t": to_float(given["hac_t"])}
        assert all(mar.loss_clauses(score, to_float(given["control_mean"])).values()) is expected["loss_survives"], index
