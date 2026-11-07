"""One pre-registered research round, from a rule file (V6.6.1): the stages each phase used to hand-write in a `scripts/v6xx_*.py`.

A round's JSON is hashed before any score and never edited: every stage starts by checking that hash. Its stages are resumable, since the training
Codespace reboots about hourly:

    rules -> score -> placebo -> gate -> pbo -> (survivors only) freeze -> hold -> report

Selection reads a free cell only. A held-out cell opens through `evaluation/research_cells.py` with the digest of the one freeze, and
`record_holdout_read` refuses a second read of any cell. Every trial counts in the deflated Sharpe's N, whether it ran or not.

Pure where it can be: `gate_report` and `pbo_report` work on stored scores, so a past round can be recomputed and compared.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.premia_research import (
    nulls_for,
    passes_sharpe_clauses,
    placebo_p_value,
    placebo_sharpes,
    score_sleeve,
    selection_gate,
)
from evaluation.research_cells import CELLS, FREE_CELLS, freeze_digest_of, record_holdout_read, write_freeze
from evaluation.trial_ledger import append_trial, read_ledger
from portfolio.premia_signals import POOLED, XS, SleeveSpec
from portfolio.signal_construction import build_table
from portfolio.wide_signals import live_names_per_rebalance, rank_mean

HOLDOUT_LEDGER = Path("ml") / "generations" / "holdout_ledger.jsonl"
KINDS = {"pooled": POOLED, "cross_sectional": XS}


@dataclass(frozen=True)
class RoundSpec:
    name: str
    cell: str
    side: str
    bar: str
    rule: str
    trials: Mapping[str, Mapping]
    out_dir: Path
    ledger: Path
    window_label: str = "v660_selection"
    track: str = "W"
    min_live_names: int = 150
    min_ic_names: int = 20
    pbo_blocks: int = 16
    prior_daily: tuple[str, ...] = ()
    prior_columns: tuple[str, ...] = ()
    disclosures: tuple[str, ...] = ()
    raw: Mapping = field(default_factory=dict)


def _read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8", newline="\n")


def rules_sha_path(path: Path) -> Path:
    return Path(path).with_suffix(".sha256")


def write_rules(payload: Mapping, path: Path) -> str:
    """Writes a round's rule file once, with its hash beside it. A second write refuses: a changed rule needs a dated amendment."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} is already written and is never overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rules_sha_path(path).write_text(digest + "\n", encoding="utf-8", newline="\n")
    return digest


def load_round(path: Path, *, root: Path = Path(".")) -> RoundSpec:
    """The round, after its hash check. A changed file stops the round: no stage reads rules other than the ones recorded."""
    path = Path(path)
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    recorded = rules_sha_path(path).read_text(encoding="utf-8").strip() if rules_sha_path(path).exists() else None
    if digest != recorded:
        raise SystemExit(f"{path.name} {digest} is not the recorded {recorded}")
    raw = json.loads(payload)
    return RoundSpec(
        name=str(raw["name"]), cell=str(raw["cell"]), side=str(raw["side"]), bar=str(raw["bar"]), rule=str(raw.get("rule", "")), trials=raw["trials"],
        out_dir=Path(root) / str(raw["out_dir"]), ledger=Path(root) / str(raw["ledger"]), window_label=str(raw.get("window_label", "v660_selection")),
        track=str(raw.get("track", "W")), min_live_names=int(raw.get("min_live_names", 150)), min_ic_names=int(raw.get("min_ic_names", 20)),
        pbo_blocks=int(raw.get("pbo_blocks", 16)), prior_daily=tuple(raw.get("prior_daily") or ()), prior_columns=tuple(raw.get("prior_columns") or ()),
        disclosures=tuple(raw.get("disclosures") or ()), raw=raw,
    )


def _paths(spec: RoundSpec) -> dict[str, Path]:
    return {name: spec.out_dir / f"{prefix}_{spec.name}{suffix}" for name, prefix, suffix in (
        ("scores", "selection_scores", ".json"), ("daily", "selection_daily", ".parquet"), ("placebos", "selection_placebos", ".json"),
        ("gate", "selection_gate", ".json"), ("pbo", "selection_pbo", ".json"), ("report", "r", ".json"),
    )}


def spec_of(spec: RoundSpec, trial: str, universe: Sequence[str]) -> SleeveSpec:
    entry = spec.trials[trial]
    params: dict = {"table": trial}
    if entry.get("top_k"):
        params["top_k"] = entry["top_k"]
    return SleeveSpec(trial, spec.track, KINDS[str(entry.get("kind", "pooled"))], "external_score", tuple(universe), int(entry.get("rebalance_every", 20)), params)


def score_file_table(path: Path, index, columns) -> pd.DataFrame | None:
    """A model's walk-forward scores as a session x ticker table, or None when the file isn't there."""
    path = Path(path)
    if not path.exists():
        return None
    frame = pd.read_csv(path, dtype={"date": str, "ticker": str})
    return frame.pivot_table(index="date", columns="ticker", values="score", aggfunc="last").reindex(index=index, columns=columns)


def trial_table(spec: RoundSpec, trial: str, cell, built: dict[str, pd.DataFrame], *, score_dir: Path, score_suffix: str = "") -> pd.DataFrame | None:
    """One trial's table on this cell, or None when it can't be built yet (a model that didn't run). `built` holds earlier trials, which a composite
    may name. Masked to the cell's members, so nothing outside them can be held."""
    entry = spec.trials[trial]
    known = cell.context.panel.known
    if entry.get("score_file"):
        table = score_file_table(Path(score_dir) / f"{entry['score_file']}{score_suffix}.csv", known.index, known.columns)
        return None if table is None else table.where(cell.member)
    if entry.get("builder") == "fama_macbeth_ridge":
        from evaluation.walk_forward_linear import fama_macbeth_ridge

        signs = {str(name): float(sign) for name, sign in entry["signs"].items()}
        start = str(entry.get("start") or cell.cell.start)
        features = {name: cell.features[name].where(cell.member.reindex(index=cell.features[name].index, columns=cell.features[name].columns, fill_value=False)) for name in signs if name in cell.features}
        if len(features) != len(signs):
            raise KeyError(f"{trial}: features {sorted(set(signs) - set(features))} are not in this cell")
        table = fama_macbeth_ridge(features, cell.label, signs=signs, start=start, kappa=int(entry.get("kappa", 36)), ridge=float(entry.get("ridge", 1.0)))
        return table.where(cell.member.reindex(index=table.index, columns=table.columns, fill_value=False))
    recipe = entry["recipe"]
    lookup = {**cell.features, **cell.tables, **built}
    if recipe.get("optional_parts"):
        present = [name for name in recipe["parts"] if name in lookup]
        if len(present) < int(recipe.get("minimum", 2)):
            return None
        return rank_mean([lookup[name] for name in present], minimum=int(recipe.get("minimum", 2))).where(cell.member)
    missing = [name for name in [*recipe["parts"], *(recipe.get("exposures") or ())] if name not in lookup]
    if missing and any(name in spec.trials for name in missing):
        return None  # a part is another trial that didn't run
    return build_table(recipe, lookup, cell.member, sectors=cell.sectors)


def _trial_context(context, entry: Mapping):
    band = entry.get("min_weight_change")
    if band is None:
        return context
    return dataclasses.replace(context, config=dataclasses.replace(context.config, min_weight_change=float(band)))


def passes_earlier_clauses(score: Mapping, *, min_live_names: int) -> bool:
    """Everything in R-SLEEVE3 before the placebos: live names, the Sharpe clauses, and the rank-IC t."""
    if not passes_sharpe_clauses(score):
        return False
    if (score.get("live_names") or {}).get("median", 0.0) < min_live_names:
        return False
    t = (score.get("ic") or {}).get("nonoverlap_t")
    return t is not None and t >= 2.0


def _failed_clause(score: Mapping, *, min_live_names: int) -> str:
    if (score.get("live_names") or {}).get("median", 0.0) < min_live_names:
        return "live_names"
    return "sharpe" if not passes_sharpe_clauses(score) else "ic"


def _load_selection_cell(spec: RoundSpec, root: Path, *, with_info: bool = True):
    from evaluation.wide_context import equity_cell

    if spec.cell not in FREE_CELLS:
        raise PermissionError(f"selection reads free cells only, not {spec.cell}")
    base = json.loads((Path(root) / "config.json").read_text(encoding="utf-8"))
    return equity_cell(Path(root), base, spec.cell, with_info=with_info)


def stage_score(spec: RoundSpec, *, cell, score_dir: Path, only: Sequence[str] = (), force: bool = False, ic_fn: Callable | None = None, emit: Callable[[str], None] = print) -> dict:
    """Scores each trial not yet scored, saving after each one. A table that can't be built stays unscored and is named by the gate."""
    if ic_fn is None:
        from evaluation.wide_context import signal_ic_t as ic_fn
    paths = _paths(spec)
    scores = _read_json(paths["scores"], {})
    frames = pd.read_parquet(paths["daily"]).to_dict("series") if paths["daily"].exists() else {}
    context = cell.context
    from evaluation.wide_context import SECTORS

    built: dict[str, pd.DataFrame] = {}
    for trial, entry in spec.trials.items():
        table = trial_table(spec, trial, cell, built, score_dir=score_dir)
        if table is None:
            emit(f"{trial}: no table yet")
            continue
        built[trial] = table
        context.panel.extras[trial] = table
        if (only and trial not in only) or (trial in scores and not force):
            continue
        sleeve = spec_of(spec, trial, SECTORS)
        start = str(entry.get("start") or cell.cell.start)
        signal = table
        live = live_names_per_rebalance(signal.loc[signal.index >= start], sleeve.rebalance_every)
        score = score_sleeve(sleeve, _trial_context(context, entry), start=start, split=cell.cell.split, end=cell.cell.end, signal=signal)
        daily = score.pop("daily")
        middle = daily[min(daily)]
        frames[trial] = middle
        ic = ic_fn(signal, cell.label, start=start, end=cell.cell.end, min_names=spec.min_ic_names) if cell.label is not None else None
        scores[trial] = {**score, "cell": spec.cell, "live_names": live, "ic": ic, "round": spec.name}
        append_trial(spec.ledger, trial_id=trial, track=spec.track, window=spec.window_label, role="candidate", annualised_sharpe=score["sharpe"], n_obs=len(middle), engine="offline",
                     detail={"cell": spec.cell, "round": spec.name})
        _write_json(paths["scores"], scores)
        pd.DataFrame(frames).sort_index().to_parquet(paths["daily"])
        emit(f"{trial} Sharpe {score['sharpe']} ({score['sharpe_first_half']}, {score['sharpe_second_half']}) IC t {(ic or {}).get('nonoverlap_t')} live {live['median']:.0f} turnover {score['turnover']}")
    return scores


def stage_placebo(spec: RoundSpec, *, cell, score_dir: Path, draws: int = 100, force: bool = False, emit: Callable[[str], None] = print) -> dict:
    """R-SLEEVE3's placebos, only for trials that pass every earlier clause."""
    from evaluation.wide_context import SECTORS

    paths = _paths(spec)
    scores = _read_json(paths["scores"], {})
    eligible = [trial for trial, score in scores.items() if passes_earlier_clauses(score, min_live_names=spec.min_live_names)]
    emit(f"reach the placebo clause: {eligible or 'none'}")
    done = _read_json(paths["placebos"], {})
    if not eligible:
        _write_json(paths["placebos"], done)
        return done
    built: dict[str, pd.DataFrame] = {}
    for trial in spec.trials:
        table = trial_table(spec, trial, cell, built, score_dir=score_dir)
        if table is not None:
            built[trial] = table
            cell.context.panel.extras[trial] = table
    for trial in eligible:
        if trial in done and not force:
            continue
        sleeve = spec_of(spec, trial, SECTORS)
        entry = spec.trials[trial]
        start = str(entry.get("start") or cell.cell.start)
        out = {}
        for mode in nulls_for(sleeve):
            sharpes = placebo_sharpes(sleeve, _trial_context(cell.context, entry), mode, start=start, end=cell.cell.end, draws=draws)
            out[mode] = {"p": placebo_p_value(scores[trial]["sharpe"], sharpes), "draws": len(sharpes), "median": float(pd.Series(sharpes).median()) if sharpes else None}
            emit(f"{trial} {mode} p {out[mode]['p']:.3f} median {out[mode]['median']}")
        done[trial] = out
        _write_json(paths["placebos"], done)
    return done


def gate_report(scores: Mapping[str, Mapping], placebos: Mapping[str, Mapping], daily: pd.DataFrame, *, trials: Sequence[str], min_live_names: int = 150) -> dict:
    """R-SLEEVE3 from stored scores: a pure function, so a past round can be recomputed and compared."""
    eligible = {name: score for name, score in scores.items() if passes_earlier_clauses(score, min_live_names=min_live_names)}
    rows = [{**score, "id": name, "daily": {0: daily[name].dropna()}} for name, score in eligible.items()]
    p_values = {name: {mode: entry["p"] for mode, entry in tests.items()} for name, tests in placebos.items()}
    gate = selection_gate(rows, p_values)
    gate["failed_earlier_clauses"] = {name: _failed_clause(score, min_live_names=min_live_names) for name, score in scores.items() if name not in eligible}
    gate["unscored"] = [trial for trial in trials if trial not in scores]
    return gate


def count_unrun_trials(spec: RoundSpec, unscored: Sequence[str], *, reason: str = "did not run") -> list[str]:
    """A pre-registered trial counts in N whether it ran or not. Appends a row only for those the ledger doesn't hold yet."""
    held = {entry["trial_id"] for entry in read_ledger(spec.ledger)}
    added = []
    for trial in unscored:
        if trial not in held:
            append_trial(spec.ledger, trial_id=trial, track=spec.track, window=spec.window_label, role="candidate", annualised_sharpe=None, n_obs=0, engine="offline",
                         detail={"cell": spec.cell, "round": spec.name, "not_run": reason})
            added.append(trial)
    return added


def stage_gate(spec: RoundSpec) -> dict:
    paths = _paths(spec)
    scores = _read_json(paths["scores"], {})
    placebos = _read_json(paths["placebos"], {})
    daily = pd.read_parquet(paths["daily"]) if paths["daily"].exists() else pd.DataFrame()
    gate = gate_report(scores, placebos, daily, trials=list(spec.trials), min_live_names=spec.min_live_names)
    gate["counted_without_a_score"] = count_unrun_trials(spec, gate["unscored"])
    _write_json(paths["gate"], gate)
    return gate


def pbo_report(frames: Sequence[pd.DataFrame], columns: Sequence[str], *, window: tuple[str, str], blocks: int = 16) -> dict:
    """The probability of backtest overfitting over the named columns. A trial with no return on a date reads as flat, as a trial that didn't exist yet would be."""
    from evaluation.pbo import probability_of_backtest_overfitting

    both = pd.concat(list(frames), axis=1)
    present = [name for name in columns if name in both.columns]
    matrix = both[present]
    matrix = matrix[(matrix.index >= window[0]) & (matrix.index <= window[1])].dropna(how="all").fillna(0.0)
    result = probability_of_backtest_overfitting(matrix.to_numpy(dtype=float), blocks=blocks, periods_per_year=252)
    return {"pbo": result.get("pbo"), "num_trials": len(present), "window": "..".join(window), "absent": [name for name in columns if name not in both.columns]}


def stage_pbo(spec: RoundSpec, *, root: Path = Path(".")) -> dict:
    paths = _paths(spec)
    cell = CELLS[spec.cell]
    frames = [pd.read_parquet(Path(root) / path) for path in spec.prior_daily]
    if paths["daily"].exists():
        frames.append(pd.read_parquet(paths["daily"]))
    report = pbo_report(frames, [*spec.prior_columns, *spec.trials], window=(cell.start, cell.end), blocks=spec.pbo_blocks)
    _write_json(paths["pbo"], report)
    return report


def holdouts_spent(path: Path) -> list[str]:
    """Cells any freeze has read, from the once-only ledger."""
    return sorted({cell for entry in read_ledger(path) for cell in entry.get("cells", ())})


def stage_freeze(spec: RoundSpec, candidate: Mapping, *, holdout_ledger: Path, code_digests: Mapping[str, str] | None = None) -> tuple[Path, str]:
    """Freezes one candidate, by rule. Refuses once any holdout has been read: the same data can't back a second candidate. Returns (path, digest)."""
    spent = holdouts_spent(holdout_ledger)
    if spent:
        raise PermissionError(f"holdouts {spent} are spent: a later candidate needs 252 forward sessions instead (R-ADMIT1)")
    path = spec.out_dir / f"freeze_{candidate['trial']}.json"
    rules_sha = hashlib.sha256(json.dumps(spec.raw, sort_keys=True).encode("utf-8")).hexdigest()
    digest = write_freeze(path, {"round": spec.name, "rules_sha256": rules_sha, "candidate": dict(candidate), "code_digests": dict(code_digests or {})})
    return path, digest


def r_hold1(reads: Mapping[str, Mapping]) -> dict:
    """R-HOLD1's clauses: V3 Sharpe >= 0.50 and alpha t >= 2.0; V1 and V2 Sharpe > 0. A missing figure fails."""
    def finite(value) -> float | None:
        return float(value) if value is not None and math.isfinite(float(value)) else None

    v3_sharpe, v3_t = finite((reads.get("V3") or {}).get("sharpe")), finite((reads.get("V3") or {}).get("alpha_t"))
    v1, v2 = finite((reads.get("V1") or {}).get("sharpe")), finite((reads.get("V2") or {}).get("sharpe"))
    clauses = {
        "V3_sharpe": v3_sharpe is not None and v3_sharpe >= 0.50, "V3_alpha_t": v3_t is not None and v3_t >= 2.0,
        "V1_sharpe": v1 is not None and v1 > 0.0, "V2_sharpe": v2 is not None and v2 > 0.0,
    }
    return {"rule": "R-HOLD1", "passed": all(clauses.values()), "clauses": clauses, "reads": dict(reads)}


def stage_hold(
    spec: RoundSpec, trial: str, *, root: Path, freeze_path: Path, digest: str, holdout_ledger: Path, created_at: str, score_dir: Path,
    read_cell: Callable[[str], object] | None = None, alpha_fn: Callable[[pd.Series], Mapping] | None = None,
) -> dict:
    """The one read of the holdouts. It records the read before opening anything: a crash after this still counts as spent."""
    from evaluation.premia_research import annual_sharpe, weights_for
    from evaluation.wide_context import SECTORS

    if Path(freeze_path).name != f"freeze_{trial}.json" or freeze_digest_of(Path(freeze_path)) != digest:
        raise PermissionError("the freeze on disk is not this candidate's")
    cells = ("V1", "V2", "V3")
    record_holdout_read(holdout_ledger, candidate=trial, cells=cells, digest=digest, created_at=created_at)
    if read_cell is None:
        from evaluation.wide_context import equity_cell

        base = json.loads((Path(root) / "config.json").read_text(encoding="utf-8"))
        read_cell = lambda name: equity_cell(Path(root), base, name, freeze_path=Path(freeze_path), freeze_digest=digest)  # noqa: E731
    sleeve = spec_of(spec, trial, SECTORS)
    entry = spec.trials[trial]
    reads: dict[str, dict] = {}
    for name in cells:
        cell = read_cell(name)
        built: dict[str, pd.DataFrame] = {}
        for other in spec.trials:
            if other != trial and not _is_part_of(spec, trial, other):
                continue
            table = trial_table(spec, other, cell, built, score_dir=score_dir, score_suffix=f"_{name}")
            if table is not None:
                built[other] = table
        if trial not in built:
            reads[name] = {"sharpe": None, "alpha_t": None, "reason": "no table on this cell"}
            continue
        cell.context.panel.extras[trial] = built[trial]
        start, end = cell.cell.start, cell.cell.end
        result = _trial_context(cell.context, entry).simulate(weights_for(sleeve, cell.context, built[trial], start=start, end=end, phase_offset=0), start, end)
        series = result["strategy_excess"]
        reads[name] = {"sharpe": annual_sharpe(series, sessions=cell.context.market.sessions), "alpha_t": (alpha_fn(series) if alpha_fn else {}).get("t_hac")}
    verdict = r_hold1(reads)
    _write_json(spec.out_dir / f"r_hold1_{trial}.json", verdict)
    return verdict


def _is_part_of(spec: RoundSpec, trial: str, other: str) -> bool:
    recipe = spec.trials[trial].get("recipe") or {}
    return other in (recipe.get("parts") or ())


def stage_report(spec: RoundSpec, *, alpha_fn: Callable[[pd.Series], Mapping] | None = None) -> dict:
    """The verdict in plain figures: survivors, PBO, and what this round can and can't exclude, per trial and at the best trial."""
    from evaluation.power_analysis import excluded_alpha_sharpe

    paths = _paths(spec)
    gate = _read_json(paths["gate"], {})
    pbo = _read_json(paths["pbo"], {})
    scores = _read_json(paths["scores"], {})
    daily = pd.read_parquet(paths["daily"]) if paths["daily"].exists() else pd.DataFrame()
    trials: dict[str, dict] = {}
    for name, score in scores.items():
        row = {key: score.get(key) for key in ("sharpe", "sharpe_first_half", "sharpe_second_half", "turnover", "max_drawdown", "mean_gross", "live_names")}
        row["ic_t"] = (score.get("ic") or {}).get("nonoverlap_t")
        row["ic"] = (score.get("ic") or {}).get("mean_ic")
        if alpha_fn is not None and name in daily.columns:
            series = daily[name].dropna()
            alpha = alpha_fn(series)
            t = alpha.get("t_hac")
            row["alpha_t"] = t
            row["alpha_annual"] = alpha.get("alpha_annual")
            if t is not None and np.isfinite(t):
                row["excluded_alpha_sharpe_95"] = excluded_alpha_sharpe(float(t), len(series) / 252.0)
        trials[name] = row
    survivors = list(gate.get("survivors") or [])
    pbo_value = pbo.get("pbo")
    stopped = None
    if not survivors:
        stopped = "zero trials survived R-SLEEVE3: no freeze, no holdout read"
    elif pbo_value is None or float(pbo_value) >= 0.5:
        stopped = f"PBO {pbo_value} is not below 0.5: no freeze, no holdout read"
    report = {
        "round": spec.name, "rule": spec.rule, "verdict": "not verified" if stopped else "survivors reach the freeze", "stopped_at": stopped, "survivors": survivors,
        "pbo": pbo_value, "trials": trials, "unscored": gate.get("unscored"), "failed": gate.get("failed"), "failed_earlier_clauses": gate.get("failed_earlier_clauses"),
        "disclosures": list(spec.disclosures),
    }
    _write_json(paths["report"], report)
    return report
