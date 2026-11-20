"""The V6.6.10 multi-asset push, as rules and verdicts (R-LOSS1, R-ALPHA1, R-BOOK2, R-INSTALL3, R-FLIP1).

The rule texts are written once (`model_book_round.write_rules`) and recorded in the vault before any score exists. Every verdict here
is a pure function of numbers a stage already wrote, so the decision a rule makes can be re-derived from the evidence files alone.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

CLASSES = ("equity", "bond", "forex", "crypto")
LOSS_TRIALS = {
    "L0": "soft_spearman",
    "L1": "listnet",
    "L2": "ic_pearson",
    "L3": "ls_sharpe",
    "L4": "class_balanced",
    "L5": "cost_aware",
}
LOSS_CONTROL = "L0"
LOSS_CLAUSES = {"ic_margin": 0.01, "min_classes_non_negative": 3, "min_hac_t": 2.0}
VERIFICATION_SEEDS = (1, 2)
INSTALL3 = {"pin_sharpe": 0.57, "max_drawdown": 0.15}
FLIP1 = {
    "holdout_sharpe": 0.40, "holdout_drawdown": 0.15, "holdout_volatility": 0.10,
    "crypto_alone_sharpe": 0.65, "pin_margin": 0.05, "lean_volatility": 0.10, "lean_drawdown": 0.15,
    "lean_correlation": 0.95, "lean_return_gap": 0.01,
}
FLIP_SHARES = {"model_book": 0.70, "crypto_sleeve": 0.30}
FLIP_WINDOW = ("2023-07-01", "2026-11-02")

RULES_TEXT = {
    "R-LOSS1": (
        "Six sequence-model trials L0-L5, each trained by train_sequence.py --memory-profile low with seed 0 on the retrained stack's own dataset "
        "(train 2014-2021, validation 2022-2023, the config's universe without EOSUSD); the multitask MLP and gating stay as in g0007. "
        "L0 soft_spearman (the control, counted), L1 listnet, L2 ic_pearson (minus the mean per-date Pearson correlation of prediction and realised rank), "
        "L3 ls_sharpe (minus the Sharpe across a batch's dates of a softmax(temperature 0.1) long-short book on the realised forward return), "
        "L4 class_balanced (soft_spearman within each date and asset class, classes weighted equally), L5 cost_aware (L4 plus 0.1 times the mean absolute "
        "change of a ticker's predicted rank between consecutive dates). Score on the validation window: the non-overlapping (every 20th session) rank IC of "
        "rank_20d per class (equity, bond, forex, crypto) and the pooled Newey-West t (lag 4). A variant L1-L5 survives iff its mean class IC >= L0's + 0.01, "
        "at least 3 of 4 classes have IC >= 0, and its pooled t >= 2.0. The best survivor by mean class IC is retrained with seeds 1 and 2 (role verification) "
        "and kept iff the three seeds' mean still passes every clause. With none kept, R-BOOK2 uses L0. Disclosure: the validation window also early-stops "
        "every trainer, so it is not clean for any of them; it is the same for all six."
    ),
    "R-ALPHA1": (
        "Diagnostics only, no selection and no trial count: on the selection window's walk-forward scores of the model R-LOSS1 keeps, the IC term structure "
        "(1, 5, 10, 20, 40 and 60 sessions), its half-life, the IC by class, year and regime, the turnover-adjusted IC at 10 bps, the exposure to momentum 12-1, "
        "low volatility, carry and market beta, the residual IC after them, and breadth. It informs the R-BOOK2 list, which is written and recorded before any "
        "R-BOOK2 score."
    ),
    "R-BOOK2": (
        "8 to 10 trials on the selection window (2019-01-01..2023-06-30, halves at 2021-04-01), built from the kept model's walk-forward scores, listed in "
        "rules_book2.json and recorded in the vault before any score. Controls b03 (re-scored with the new scores) and core are scored and never selected. "
        "Gate: R-SLEEVE2 unchanged from V6.6.9, with N counting every v6610 trial."
    ),
    "R-INSTALL3": (
        "The retrained stack (g0007) replaces the installed models iff, on the verification window 2023-07-01..2026-11-02 with b03 unchanged, the mean over the "
        "four classes of ml_a1's non-overlapping 20-session rank IC is >= the installed models', and the Lean run of the shipped 70/30 book with g0007 completes "
        "with a clean engine log, Sharpe >= 0.57 (pin 2026-11-16_16-25-28) and max drawdown <= 15%. An R-BOOK2 survivor replaces b03 at the same 30% iff "
        "R-INSTALL2's eligibility and Lean clauses hold for it. Otherwise nothing changes."
    ),
    "R-FLIP1": (
        "The shares become 70% model book and 30% crypto sleeve iff one R-BOOK2 survivor, frozen before any row after 2023-06-30 is read for it, meets all of: "
        "(a) it passes R-SLEEVE2; (b) on one read of 2023-07-01..2026-11-02, net Sharpe >= 0.40, max drawdown <= 15%, annual volatility <= 10%; "
        "(c) the Lean run of the 70/30 blend completes with a clean engine log, Sharpe >= 0.65 (the crypto sleeve alone) and >= the current pin's 0.57 + 0.05, "
        "annual volatility <= 10%, max drawdown <= 15%; (d) Lean against the engine keeps daily correlation >= 0.95 and an annual return gap <= 100 bps. "
        "Otherwise the shares stay 30% model book and 70% crypto sleeve, and no text calls the book multi-asset-led. Disclosure: no clean multi-asset holdout "
        "exists (V1, V2, V3, P and CV are cells of the wide equity and crypto universes); the window in (b) was read by earlier books, never by this one."
    ),
}


def rules_payload(*, written: str) -> dict[str, Any]:
    """Everything V6.6.10 fixes before a score exists."""
    return {
        "written": written,
        "phase": "v6610",
        "loss_trials": dict(LOSS_TRIALS),
        "loss_clauses": dict(LOSS_CLAUSES),
        "verification_seeds": list(VERIFICATION_SEEDS),
        "install3": dict(INSTALL3),
        "flip1": dict(FLIP1),
        "flip_shares": dict(FLIP_SHARES),
        "flip_window": list(FLIP_WINDOW),
        "rules": dict(RULES_TEXT),
    }


# R-BOOK2's list (V6.6.10), from R-ALPHA1 on g0007's walk-forward scores: ml_a2 is the one table with a pooled 20-session IC whose
# HAC t clears 2 (equity its strongest class), its IC holds to 40 sessions (half-life about 57 sessions, hence the 40-session
# cadence), ml_a3 carries the bond IC, and ml_a1 (what b03 trades) is the weakest. (id, optimizer, every, table, extra params)
BOOK2_TRIALS = (
    ("n01", "inverse_vol", 20, "ml_a2", {}),
    ("n02", "inverse_vol", 40, "ml_a2", {}),
    ("n03", "class_risk_parity", 20, "ml_a2", {}),
    ("n04", "pooled", 20, "ml_a2", {}),
    ("n05", "tilted_core", 20, "ml_a2", {"kappa": 0.25}),
    ("n06", "tilted_core", 20, "ml_a2", {"kappa": 0.5}),
    ("n07", "inverse_vol", 20, "mix_a23", {}),
    ("n08", "inverse_vol", 20, "ml_a3", {}),
    ("n09", "class_risk_parity", 40, "mix_a23", {}),
)
BOOK2_CONTROLS = (("n00", "inverse_vol", 20, "ml_a1", {}), ("core", "core", 20, "const", {}))  # b03 re-scored, and the model-free core


def _book2_spec(trial: str, optimizer: str, every: int, table: str, extra: Mapping[str, Any], *, track: str) -> Any:
    from evaluation.model_book_research import GUARD
    from portfolio.premia_signals import XS, SleeveSpec

    return SleeveSpec(trial, track, XS, "external_score", CLASSES, every, {"table": table, **GUARD, "optimizer": optimizer, **extra})


def book2_trials() -> list[Any]:
    """R-BOOK2's selectable trials, as the model-book stages score them."""
    return [_book2_spec(*entry, track="B2") for entry in BOOK2_TRIALS]


def book2_controls() -> list[Any]:
    """R-BOOK2's controls: scored, never selected, counted in no N."""
    return [_book2_spec(*entry, track="B2C") for entry in BOOK2_CONTROLS]


def book2_rules_payload(*, written: str, alpha: Mapping[str, Any]) -> dict[str, Any]:
    """The R-BOOK2 rules file: the list, the controls, the gate and the R-ALPHA1 numbers the list was drawn from, written and recorded in
    the vault before any R-BOOK2 score."""
    return {
        "written": written, "phase": "v6610", "rule": "R-BOOK2", "text": RULES_TEXT["R-BOOK2"], "counted_trials": len(BOOK2_TRIALS),
        "trials": {entry[0]: {"optimizer": entry[1], "every": entry[2], "table": entry[3], **entry[4]} for entry in BOOK2_TRIALS},
        "controls": {entry[0]: {"optimizer": entry[1], "every": entry[2], "table": entry[3]} for entry in BOOK2_CONTROLS},
        "gate": "R-SLEEVE2 unchanged from V6.6.9 (pooled Sharpe >= 0.50, both halves >= 0.40, every placebo p < 0.05, correlation <= 0.7, "
                "at most 5 survivors), then PBO < 0.5; only a survivor can be frozen",
        "alpha_basis": dict(alpha),
    }


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def mean_class_ic(class_ic: Mapping[str, Any]) -> float | None:
    """The mean of the four classes' IC; None unless every class has a finite IC (a class with no score is not a zero)."""
    values = [_finite(class_ic.get(name)) for name in CLASSES]
    if any(value is None for value in values):
        return None
    return sum(values) / len(values)  # type: ignore[arg-type]


def loss_clauses(score: Mapping[str, Any], control_mean: float, *, clauses: Mapping[str, float] = LOSS_CLAUSES) -> dict[str, bool]:
    """R-LOSS1's three clauses for one variant's score {"class_ic": {class: ic}, "hac_t": t} against the control's mean class IC."""
    mean = mean_class_ic(score.get("class_ic", {}))
    hac_t = _finite(score.get("hac_t"))
    class_values = [_finite(score.get("class_ic", {}).get(name)) for name in CLASSES]
    non_negative = sum(1 for value in class_values if value is not None and value >= 0.0)
    return {
        "ic_margin": mean is not None and mean >= control_mean + float(clauses["ic_margin"]),
        "classes": non_negative >= int(clauses["min_classes_non_negative"]),
        "hac_t": hac_t is not None and hac_t >= float(clauses["min_hac_t"]),
    }


def loss_gate(scores: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """R-LOSS1's gate over every variant's score. Returns the survivors, the best of them (by mean class IC) and why each failed."""
    control = scores.get(LOSS_CONTROL)
    control_mean = mean_class_ic(control.get("class_ic", {})) if control else None
    if control_mean is None:
        return {"control_mean": None, "survivors": [], "best": None, "failed": {name: "no control" for name in scores if name != LOSS_CONTROL}}
    survivors: list[tuple[float, str]] = []
    failed: dict[str, str] = {}
    for name in sorted(scores):
        if name == LOSS_CONTROL:
            continue
        verdict = loss_clauses(scores[name], control_mean)
        if all(verdict.values()):
            survivors.append((mean_class_ic(scores[name]["class_ic"]), name))  # type: ignore[arg-type]
        else:
            failed[name] = ",".join(clause for clause, ok in verdict.items() if not ok)
    survivors.sort(key=lambda item: (-item[0], item[1]))
    return {"control_mean": control_mean, "survivors": [name for _, name in survivors], "best": survivors[0][1] if survivors else None, "failed": failed}


def seed_mean_score(seed_scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The mean over seeds of each class IC and of the t statistic; a class missing in any seed stays missing."""
    if not seed_scores:
        raise ValueError("no seed scores")
    class_ic: dict[str, float | None] = {}
    for name in CLASSES:
        values = [_finite(score.get("class_ic", {}).get(name)) for score in seed_scores]
        class_ic[name] = None if any(value is None for value in values) else sum(values) / len(values)  # type: ignore[arg-type]
    t_values = [_finite(score.get("hac_t")) for score in seed_scores]
    hac_t = None if any(value is None for value in t_values) else sum(t_values) / len(t_values)  # type: ignore[arg-type]
    return {"class_ic": class_ic, "hac_t": hac_t}


def loss_verdict(scores: Mapping[str, Mapping[str, Any]], verification: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The model R-BOOK2 uses: the best survivor when its seed-0 score and the verification seeds' scores still pass on their mean, else L0."""
    gate = loss_gate(scores)
    best = gate["best"]
    if best is None:
        return {**gate, "kept": LOSS_CONTROL, "verified": False, "reason": "no variant survived"}
    if not verification:
        return {**gate, "kept": LOSS_CONTROL, "verified": False, "reason": f"{best} survived; its verification seeds have not been scored"}
    mean = seed_mean_score([scores[best], *verification])
    verdict = loss_clauses(mean, gate["control_mean"])
    if all(verdict.values()):
        return {**gate, "kept": best, "verified": True, "seed_mean": mean, "reason": f"{best} survived and its three-seed mean still passes"}
    return {**gate, "kept": LOSS_CONTROL, "verified": False, "seed_mean": mean, "reason": f"{best}'s three-seed mean fails: " + ",".join(k for k, ok in verdict.items() if not ok)}


def loss_score(frame: Any, asset_class: Mapping[str, str], *, stride: int = 20, lags: int = 4, min_names: int = 3) -> dict[str, Any]:
    """R-LOSS1's score of one trained variant from its validation rows (columns date, ticker, prediction, target): the mean rank IC of
    each class over every `stride`-th date (non-overlapping for a 20-session label) and the Newey-West t (`lags`) of the pooled IC on
    the same dates."""
    import pandas as pd

    from evaluation.alpha_behaviour import session_rank_ic
    from evaluation.rank_ic_core import newey_west_t_stat

    prediction = frame.pivot_table(index="date", columns="ticker", values="prediction", aggfunc="last").sort_index()
    target = frame.pivot_table(index="date", columns="ticker", values="target", aggfunc="last").reindex_like(prediction)
    dates = list(prediction.index[::max(1, int(stride))])
    prediction, target = prediction.loc[dates], target.loc[dates]
    class_ic: dict[str, float | None] = {}
    for name in CLASSES:
        members = [ticker for ticker in prediction.columns if asset_class.get(ticker) == name]
        series = session_rank_ic(prediction[members], target[members], min_names=min_names).dropna() if members else pd.Series(dtype=float)
        class_ic[name] = float(series.mean()) if len(series) else None
    pooled = session_rank_ic(prediction, target, min_names=min_names).dropna()
    hac_t = float(newey_west_t_stat(pooled.to_numpy(), lags=lags)) if len(pooled) > 1 else None
    return {"class_ic": class_ic, "hac_t": hac_t, "dates": len(dates), "pooled_ic": float(pooled.mean()) if len(pooled) else None}


def install3_verdict(*, new_ic: float | None, installed_ic: float | None, lean: Mapping[str, Any] | None) -> dict[str, Any]:
    """R-INSTALL3 for the retrained stack. `lean` holds the Lean run's {"completed", "log_clean", "sharpe", "max_drawdown"}."""
    reasons = []
    if new_ic is None or installed_ic is None or new_ic < installed_ic:
        reasons.append("ic")
    lean = lean or {}
    if not (lean.get("completed") and lean.get("log_clean")):
        reasons.append("lean_run")
    sharpe, drawdown = _finite(lean.get("sharpe")), _finite(lean.get("max_drawdown"))
    if sharpe is None or sharpe < INSTALL3["pin_sharpe"]:
        reasons.append("sharpe")
    if drawdown is None or drawdown > INSTALL3["max_drawdown"]:
        reasons.append("drawdown")
    return {"install": not reasons, "failed": reasons}


def flip_verdict(*, survivor: str | None, holdout: Mapping[str, Any] | None, lean: Mapping[str, Any] | None, parity: Mapping[str, Any] | None,
                 pin_sharpe: float = INSTALL3["pin_sharpe"]) -> dict[str, Any]:
    """R-FLIP1. `holdout` holds the one verification read {"sharpe", "max_drawdown", "volatility"}; `lean` the 70/30 run's
    {"completed", "log_clean", "sharpe", "volatility", "max_drawdown"}; `parity` Lean against the engine {"correlation", "annual_return_gap"}."""
    failed: list[str] = []
    if survivor is None:
        failed.append("a")
    holdout, lean, parity = holdout or {}, lean or {}, parity or {}
    h_sharpe, h_dd, h_vol = (_finite(holdout.get(key)) for key in ("sharpe", "max_drawdown", "volatility"))
    if h_sharpe is None or h_sharpe < FLIP1["holdout_sharpe"] or h_dd is None or h_dd > FLIP1["holdout_drawdown"] or h_vol is None or h_vol > FLIP1["holdout_volatility"]:
        failed.append("b")
    l_sharpe, l_vol, l_dd = (_finite(lean.get(key)) for key in ("sharpe", "volatility", "max_drawdown"))
    floor = max(FLIP1["crypto_alone_sharpe"], pin_sharpe + FLIP1["pin_margin"])
    if (not (lean.get("completed") and lean.get("log_clean")) or l_sharpe is None or l_sharpe < floor
            or l_vol is None or l_vol > FLIP1["lean_volatility"] or l_dd is None or l_dd > FLIP1["lean_drawdown"]):
        failed.append("c")
    correlation, gap = _finite(parity.get("correlation")), _finite(parity.get("annual_return_gap"))
    if correlation is None or correlation < FLIP1["lean_correlation"] or gap is None or abs(gap) > FLIP1["lean_return_gap"]:
        failed.append("d")
    flip = not failed
    return {"flip": flip, "failed": failed, "shares": dict(FLIP_SHARES) if flip else {"model_book": 0.30, "crypto_sleeve": 0.70}, "sharpe_floor": floor}
