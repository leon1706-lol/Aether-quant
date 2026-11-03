"""V6.4.3 research chain: rule R-MODEL11's fixed grid (ml/evaluation/v643/r_model11_rule.json, written before any score),
the as-of label leak measurement and the leakage audit. Scoring is V6.4.0's: the calibrated as-live simulator
(lean_calibration.calibrated_overrides + the V6.1.0 mechanisms without the legacy signal, learned-topology sizing at the
mid bracket), rolling-IC gate on, T-bill sweep off, the median over --max-phases evenly spaced rebalance phases.

Stages (each resumable from the memo next to --out):
  labels     as-of beta labels (features/asof_beta_labels.py) -> --asof-labels parquet, and the leak: the installed
             multitask residual / beta-neutral heads' IC against the whole-history labels and against the as-of ones
  leakage    evaluation/leakage_audit.audit_leakage on the 50 scaled features
  grid       F1-F6, L1-L3, G1-G3, B1-B3, R1: IC report (evaluation/research_harness) + as-live phases on both splits
  pbo        CSCV over the grid's phase-0 daily as-live returns (validation + backtest)
  spanning   probes' long/short returns against F1-F5's on backtest
  verdict    R-MODEL11's six clauses; the holdout is read once, for finalists only

    python scripts/v643_research.py [--dataset ml/datasets/full_dataset.csv] [--stages labels leakage grid pbo spanning verdict]
        [--max-phases 10] [--out ml/evaluation/v643/research.json]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

SPLITS = ("validation", "backtest")
YARDSTICK = 0.034
RAW_FACTOR_INPUTS = ("close_to_close_return_1d", "close_to_close_return_5d", "momentum_20d", "rolling_volatility_20d", "dist_52w_high")
TARGETS = ("target_rank_20d", "target_rank_5d", "target_return_1d", "target_return_5d", "target_return_20d",
           "target_residual_rank_20d", "target_residual_rank_5d", "target_beta_neutral_rank_20d", "target_beta_neutral_rank_5d")
CLASS_COLUMNS = ("asset_class_equity", "asset_class_crypto", "asset_class_bond", "asset_class_future", "asset_class_option", "asset_class_forex")
FACTOR_TRIALS = {"F1": "f_mom_12_1", "F2": "f_mom_20", "F3": "f_rev_5", "F4": "f_lowvol", "F5": "f_high52", "F6": "f_composite"}
OVERLAY_TRIALS = ("F1", "F2", "F3", "F4", "F5", "F6", "B1", "B2", "B3", "R1", "S1")
S1_HEADS = {"sector_neutral_rank_20d": 1.0}
HGB_PARAMS = dict(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=500, l2_regularization=1.0, early_stopping=False,
                  random_state=7)


def _json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save(path: Path, payload) -> None:
    from json_safety import atomic_write_json

    atomic_write_json(path, payload, indent=1)


def per_date_rank(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.groupby("date")[column].rank(pct=True)


class Chain:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out)
        self.report = _json(self.out, {})
        self.report.setdefault("holdout_reads", [])
        self.memo_path = self.out.with_suffix(".memo.json")
        self.memo = _json(self.memo_path, {})
        self.config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
        self.harnesses: dict = {}
        self._frame = None

    def save(self) -> None:
        _save(self.out, self.report)
        _save(self.memo_path, self.memo)

    # -- data
    def frame(self) -> pd.DataFrame:
        if self._frame is None:
            from evaluation.research_probes import load_research_frame

            schema = json.loads((ROOT_DIR / "ml" / "feature_schema.json").read_text(encoding="utf-8"))
            mt_schema = json.loads((ROOT_DIR / "ml" / "multitask_feature_schema.json").read_text(encoding="utf-8"))
            self.scaled = list(schema["scaled_feature_names"])
            self.model_inputs = list(mt_schema["model_input_names"])
            columns = [*self.model_inputs, *RAW_FACTOR_INPUTS, *TARGETS, "regime_signal_risk_score", "liquidity_log_dollar_volume"]
            frame = load_research_frame(self.args.dataset, columns=columns)
            labels_path = Path(self.args.asof_labels)
            if labels_path.exists():
                labels = pd.read_parquet(labels_path)
                frame = frame.merge(labels, on=["date", "ticker"], how="left")
            frame = frame.sort_values(["date", "ticker"]).reset_index(drop=True)
            self._frame = frame
            print(f"research frame {frame.shape}, {frame.memory_usage(deep=False).sum() / 1e6:.0f} MB", flush=True)
        return self._frame

    def harness(self, split: str):
        if split not in self.harnesses:
            from as_live_levers import AsLiveHarness
            from lean_calibration import topology_inputs_fn_for

            harness = AsLiveHarness(split, dataset_path=self.args.dataset, config=self.config)
            harness.topology_inputs_fn = topology_inputs_fn_for(harness, self.config)
            harness.original_scores = harness.frame["live_rank_score"].to_numpy().copy()
            self.harnesses[split] = harness
        return self.harnesses[split]

    def installed_scores(self) -> pd.Series:
        """live_rank_score of every validation / backtest / holdout row, aligned to the research frame."""
        frame = self.frame()
        if "installed" not in frame:
            parts = []
            for split in (*SPLITS, "holdout"):
                harness = self.harness(split)
                parts.append(pd.DataFrame({"date": harness.frame["date"].astype(str).str[:10], "ticker": harness.frame["ticker"].astype(str),
                                           "installed": harness.original_scores}))
            scores = pd.concat(parts, ignore_index=True).drop_duplicates(["date", "ticker"])
            self._frame = frame.merge(scores, on=["date", "ticker"], how="left")
        return self._frame["installed"]

    def s1_scores(self, splits=(*SPLITS, "holdout")) -> pd.Series:
        """S1: the live rank score the installed models give with rank_signal.heads = S1_HEADS, aligned to the frame."""
        import copy

        from as_live_levers import AsLiveHarness

        config = copy.deepcopy(self.config)
        config["phase_v2"]["rank_signal"]["heads"] = dict(S1_HEADS)
        parts = []
        for split in splits:
            harness = AsLiveHarness(split, dataset_path=self.args.dataset, config=config)
            parts.append(pd.DataFrame({"date": harness.frame["date"].astype(str).str[:10], "ticker": harness.frame["ticker"].astype(str),
                                       "s1": harness.frame["live_rank_score"].to_numpy()}))
            del harness
        scores = pd.concat(parts, ignore_index=True).drop_duplicates(["date", "ticker"])
        merged = self.frame()[["date", "ticker"]].merge(scores, on=["date", "ticker"], how="left")
        return pd.Series(merged["s1"].to_numpy(), index=self.frame().index)

    @contextlib.contextmanager
    def score_override(self, harness, scores: pd.Series):
        """Swap the harness' live score for `scores` (indexed like the research frame) while the block runs."""
        from evaluation.live_parity import lag_predictions_for_tickers

        frame = self.frame()
        lookup = dict(zip(zip(frame["date"], frame["ticker"]), scores.to_numpy()))
        keys = zip(harness.frame["date"].astype(str).str[:10], harness.frame["ticker"].astype(str))
        replaced = np.array([lookup.get(key, np.nan) for key in keys], dtype=float)
        try:
            harness.frame["live_rank_score"] = replaced
            harness.lagged_frame = lag_predictions_for_tickers(harness.frame, prediction_column="live_rank_score",
                                                               tickers=harness.late_bar_tickers)
            harness._states.clear()
            harness._gates.clear()
            harness._mechanisms.clear()
            yield
        finally:
            harness.frame["live_rank_score"] = harness.original_scores
            harness.lagged_frame = lag_predictions_for_tickers(harness.frame, prediction_column="live_rank_score",
                                                               tickers=harness.late_bar_tickers)
            harness._states.clear()
            harness._gates.clear()
            harness._mechanisms.clear()

    # -- scoring
    def phases(self) -> list[int]:
        every = int(self.config["phase_v2"]["portfolio_book"].get("rebalance_every_bars", 20))
        count = min(self.args.max_phases, every)
        return sorted({int(round(i * every / count)) % every for i in range(count)})

    def as_live(self, trial: str, split: str, scores: pd.Series | None) -> dict:
        """{"summary": extended_summary, "daily": phase-0 {date: net return}} for one trial on one split (memoised)."""
        from as_live_levers import summarize
        from lean_calibration import ANALYZER_INCLUDE, calibrated_overrides
        from v640_research import extended_summary

        digest = hashlib.sha1(np.nan_to_num(scores.to_numpy(dtype=float), nan=-9.0).tobytes()).hexdigest() if scores is not None else "base"
        key = f"{trial}|{split}|{digest}|{self.args.max_phases}"
        if key in self.memo:
            return self.memo[key]
        harness = self.harness(split)
        mechanisms = harness.v610_mechanisms(self.config, legacy=False)
        per_phase, daily = [], {}
        context = self.score_override(harness, scores) if scores is not None else contextlib.nullcontext()
        with context:
            for phase in self.phases():
                result = harness.as_live(**dict(calibrated_overrides(harness, phase=phase), **mechanisms), include=ANALYZER_INCLUDE)
                per_phase.append(summarize(result))
                if not daily:
                    daily = {str(d)[:10]: float(r) for d, r in zip(result.per_date, result.per_date_net_return)}
        entry = {"summary": extended_summary(per_phase), "daily": daily}
        self.memo[key] = entry
        self.save()
        print(f"  {trial:4s} {split:10s} median as-live Sharpe {entry['summary']['median_net_sharpe']:+.3f}", flush=True)
        return entry

    def ic(self, scores: pd.Series, splits=SPLITS) -> dict:
        from evaluation.research_harness import evaluate_signal

        frame = self.frame().assign(_score=scores.to_numpy())
        return evaluate_signal(frame, score_column="_score", splits=splits, horizons=(5, 20), min_names_per_date=20,
                               bootstrap_draws=500)["splits"]


# -- stages -----------------------------------------------------------------------------------------------------------

def stage_labels(chain: Chain) -> None:
    from features import load_sector_mapping
    from features.asof_beta_labels import build_asof_rank_labels

    frame = chain.frame()
    labels_path = Path(chain.args.asof_labels)
    if "target_residual_rank_20d_asof" not in frame:
        ranking = chain.config["phase1"]["target"]["ranking"]
        residual = ranking.get("residual_neutral", {})
        labels = build_asof_rank_labels(
            frame[["date", "ticker", "close_to_close_return_1d", "target_return_5d", "target_return_20d", "liquidity_log_dollar_volume"]],
            market_ticker=residual.get("market_ticker", "SPY"), sector_by_ticker=load_sector_mapping(chain.config),
            min_universe_size=int(residual.get("min_universe_size", ranking.get("min_universe_size", 20))),
        )
        out = pd.concat([frame[["date", "ticker"]], labels], axis=1)
        labels_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(labels_path, index=False)
        chain._frame = pd.concat([frame, labels], axis=1)
        frame = chain._frame
        print(f"as-of labels -> {labels_path}", flush=True)

    from evaluation.gate_audit import daily_rank_ic
    from evaluation.model_predictions import predict_heads

    export = json.loads((ROOT_DIR / "ml" / "multitask_model.json").read_text(encoding="utf-8"))
    heads = ["residual_rank_20d", "beta_neutral_rank_20d"]
    report: dict = {}
    for split in SPLITS:
        part = frame[frame["split"] == split].reset_index(drop=True)
        predictions = predict_heads(part, export, chain.model_inputs, heads, model_kind="multitask", batched=True)
        split_report = {}
        for head in heads:
            scored = part.assign(_p=predictions[head])
            row = {}
            for label in (f"target_{head}", f"target_{head}_asof"):
                ic = daily_rank_ic(scored, score_column="_p", target_column=label, min_names_per_date=20)
                row[label] = float(np.mean(list(ic.values()))) if ic else None
            agreement = daily_rank_ic(part, score_column=f"target_{head}", target_column=f"target_{head}_asof", min_names_per_date=20)
            row["label_agreement_spearman"] = float(np.mean(list(agreement.values()))) if agreement else None
            if row[f"target_{head}"] is not None and row[f"target_{head}_asof"] is not None:
                row["ic_inflation"] = row[f"target_{head}"] - row[f"target_{head}_asof"]
            split_report[head] = row
        report[split] = split_report
    chain.report["label_leak"] = report
    chain.save()
    print("label leak:", json.dumps(report, indent=1), flush=True)


def stage_leakage(chain: Chain) -> None:
    from evaluation.leakage_audit import audit_leakage

    frame = chain.frame()
    chain.installed_scores()
    report = audit_leakage(chain._frame, feature_columns=chain.scaled, target_column="target_rank_20d", class_columns=CLASS_COLUMNS,
                           model_score_column="installed")
    chain.report["leakage_audit"] = report
    _save(chain.out.parent / "leakage_audit.json", report)
    chain.save()
    print("leakage flagged:", report["flagged"], "identity:", report["identity"], flush=True)
    del frame


def build_trial_scores(chain: Chain) -> dict[str, pd.Series]:
    from evaluation.factor_spanning import build_factor_scores
    from evaluation.research_probes import fit_hgb_rank, fit_ridge_rank, predict_scores
    from features.cross_sectional_norm import cross_sectional_rank

    frame = chain.frame()
    installed = chain.installed_scores()
    frame = chain._frame
    factors = build_factor_scores(frame)
    scores: dict[str, pd.Series] = {trial: factors[column] for trial, column in FACTOR_TRIALS.items()}

    ranked = cross_sectional_rank(frame, chain.scaled)
    flagged = set((chain.report.get("leakage_audit") or {}).get("flagged", []))
    identity_like = {column for column, row in ((chain.report.get("leakage_audit") or {}).get("single_feature_ic") or {}).items()
                     if row.get("flag")}
    train = (frame["split"] == "train").to_numpy()
    inputs = {"L1": chain.scaled, "L2": chain.scaled, "L3": [c for c in chain.scaled if c not in flagged | identity_like
                                                            and c != "dist_52w_high_scaled"]}
    for name, columns in inputs.items():
        x = ranked[columns].to_numpy(dtype=np.float64)
        if name == "L2":
            x = np.column_stack([x, frame[list(CLASS_COLUMNS)].to_numpy(dtype=np.float64)])
        model = fit_ridge_rank(x[train], frame.loc[train, "target_rank_20d"].to_numpy(), alpha=10.0)
        scores[name] = pd.Series(predict_scores(model, x), index=frame.index)
        print(f"  {name} ridge on {model['rows']} rows, {x.shape[1]} inputs", flush=True)
    x = ranked[chain.scaled].to_numpy(dtype=np.float32)
    for name, depth, target in (("G1", 3, "target_rank_20d"), ("G2", 4, "target_rank_20d"), ("G3", 3, "target_residual_rank_20d_asof")):
        model = fit_hgb_rank(x[train], frame.loc[train, target].to_numpy(), **dict(HGB_PARAMS, max_depth=depth))
        scores[name] = pd.Series(predict_scores(model, x), index=frame.index)
        print(f"  {name} HGB depth {depth} on {target}", flush=True)
        del model

    installed_rank = per_date_rank(frame.assign(_s=installed), "_s")
    composite_rank = per_date_rank(frame.assign(_s=scores["F6"]), "_s")
    for name, weight in (("B1", 0.25), ("B2", 0.5), ("B3", 0.75)):
        scores[name] = (1.0 - weight) * installed_rank + weight * composite_rank.fillna(0.5)

    risk = frame["regime_signal_risk_score"]
    edges = risk[train].quantile([1 / 3, 2 / 3]).to_numpy()
    tercile = np.digitize(risk.to_numpy(), edges)
    weights = {}
    from evaluation.gate_audit import daily_rank_ic

    ranks = {trial: per_date_rank(frame.assign(_s=scores[trial]), "_s") for trial in ("F1", "F3", "F4", "F5")}
    for bucket in range(3):
        mask = train & (tercile == bucket)
        ics = {}
        for trial in ranks:
            ic = daily_rank_ic(frame[mask].assign(_s=scores[trial][mask]), score_column="_s", target_column="target_rank_20d",
                               min_names_per_date=20)
            ics[trial] = max(0.0, float(np.mean(list(ic.values())))) if ic else 0.0
        total = sum(ics.values())
        weights[bucket] = {trial: (value / total if total > 0 else 0.25) for trial, value in ics.items()}
    chain.report["r1_weights"] = {str(k): v for k, v in weights.items()}
    r1 = pd.Series(0.0, index=frame.index)
    for bucket, w in weights.items():
        mask = tercile == bucket
        r1[mask] = sum(w[trial] * ranks[trial][mask].fillna(0.5) for trial in w)
    scores["R1"] = r1.where(risk.notna())
    scores["S1"] = chain.s1_scores()
    return scores


def stage_grid(chain: Chain) -> dict[str, pd.Series]:
    scores = build_trial_scores(chain)
    installed = chain.installed_scores()
    grid = chain.report.setdefault("grid", {})
    base = {"ic": chain.ic(installed), "as_live": {split: chain.as_live("base", split, None)["summary"] for split in SPLITS}}
    chain.report["baseline"] = base
    for trial, series in scores.items():
        entry = grid.setdefault(trial, {})
        entry["ic"] = chain.ic(series)
        entry["as_live"] = {split: chain.as_live(trial, split, series)["summary"] for split in SPLITS}
        # build_trial_registry reads <trial>/backtest/median_net_sharpe
        entry["registry"] = {split: {"median_net_sharpe": entry["as_live"][split]["median_net_sharpe"],
                                     "phases": entry["as_live"][split]["phases"]} for split in SPLITS}
        chain.save()
    return scores


def stage_pbo(chain: Chain, scores: dict[str, pd.Series]) -> None:
    from evaluation.pbo import probability_of_backtest_overfitting

    trials = list(scores)
    series = []
    for trial in trials:
        daily: dict = {}
        for split in SPLITS:
            daily.update(chain.as_live(trial, split, scores[trial])["daily"])
        series.append(pd.Series(daily))
    matrix = pd.concat(series, axis=1, keys=trials).sort_index().fillna(0.0)
    matrix.to_parquet(chain.out.parent / "trial_returns.parquet")
    chain.report["pbo"] = probability_of_backtest_overfitting(matrix.to_numpy(), blocks=16)
    chain.save()
    print("PBO:", chain.report["pbo"]["pbo"], flush=True)


def stage_spanning(chain: Chain, scores: dict[str, pd.Series]) -> None:
    from evaluation.factor_spanning import build_factor_returns, factor_spanning

    frame = chain.frame()
    backtest = (frame["split"] == "backtest").to_numpy()
    part = frame.loc[backtest, ["date", "target_return_1d"]].copy()
    for trial, series in scores.items():
        part[trial] = series[backtest].to_numpy()
    factor_returns = build_factor_returns(part, ["F1", "F2", "F3", "F4", "F5"])
    result = {}
    for trial in ("L1", "L2", "L3", "G1", "G2", "G3"):
        signal = build_factor_returns(part, [trial])[trial]
        result[trial] = factor_spanning(signal, factor_returns)
    chain.report["spanning"] = result
    chain.save()
    print("spanning alpha t:", {k: v.get("alpha_t") for k, v in result.items()}, flush=True)


def clause_checks(chain: Chain, trial: str) -> dict:
    from v640_research import verdict_as_live

    base, entry = chain.report["baseline"], chain.report["grid"][trial]
    base_ic = base["ic"]["validation"]["h20"]["nonoverlap_mean_ic"]
    checks = {
        "1_validation_ic_beats_base_by_0.034": entry["ic"]["validation"]["h20"]["nonoverlap_mean_ic"] - base_ic >= YARDSTICK,
        "2_backtest_hac_t_ge_2": entry["ic"]["backtest"]["h20"]["hac_t"] >= 2.0,
        "3_verdict_as_live": verdict_as_live(base["as_live"], entry["as_live"])["passes"],
        "4_grid_pbo_below_0.5": (chain.report.get("pbo") or {}).get("pbo") is not None and chain.report["pbo"]["pbo"] < 0.5,
    }
    if trial[0] in "LG":
        checks["5_spanning_alpha_t_ge_2"] = ((chain.report.get("spanning") or {}).get(trial) or {}).get("alpha_t") is not None and \
            chain.report["spanning"][trial]["alpha_t"] >= 2.0
    return checks


def stage_verdict(chain: Chain, scores: dict[str, pd.Series]) -> None:
    verdicts = {trial: clause_checks(chain, trial) for trial in chain.report["grid"]}
    finalists = [trial for trial, checks in verdicts.items() if all(checks.values())]
    holdout = {}
    if finalists:
        base = chain.as_live("base", "holdout", None)["summary"]["median_net_sharpe"]
        for trial in finalists:
            chain.report["holdout_reads"].append({"trial": trial, "what": "rank_20d IC and as-live Sharpe on the holdout"})
            ic = chain.ic(scores[trial], splits=("holdout",))["holdout"]["h20"]["mean_ic"]
            sharpe = chain.as_live(trial, "holdout", scores[trial])["summary"]["median_net_sharpe"]
            holdout[trial] = {"ic": ic, "median_net_sharpe": sharpe, "baseline_median_net_sharpe": base,
                              "passes": ic > 0 and sharpe >= base - 0.10}
            verdicts[trial]["6_holdout"] = holdout[trial]["passes"]
    qualifiers = [trial for trial in finalists if all(verdicts[trial].values())]
    winner = max(qualifiers, key=lambda t: chain.report["grid"][t]["as_live"]["backtest"]["median_net_sharpe"]) if qualifiers else None
    chain.report["verdict"] = {"rule": "R-MODEL11", "checks": verdicts, "finalists": finalists, "holdout": holdout,
                               "qualifiers": qualifiers, "winner": winner,
                               "winner_type": None if winner is None else ("overlay" if winner in OVERLAY_TRIALS else "probe")}
    chain.save()
    print("R-MODEL11:", json.dumps(chain.report["verdict"], indent=1, default=str), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--asof-labels", default=str(ROOT_DIR / "ml" / "datasets" / "v643_asof_labels.parquet"))
    parser.add_argument("--stages", nargs="*", default=["labels", "leakage", "grid", "pbo", "spanning", "verdict"])
    parser.add_argument("--max-phases", type=int, default=10)
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v643" / "research.json"))
    args = parser.parse_args()
    chain = Chain(args)
    if "labels" in args.stages:
        stage_labels(chain)
    if "leakage" in args.stages:
        stage_leakage(chain)
    scores = None
    if any(stage in args.stages for stage in ("grid", "pbo", "spanning", "verdict")):
        scores = stage_grid(chain)
    if "pbo" in args.stages:
        stage_pbo(chain, scores)
    if "spanning" in args.stages:
        stage_spanning(chain, scores)
    if "verdict" in args.stages:
        stage_verdict(chain, scores)
    chain.report["phases"] = chain.phases()
    chain.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
