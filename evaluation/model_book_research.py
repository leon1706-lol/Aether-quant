"""The multi-asset model book's research, as pure functions (V6.6.9).

The research engine (`evaluation/premia_research.py`) scores a sleeve whose signal is a table by session and ticker. This module
builds those tables from the models' walk-forward scores (aligned to the session they could be used at), the composites the rules
name, and decides what the pre-registered rules decide: which trials are eligible, which one is the candidate, whether it installs.
Nothing here reads a file the rules have not fixed, and nothing here knows the dates of a holdout.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from portfolio.model_book import (  # noqa: F401  (re-exported: the research and the live book build their rows from one definition)
    blend_rows,
    composite_signal,
    forward_fill_rows,
    low_volatility_score,
    momentum_12_1,
    signal_tables,
    trend_vote,
    within_class_z,
)
from portfolio.premia_signals import XS, SleeveSpec, WeightSettings, align_score_table
from portfolio.target_weights import NEXT_BAR_CLASSES

CLASSES = ("equity", "bond", "forex", "crypto")
SELECTION = ("2019-01-01", "2021-04-01", "2023-06-30")
VERIFICATION = ("2023-07-01", "2026-11-02")
STALE_SCORE_ROWS = 5  # a crypto or forex score older than this many calendar rows is not carried forward
NON_SURVIVOR_SHARE = 0.30
HEADS = ("rank_20d", "rank_5d", "sector_neutral_rank_20d")

# the forex name cap is 6%: a pair under $5,000 of a $100,000 book is below `forex_min_trade_usd` and could never open (audit item 4)
MODEL_SETTINGS = {
    "target_vol": 0.07, "gross_cap": 1.4, "name_cap": 0.05,
    "class_caps": {"equity": 0.80, "bond": 0.60, "crypto": 0.15, "forex": 0.12},
    "name_cap_by_class": {"crypto": 0.05, "forex": 0.06},
}
GUARD = {"guard_classes": ["forex"], "guard_lookback": 60, "guard_max_loss": 0.01}
ELIGIBLE = {"max_drawdown": 0.15, "volatility": 0.10, "mean_gross": 2.0, "class_breadth": 0.80}
LEAN_VS_ENGINE = {"correlation": 0.90, "annual_return_gap": 0.01}


def model_settings() -> WeightSettings:
    """The sizing every model-book trial shares (R-BOOK1 fixes it before any score)."""
    return WeightSettings(**MODEL_SETTINGS)


def universe_tickers(config: Mapping[str, Any]) -> list[str]:
    """The tickers the config's universe holds now. The installed models were trained with EOSUSD still present (#385); a score
    for a ticker the universe no longer lists is never ranked."""
    return [str(asset["ticker"]) for asset in config["phase1"]["universe"]["assets"]]


def load_score_table(
    path: Path | str, sessions: Sequence[str], asset_class: Mapping[str, str], *, universe: Iterable[str] | None = None, end: str | None = None,
) -> pd.DataFrame:
    """A score file (`date,ticker,score`, keyed by dataset date) as a table by session, usable at that session (#390).

    A crypto or forex score dated D reads bar D, which closes after D's equity decision, so it moves to the next row: the
    columns are carried over the calendar rows first (a Friday forex score serves Monday's decision) and then shifted one row
    through `align_score_table`. An equity or bond score dated D is the close of D and stays. Every score table the model book's
    research reads comes through here."""
    table = pd.read_csv(path, dtype={"date": str, "ticker": str})
    if end is not None:
        table = table[table["date"] <= end]
    if universe is not None:
        table = table[table["ticker"].isin(set(universe))]
    wide = table.pivot_table(index="date", columns="ticker", values="score", aggfunc="last").sort_index()
    wide = wide.reindex(sorted(set(wide.index) | set(map(str, sessions))))
    late = [ticker for ticker in wide.columns if asset_class.get(ticker) in NEXT_BAR_CLASSES]
    wide[late] = wide[late].ffill(limit=STALE_SCORE_ROWS)
    return align_score_table(wide, asset_class).reindex(list(sessions))


def _spec(trial: str, track: str, optimizer: str | None, every: int, table: str = "ml_a1", **extra: Any) -> SleeveSpec:
    params: dict[str, Any] = {"table": table, **GUARD, **extra}
    if optimizer is not None:
        params["optimizer"] = optimizer
    return SleeveSpec(trial, track, XS, "external_score", CLASSES, every, params)


def book_trials() -> list[SleeveSpec]:
    """R-BOOK1: twelve optimizer trials on one signal (`ml_a1`). The signal is fixed so that only the optimizer varies."""
    return [
        _spec("b02", "B1", "pooled", 20),
        _spec("b03", "B1", "inverse_vol", 20),
        _spec("b04", "B1", "class_risk_parity", 20),
        _spec("b05", "B1", "hrp", 20),
        _spec("b06", "B1", "mean_variance", 20),
        _spec("b07", "B1", "tilted_core", 20, kappa=1.0),
        _spec("b08", "B1", "tilted_core", 20, "mix_trend", kappa=1.0),
        _spec("b09", "B1", "inverse_vol", 5),
        _spec("b10", "B1", "class_risk_parity", 5),
        _spec("b11", "B1", "tilted_core", 5, kappa=1.0),
        _spec("b12", "B1", "class_risk_parity", 20, partial=0.5),
        _spec("b13", "B1", "tilted_core", 20, kappa=1.0, band=0.25),
    ]


def mix_trials() -> list[SleeveSpec]:
    """R-MIX1: six signal trials on one optimizer (pooled ranks, every 20 sessions)."""
    return [
        _spec("m01", "M1", "pooled", 20, "mix_mom"),
        _spec("m02", "M1", "pooled", 20, "mix_lowvol"),
        _spec("m03", "M1", "pooled", 20, "mix_trend"),
        _spec("m04", "M1", "pooled", 20, vix_halve=0.95),
        _spec("m05", "M1", "pooled", 20, "mix_all4"),
        _spec("m06", "M1", "pooled", 20, "mix_a23"),
    ]


def control_trials() -> list[SleeveSpec]:
    """Scored, never selectable, counted in no N: V6.5.0's top-6 book through the aligned loader, and the model-free risk-parity core."""
    return [
        SleeveSpec("b01", "BC", XS, "external_score", CLASSES, 20, {"table": "ml_a1", "top_k": 6}),
        _spec("core", "BC", "core", 20, "const"),
    ]


CONTROL_IDS = ("b01", "core")


def candidate_pool() -> list[SleeveSpec]:
    """Every selectable model-driven trial: the 18 the install rule chooses among."""
    return [*book_trials(), *mix_trials()]


def is_eligible(score: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """R-INSTALL2's eligibility on the selection window: drawdown, volatility and gross within the ceiling, and a book that
    holds at least three of the four classes on at least 80% of its rebalance rows. Returns (eligible, the clauses that failed)."""
    failed = []
    for key, ceiling in (("max_drawdown", ELIGIBLE["max_drawdown"]), ("volatility", ELIGIBLE["volatility"]), ("mean_gross", ELIGIBLE["mean_gross"])):
        value = score.get(key)
        if value is None or not np.isfinite(value) or value > ceiling:
            failed.append(key)
    breadth = score.get("class_breadth")
    if breadth is None or breadth < ELIGIBLE["class_breadth"]:
        failed.append("class_breadth")
    return not failed, failed


def pick_candidate(scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The eligible trial with the highest pooled Sharpe (the lower turnover on a tie). With none eligible the model-free core
    stands in, and the result says so. Controls never compete."""
    pool = [score for score in scores if score["id"] not in CONTROL_IDS]
    verdicts = {score["id"]: is_eligible(score) for score in pool}
    eligible = [score for score in pool if verdicts[score["id"]][0] and score.get("sharpe") is not None]
    if not eligible:
        return {"candidate": "core", "reason": "no trial is eligible; the model-free core stands in", "eligible": [],
                "ineligible": {name: failed for name, (_, failed) in verdicts.items() if failed}}
    best = min(eligible, key=lambda score: (-round(float(score["sharpe"]), 12), float(score.get("turnover") or 0.0), score["id"]))
    return {"candidate": best["id"], "reason": "highest pooled Sharpe among the eligible", "eligible": sorted(score["id"] for score in eligible),
            "ineligible": {name: failed for name, (ok, failed) in verdicts.items() if not ok}}


def install_verdict(
    verification: Mapping[str, Any], lean: Mapping[str, Any] | None, *, survivor: bool = False,
) -> dict[str, Any]:
    """R-INSTALL2's install clauses on the verification window, each with its number. `verification` holds the engine's volatility,
    max_drawdown and mean_gross for the frozen candidate; `lean` the Lean run's `completed`, `engine_log_clean`, `correlation`
    and `annual_return_gap` (None before a run exists, which fails the Lean clauses). Sharpe is reported, not required."""
    clauses: dict[str, dict[str, Any]] = {}

    def add(name: str, value: Any, passed: bool) -> None:
        clauses[name] = {"value": value, "pass": bool(passed)}

    for key, ceiling in (("volatility", ELIGIBLE["volatility"]), ("max_drawdown", ELIGIBLE["max_drawdown"]), ("mean_gross", ELIGIBLE["mean_gross"])):
        value = verification.get(key)
        add(key, value, value is not None and np.isfinite(value) and value <= ceiling)
    lean = lean or {}
    add("lean_completed", lean.get("completed"), bool(lean.get("completed")) and bool(lean.get("engine_log_clean")))
    correlation, gap = lean.get("correlation"), lean.get("annual_return_gap")
    add("lean_correlation", correlation, correlation is not None and correlation >= LEAN_VS_ENGINE["correlation"])
    add("lean_return_gap", gap, gap is not None and abs(gap) <= LEAN_VS_ENGINE["annual_return_gap"])
    install = all(item["pass"] for item in clauses.values())
    return {"install": install, "share": None if not install else (None if survivor else NON_SURVIVOR_SHARE), "survivor": survivor,
            "sharpe_reported": verification.get("sharpe"), "clauses": clauses, "failed": sorted(name for name, item in clauses.items() if not item["pass"])}


def rank_ic_diagnostics(
    table: pd.DataFrame, known: pd.DataFrame, asset_class: Mapping[str, str], *, horizons: Sequence[int] = (5, 20), classes: Sequence[str] = CLASSES,
    start: str, end: str,
) -> dict[str, dict[str, Any]]:
    """D1: the rank correlation between a score table and the return that followed it (the known close at the decision to the known
    close `horizon` sessions later), by class and horizon. Each date's correlation is kept every `horizon`-th date (non-overlapping)
    and the t-statistic is Newey-West on the daily series. Looks at the score only; it selects nothing."""
    from evaluation.rank_ic_core import newey_west_t_stat

    out: dict[str, dict[str, Any]] = {}
    window = table.loc[(table.index >= start) & (table.index <= end)]
    for horizon in horizons:
        forward = known.shift(-int(horizon)) / known - 1.0
        for name in classes:
            members = [ticker for ticker in window.columns if asset_class.get(ticker) == name and ticker in forward.columns]
            daily = []
            for date, row in window[members].iterrows():
                realised = forward.loc[date, members]
                both = pd.concat([row, realised], axis=1).dropna()
                if len(both) >= 4 and both.iloc[:, 0].nunique() > 1 and both.iloc[:, 1].nunique() > 1:
                    daily.append((date, float(both.rank().corr().iloc[0, 1])))
            series = pd.Series(dict(daily), dtype=float)
            sampled = series.iloc[:: int(horizon)]
            out[f"{name}_{horizon}d"] = {
                "class": name, "horizon": int(horizon), "n_dates": int(len(series)), "n_independent": int(len(sampled)),
                "mean_ic": float(sampled.mean()) if len(sampled) else None,
                "t_hac": newey_west_t_stat(series.to_numpy(), int(horizon) - 1) if len(series) else None,
            }
    return out


def daily_rank(frame: pd.DataFrame, values: np.ndarray) -> pd.Series:
    """The percentile rank of `values` among the names of the same date."""
    return pd.Series(values, index=frame.index).groupby(frame["date"]).rank(pct=True)


def installed_score_tables(
    dataset: pd.DataFrame, exports: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]], *, start: str, end: str,
    sequence_window: int = 30, universe: Iterable[str] | None = None, predictor: Callable[..., Mapping[str, np.ndarray]] | None = None,
) -> dict[str, pd.DataFrame]:
    """The installed models' score tables on [start, end], defined exactly as the walk-forward tables are (V6.5.0): `inst_a1` the
    mean of the date's percentile ranks of the sequence model's rank_20d and rank_5d, `inst_a2` the multitask model's
    sector_neutral_rank_20d, `inst_a3` the sequence model's. `dataset` must hold earlier rows too: a sequence window reads the
    previous bars of its ticker. `exports` maps "multitask"/"sequence" to (export, feature schema)."""
    if predictor is None:
        from evaluation.model_predictions import predict_heads as predictor
    frame = dataset.copy()
    frame["date"] = frame["date"].astype(str).str[:10]
    if universe is not None:
        frame = frame[frame["ticker"].isin(set(universe))]
    frame = frame.sort_values(["ticker", "date"]).reset_index(drop=True)
    mask = ((frame["date"] >= start) & (frame["date"] <= end)).to_numpy()
    if not mask.any():
        return {}
    heads = {
        kind: predictor(
            frame, export, schema["model_input_names"], list(HEADS), model_kind=kind,
            sequence_feature_schema=schema if kind == "sequence" else None, configured_window_size=sequence_window, row_mask=mask, batched=True,
        )
        for kind, (export, schema) in exports.items()
    }
    out: dict[str, pd.DataFrame] = {}

    def add(name: str, values: pd.Series) -> None:
        out[name] = pd.DataFrame({"date": frame.loc[mask, "date"], "ticker": frame.loc[mask, "ticker"], "score": values[mask]}).reset_index(drop=True)

    if "sequence" in heads:
        sequence = heads["sequence"]
        add("inst_a1", (daily_rank(frame, sequence["rank_20d"]) + daily_rank(frame, sequence["rank_5d"])) / 2.0)
        add("inst_a3", pd.Series(sequence["sector_neutral_rank_20d"], index=frame.index))
    if "multitask" in heads:
        add("inst_a2", pd.Series(heads["multitask"]["sector_neutral_rank_20d"], index=frame.index))
    return out
