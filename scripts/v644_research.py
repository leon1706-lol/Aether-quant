"""V6.4.4 research chain: rules R-MODEL12 (the retrain grid) and R-TREND1 (the trend sleeve), both written in
ml/evaluation/v644/rules.json before any score. Scoring is V6.4.3's (`scripts/v643_research.Chain`): the calibrated
as-live simulator, rolling-IC gate on, T-bill sweep off, the median over --max-phases rebalance phases.

Stages (each resumable from the memo next to --out):
  priors       installed model and the identity / class priors on both candidate targets (validation)
  stage1       seed 1 of every grid ID: clauses C0 (viability) and C1 (priors + yardstick) -> stage1.json (survivors)
  stage2       seeds 1-3 of the survivors: seed medians, C2, the shipped seed
  ensemble     E = the best survivor's 3 seeds averaged (phase_v2.model_ensemble)
  aslive       as-live phases on validation / backtest for the base and every trial (C3, C4)
  pbo          CSCV over every trial's daily as-live returns (C5)
  spanning     informational: candidates' long/short returns against F1-F5 on backtest
  trend        R-TREND1 trials T1-T4 on train / validation / backtest (K1-K3)
  trend_main   the main book as-live without the trend symbols, correlation and the combined book (K4, K5)
  walkforward_pick  candidates passing C0-C5 in order -> walkforward_pick.json (the session runs the walk-forward)
  c6           --wf-candidate ID --wf-summary FILE: clause C6 (exit 0 pass, 3 fail)
  holdout      the single finalist's holdout read (C7) and the chosen trend trial's (K6)
  verdict      R-MODEL12 and R-TREND1

    python scripts/v644_research.py --stages priors stage1 [--dataset ml/datasets/v644_full_dataset.csv] [--smoke]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from v643_research import CLASS_COLUMNS, RAW_FACTOR_INPUTS, Chain, _save  # noqa: E402
from v643_research import _json as _json_load  # noqa: E402
from v644_make_configs import GRID, target_head  # noqa: E402

OUT_DIR = ROOT_DIR / "ml" / "evaluation" / "v644"
SPLITS = ("validation", "backtest")
YARDSTICK = 0.034
MAX_SURVIVORS = 3
SEEDS = (1, 2, 3)
TARGETS = ("target_rank_20d", "target_rank_5d", "target_sector_neutral_rank_20d", "target_return_1d", "target_return_5d",
           "target_return_20d")
TREND_TRIALS = {"T1": "sign_252", "T2": "sign_126", "T3": "sign_63", "T4": "sign_blend"}
TREND_WINDOWS = {"train": ("2014-12-01", "2021-12-31"), "validation": ("2022-01-01", "2023-06-30"),
                 "backtest": ("2023-07-01", "2025-06-30"), "trainval": ("2014-12-01", "2023-06-30")}
TREND_HALF_SPREAD_BPS = 2.0


def version_dir(grid_id: str, seed: int) -> Path:
    return ROOT_DIR / "ml" / "versions" / f"v644_{grid_id}_s{seed}"


def candidate_config(grid_id: str, *, ensemble: bool = False) -> dict:
    config = json.loads((OUT_DIR / "configs" / f"{grid_id}.json").read_text(encoding="utf-8"))
    if ensemble:
        config["phase_v2"]["model_ensemble"]["enabled"] = True
    return config


def candidate_ml_dir(name: str, members: list[Path], *, ensemble: bool) -> Path:
    """ml/evaluation/v644/cand_ml/<name>/: the installed top-level ml/*.json with the candidate's multitask files on top
    (the harness scores another directory's models without installing them); `ensemble` adds multitask_ensemble/."""
    target = OUT_DIR / "cand_ml" / name
    target.mkdir(parents=True, exist_ok=True)
    for path in (ROOT_DIR / "ml").glob("*.json"):
        shutil.copy2(path, target / path.name)
    for filename in ("multitask_model.json", "multitask_feature_schema.json", "multitask_training_metrics.json"):
        shutil.copy2(members[0] / filename, target / filename)
    ensemble_dir = target / "multitask_ensemble"
    if ensemble_dir.exists():
        shutil.rmtree(ensemble_dir)
    if ensemble:
        ensemble_dir.mkdir()
        for index, member in enumerate(members, start=1):
            shutil.copy2(member / "multitask_model.json", ensemble_dir / f"member_{index}.json")
    return target


CENTRED_SUFFIX = "_c"


def add_centred_targets(frame: pd.DataFrame, config: dict) -> pd.DataFrame:
    """R-MODEL13's labels: target_rank_20d minus its mean over (date, rank group) and target_sector_neutral_rank_20d minus
    its mean over (date, sector). A percentile rank in a group of n names averages (n+1)/2n, so uncentred labels differ in
    mean by group size alone and a pooled IC rewards knowing the group (Problems.md, V6.4.4)."""
    from features import load_sector_mapping
    from features.cross_sectional_inputs import asset_class_by_ticker

    classes = asset_class_by_ticker(config)
    separate = (config["phase1"]["target"]["ranking"].get("separate_rank_groups") or {})
    group_of_class = {cls: name for name, members in separate.items() for cls in members}
    sectors = load_sector_mapping(config)
    tickers = frame["ticker"].astype(str)
    frame["_rank_group"] = tickers.map(lambda t: group_of_class.get(classes.get(t, "unknown"), "main"))
    frame["_sector"] = tickers.map(lambda t: sectors.get(t, "unknown"))
    for column, group in (("target_rank_20d", "_rank_group"), ("target_sector_neutral_rank_20d", "_sector")):
        if column in frame:
            means = frame.groupby(["date", group])[column].transform("mean")
            frame[column + CENTRED_SUFFIX] = (frame[column] - means).astype("float32")
    return frame


class Chain644(Chain):
    def __init__(self, args):
        super().__init__(args)
        if getattr(args, "memo", None):  # R-MODEL13 shares R-MODEL12's memo (the same as-live runs)
            self.memo_path = Path(args.memo)
            self.memo = _json_load(self.memo_path, {})
        self.tag = "_r13" if args.centred else ""

    def frame(self) -> pd.DataFrame:
        if self._frame is None:
            from evaluation.research_probes import load_research_frame

            schema = json.loads((ROOT_DIR / "ml" / "feature_schema.json").read_text(encoding="utf-8"))
            self.scaled = list(schema["scaled_feature_names"])
            columns = [*RAW_FACTOR_INPUTS, *TARGETS, *CLASS_COLUMNS]
            frame = load_research_frame(self.args.dataset, columns=columns)
            frame = frame.sort_values(["date", "ticker"]).reset_index(drop=True)
            self._frame = add_centred_targets(frame, self.config)
            print(f"research frame {self._frame.shape}", flush=True)
        return self._frame

    def ic_on(self, scores: pd.Series, head: str, splits=SPLITS) -> dict:
        """{split: h20 summary} of `scores` against the candidate's target (rank_20d or sector_neutral_rank_20d)."""
        from evaluation.research_harness import evaluate_signal

        template = "target_sector_neutral_rank_{h}d" if head == "sector_neutral_rank_20d" else "target_rank_{h}d"
        if self.args.centred:  # R-MODEL13: labels minus their (date, group) mean
            template += CENTRED_SUFFIX
        frame = self.frame().assign(_score=scores.to_numpy())
        report = evaluate_signal(frame, score_column="_score", splits=splits, horizons=(20,), target_template=template,
                                 min_names_per_date=20, bootstrap_draws=300)["splits"]
        return {split: report[split].get("h20", {}) for split in splits}

    def candidate_scores(self, name: str, ml_dir: Path, config: dict, splits=SPLITS) -> pd.Series:
        """The candidate's live rank score (its harness with `ml_dir`) aligned to the research frame; cached as parquet."""
        from as_live_levers import AsLiveHarness

        cache = OUT_DIR / "scores" / f"{name}__{'+'.join(splits)}.parquet"
        if cache.exists():
            scores = pd.read_parquet(cache)
        else:
            parts = []
            for split in splits:
                harness = AsLiveHarness(split, dataset_path=self.args.dataset, config=config, ml_dir=ml_dir)
                parts.append(pd.DataFrame({"date": harness.frame["date"].astype(str).str[:10],
                                           "ticker": harness.frame["ticker"].astype(str),
                                           "score": harness.frame["live_rank_score"].to_numpy(dtype=float)}))
                del harness
            scores = pd.concat(parts, ignore_index=True).drop_duplicates(["date", "ticker"])
            cache.parent.mkdir(parents=True, exist_ok=True)
            scores.to_parquet(cache, index=False)
        merged = self.frame()[["date", "ticker"]].merge(scores, on=["date", "ticker"], how="left")
        return pd.Series(merged["score"].to_numpy(), index=self.frame().index)

    def installed(self) -> pd.Series:
        return self.installed_scores()

    @contextlib.contextmanager
    def exclude_tickers(self, harness, tickers):
        """The main book without `tickers` (their live score NaN while the block runs)."""
        frame = self.frame()
        scores = pd.Series(self.installed().to_numpy(), index=frame.index)
        scores[frame["ticker"].isin(list(tickers)).to_numpy()] = np.nan
        with self.score_override(harness, scores):
            yield


# ---------------------------------------------------------------- R-MODEL12 helpers

def viability(version: Path, config: dict) -> dict:
    """C0: the shipped promotion policy keeps the candidate's live-signal head (not demoted, status allowed)."""
    from portfolio.rank_signal import resolve_rank_signal_policy

    metrics = json.loads((version / "multitask_training_metrics.json").read_text(encoding="utf-8"))
    policy = resolve_rank_signal_policy({"multitask": metrics, "sequence": None}, config)
    wanted = [head for head, weight in config["phase_v2"]["rank_signal"]["heads"].items() if weight > 0]
    kept = {head: float(policy["heads"].get(head, 0.0)) for head in wanted}
    return {"passes": all(value > 0.0 for value in kept.values()) and "multitask" in policy["model_priority"],
            "kept_head_weights": kept, "model_priority": list(policy["model_priority"])}


def c1_check(ic: dict, priors: dict, installed_ic: dict) -> dict:
    validation = ic["validation"]
    prior_bar = max(value for value in (priors.get("identity_prior_ic"), priors.get("class_prior_ic")) if value is not None)
    checks = {
        "mean_ic_ge_priors": validation.get("mean_ic") is not None and validation["mean_ic"] >= prior_bar,
        "nonoverlap_ic_ge_installed_plus_yardstick":
            validation.get("nonoverlap_mean_ic") is not None
            and validation["nonoverlap_mean_ic"] >= installed_ic["validation"]["nonoverlap_mean_ic"] + YARDSTICK,
    }
    return {"passes": all(checks.values()), "checks": checks, "prior_bar": prior_bar}


def stage_priors(chain: Chain644) -> None:
    from evaluation.leakage_audit import identity_check

    frame = chain.frame()
    chain.installed()
    frame = chain._frame
    train, validation = frame[frame["split"] == "train"], frame[frame["split"] == "validation"]
    priors, installed_ic = {}, {}
    for head in ("rank_20d", "sector_neutral_rank_20d"):
        target = f"target_{head}" + (CENTRED_SUFFIX if chain.args.centred else "")
        priors[head] = identity_check(train, validation, target, class_columns=CLASS_COLUMNS, model_score_column="installed")
        installed_ic[head] = chain.ic_on(chain.installed(), head)
    chain.report["priors"] = priors
    chain.report["installed_ic"] = installed_ic
    chain.save()
    print("priors:", json.dumps(priors, indent=1), flush=True)


def score_version(chain: Chain644, name: str, grid_id: str, members: list[Path], *, ensemble: bool = False) -> dict:
    config = candidate_config(grid_id, ensemble=ensemble)
    ml_dir = candidate_ml_dir(name, members, ensemble=ensemble)
    head = target_head(config["phase_v2"]["rank_signal"]["heads"])
    scores = chain.candidate_scores(name, ml_dir, config)
    return {"head": head, "ic": chain.ic_on(scores, head), "ml_dir": str(ml_dir.relative_to(ROOT_DIR))}


def stage_stage1(chain: Chain644) -> None:
    results = chain.report.setdefault("stage1", {})
    ids = list(GRID)[: 1 if chain.args.smoke else None]
    for grid_id in ids:
        version = version_dir(grid_id, 1)
        if not (version / "multitask_model.json").exists():
            results[grid_id] = {"status": "missing", "version": str(version)}
            continue
        entry = score_version(chain, grid_id, grid_id, [version])
        entry["c0"] = viability(version, candidate_config(grid_id))
        entry["c1"] = c1_check(entry["ic"], chain.report["priors"][entry["head"]], chain.report["installed_ic"][entry["head"]])
        results[grid_id] = entry
        chain.save()
        print(f"  stage1 {grid_id}: val IC {entry['ic']['validation'].get('nonoverlap_mean_ic')} C0 {entry['c0']['passes']} "
              f"C1 {entry['c1']['passes']}", flush=True)
    passing = [g for g, e in results.items() if e.get("c0", {}).get("passes") and e.get("c1", {}).get("passes")]
    passing.sort(key=lambda g: results[g]["ic"]["validation"]["nonoverlap_mean_ic"], reverse=True)
    survivors = passing[:MAX_SURVIVORS]
    chain.report["survivors"] = survivors
    if not chain.args.smoke:  # the session reads these side files; a smoke pass must not replace them
        _save(OUT_DIR / f"stage1{chain.tag}.json", {"survivors": survivors})
    chain.save()
    print("stage-1 survivors:", survivors, flush=True)


def stage_stage2(chain: Chain644) -> None:
    results = chain.report.setdefault("stage2", {})
    for grid_id in chain.report.get("survivors", []):
        seeds = {}
        for seed in SEEDS:
            version = version_dir(grid_id, seed)
            if not (version / "multitask_model.json").exists():
                seeds[seed] = None
                continue
            seeds[seed] = score_version(chain, f"{grid_id}_s{seed}", grid_id, [version])
        done = {seed: entry for seed, entry in seeds.items() if entry}
        val = {seed: entry["ic"]["validation"]["nonoverlap_mean_ic"] for seed, entry in done.items()}
        ordered = sorted(val, key=lambda seed: val[seed])
        shipped = ordered[len(ordered) // 2] if ordered else None
        median = {split: {key: statistics.median([e["ic"][split][key] for e in done.values()])
                          for key in ("mean_ic", "nonoverlap_mean_ic", "hac_t")} for split in SPLITS} if done else {}
        head = next(iter(done.values()))["head"] if done else None
        results[grid_id] = {
            "head": head, "seeds": {str(s): e for s, e in seeds.items()}, "median_ic": median, "shipped_seed": shipped,
            "c2": {"passes": len(done) == len(SEEDS) and all(value > 0.0 for value in val.values()), "validation_ic": val},
            "c1_median": c1_check(median, chain.report["priors"][head], chain.report["installed_ic"][head]) if done else None,
            "c0": viability(version_dir(grid_id, shipped), candidate_config(grid_id)) if shipped else None,
        }
        chain.save()
        print(f"  stage2 {grid_id}: seed val ICs {val} shipped s{shipped}", flush=True)


def stage_ensemble(chain: Chain644) -> None:
    stage2 = chain.report.get("stage2", {})
    complete = [g for g, e in stage2.items() if e.get("c2", {}).get("validation_ic") and len(e["c2"]["validation_ic"]) == len(SEEDS)]
    if not complete:
        chain.report["ensemble"] = {"status": "no complete stage-2 candidate"}
        chain.save()
        return
    best = max(complete, key=lambda g: stage2[g]["median_ic"]["validation"]["nonoverlap_mean_ic"])
    members = [version_dir(best, seed) for seed in SEEDS]
    entry = score_version(chain, "E", best, members, ensemble=True)
    entry.update({"recipe": best, "c2": stage2[best]["c2"],
                  "c0": viability(members[0], candidate_config(best)),
                  "c1": c1_check(entry["ic"], chain.report["priors"][entry["head"]], chain.report["installed_ic"][entry["head"]])})
    chain.report["ensemble"] = entry
    chain.save()
    print(f"  ensemble E of {best}: val IC {entry['ic']['validation'].get('nonoverlap_mean_ic')}", flush=True)


def trial_specs(chain: Chain644) -> dict[str, dict]:
    """Every R-MODEL12 trial: the seven seed-1 IDs, each survivor's shipped seed (when not seed 1) and E."""
    specs = {}
    for grid_id, entry in chain.report.get("stage1", {}).items():
        if entry.get("ml_dir"):
            specs[grid_id] = {"name": grid_id, "grid_id": grid_id, "ml_dir": entry["ml_dir"], "kind": "seed1"}
    for grid_id, entry in chain.report.get("stage2", {}).items():
        shipped = entry.get("shipped_seed")
        if shipped and shipped != 1:
            name = f"{grid_id}_s{shipped}"
            specs[name] = {"name": name, "grid_id": grid_id, "ml_dir": entry["seeds"][str(shipped)]["ml_dir"], "kind": "shipped"}
    ensemble = chain.report.get("ensemble") or {}
    if ensemble.get("ml_dir"):
        specs["E"] = {"name": "E", "grid_id": ensemble["recipe"], "ml_dir": ensemble["ml_dir"], "kind": "ensemble"}
    return specs


def trial_scores(chain: Chain644, spec: dict, splits=SPLITS) -> pd.Series:
    config = candidate_config(spec["grid_id"], ensemble=spec["kind"] == "ensemble")
    return chain.candidate_scores(spec["name"], ROOT_DIR / spec["ml_dir"], config, splits=splits)


def stage_aslive(chain: Chain644) -> None:
    base = {split: chain.as_live("base", split, None)["summary"] for split in SPLITS}
    chain.report["baseline_as_live"] = base
    trials = chain.report.setdefault("trials", {})
    for name, spec in trial_specs(chain).items():
        scores = trial_scores(chain, spec)
        as_live = {split: chain.as_live(name, split, scores)["summary"] for split in SPLITS}
        trials[name] = {"spec": spec, "as_live": as_live,
                        "registry": {split: {"median_net_sharpe": as_live[split]["median_net_sharpe"],
                                             "phases": as_live[split]["phases"]} for split in SPLITS}}
        chain.save()


def stage_pbo(chain: Chain644) -> None:
    from evaluation.pbo import probability_of_backtest_overfitting

    names, series = [], []
    for name, spec in trial_specs(chain).items():
        scores = trial_scores(chain, spec)
        daily: dict = {}
        for split in SPLITS:
            daily.update(chain.as_live(name, split, scores)["daily"])
        names.append(name)
        series.append(pd.Series(daily))
    if len(series) < 2:
        chain.report["pbo"] = {"pbo": None, "reason": "fewer than 2 trials"}
        chain.save()
        return
    matrix = pd.concat(series, axis=1, keys=names).sort_index().fillna(0.0)
    matrix.to_parquet(OUT_DIR / "trial_returns.parquet")
    chain.report["pbo"] = probability_of_backtest_overfitting(matrix.to_numpy(), blocks=16)
    chain.save()
    print("PBO:", chain.report["pbo"].get("pbo"), flush=True)


def stage_spanning(chain: Chain644) -> None:
    from evaluation.factor_spanning import build_factor_returns, build_factor_scores, factor_spanning

    frame = chain.frame()
    factors = build_factor_scores(frame)
    backtest = (frame["split"] == "backtest").to_numpy()
    part = frame.loc[backtest, ["date", "target_return_1d"]].copy()
    for column, name in (("f_mom_12_1", "F1"), ("f_mom_20", "F2"), ("f_rev_5", "F3"), ("f_lowvol", "F4"), ("f_high52", "F5")):
        part[name] = factors[column][backtest].to_numpy()
    factor_returns = build_factor_returns(part, ["F1", "F2", "F3", "F4", "F5"])
    result = {}
    for name, spec in trial_specs(chain).items():
        part[name] = trial_scores(chain, spec)[backtest].to_numpy()
        result[name] = factor_spanning(build_factor_returns(part, [name])[name], factor_returns)
    chain.report["spanning"] = result
    chain.save()


def candidate_entries(chain: Chain644) -> dict[str, dict]:
    """The R-MODEL12 candidates: each survivor (seed medians, shipped seed) and E."""
    out = {}
    stage2 = chain.report.get("stage2", {})
    for grid_id, entry in stage2.items():
        shipped = entry.get("shipped_seed")
        if not shipped:
            continue
        out[grid_id] = {"grid_id": grid_id, "trial": grid_id if shipped == 1 else f"{grid_id}_s{shipped}", "head": entry["head"],
                        "ic": entry["median_ic"], "c0": entry["c0"], "c1": entry["c1_median"], "c2": entry["c2"],
                        "members": [str(version_dir(grid_id, shipped).relative_to(ROOT_DIR))], "ensemble": False}
    ensemble = chain.report.get("ensemble") or {}
    if ensemble.get("ml_dir"):
        out["E"] = {"grid_id": ensemble["recipe"], "trial": "E", "head": ensemble["head"], "ic": ensemble["ic"],
                    "c0": ensemble["c0"], "c1": ensemble["c1"], "c2": ensemble["c2"],
                    "members": [str(version_dir(ensemble["recipe"], s).relative_to(ROOT_DIR)) for s in SEEDS], "ensemble": True}
    return out


def clauses_c0_c5(chain: Chain644, candidate: dict) -> dict:
    from v640_research import verdict_as_live

    trial = chain.report.get("trials", {}).get(candidate["trial"], {})
    pbo = (chain.report.get("pbo") or {}).get("pbo")
    as_live_verdict = verdict_as_live(chain.report["baseline_as_live"], trial["as_live"]) if trial.get("as_live") else {"passes": False}
    return {
        "C0": bool((candidate.get("c0") or {}).get("passes")),
        "C1": bool((candidate.get("c1") or {}).get("passes")),
        "C2": bool((candidate.get("c2") or {}).get("passes")),
        "C3": (candidate["ic"].get("backtest") or {}).get("hac_t") is not None and candidate["ic"]["backtest"]["hac_t"] >= 2.0,
        "C4": bool(as_live_verdict.get("passes")),
        "C5": pbo is not None and pbo < 0.5,
    }


def stage_walkforward_pick(chain: Chain644) -> None:
    candidates = candidate_entries(chain)
    checks = {name: clauses_c0_c5(chain, entry) for name, entry in candidates.items()}
    passing = [name for name, c in checks.items() if all(c.values())]
    passing.sort(key=lambda n: chain.report["trials"][candidates[n]["trial"]]["as_live"]["backtest"]["median_net_sharpe"], reverse=True)
    pick = {"order": passing[:2], "configs": {name: f"ml/evaluation/v644/configs/{candidates[name]['grid_id']}.json" for name in passing[:2]},
            "checks": checks}
    chain.report["walkforward_pick"] = pick
    if not chain.args.smoke:
        _save(OUT_DIR / f"walkforward_pick{chain.tag}.json", pick)
    chain.save()
    print("walk-forward order:", pick["order"], flush=True)


def stage_c6(chain: Chain644) -> int:
    summary = json.loads(Path(chain.args.wf_summary).read_text(encoding="utf-8"))
    bootstrap = ((summary.get("summary_by_metric") or {}).get("candidate_ic") or {}).get("cross_window_bootstrap") or {}
    stability = (summary.get("stability_by_metric") or {}).get("candidate_ic") or {}
    passes = bootstrap.get("lower_bound") is not None and bootstrap["lower_bound"] > 0.0 \
        and stability.get("sign_flip_fraction") is not None and stability["sign_flip_fraction"] <= 0.34
    chain.report.setdefault("c6", {})[chain.args.wf_candidate] = {
        "run_id": summary.get("run_id"), "num_windows": summary.get("num_windows"), "mean_ic": bootstrap.get("mean_ic"),
        "lower_bound": bootstrap.get("lower_bound"), "sign_flip_fraction": stability.get("sign_flip_fraction"), "passes": passes}
    chain.save()
    print(f"C6 {chain.args.wf_candidate}: {'PASS' if passes else 'FAIL'}", flush=True)
    return 0 if passes else 3


# ---------------------------------------------------------------- R-TREND1

def trend_config(config: dict, signal: str):
    from portfolio.trend_sleeve import resolve_trend_sleeve_config

    return resolve_trend_sleeve_config({**config["phase_v2"]["trend_sleeve"], "enabled": True, "signal": signal})


def trend_kwargs(config: dict) -> dict:
    from portfolio.sleeve_guard import resolve_sleeve_guard_config

    costs = config["phase_v2"]["costs"]
    return {"commission_bps": float(costs["commission_bps_per_side"]), "min_commission_usd": float(costs["min_commission_usd"]),
            "half_spread_bps": TREND_HALF_SPREAD_BPS,
            "guard": resolve_sleeve_guard_config(config["phase_v2"]["sleeve_guards"].get("trend"))}


def trend_closes(chain: Chain644) -> pd.DataFrame:
    from evaluation.trend_sleeve_backtest import load_daily_closes

    if getattr(chain, "_closes", None) is None:
        chain._closes = load_daily_closes(ROOT_DIR, chain.config, chain.config["phase_v2"]["trend_sleeve"]["symbols"])
    return chain._closes


def trend_run(chain: Chain644, trial: str, window: str, start: str, end: str) -> dict:
    from evaluation.trend_sleeve_backtest import trend_phase_summary

    key = f"trend|{trial}|{window}|{chain.args.max_phases}"
    if key not in chain.memo:
        out = trend_phase_summary(trend_closes(chain), trend_config(chain.config, TREND_TRIALS[trial]), start=start, end=end,
                                  phases=chain.args.max_phases, **trend_kwargs(chain.config))
        daily = out.pop("daily_phase0")
        chain.memo[key] = {"summary": out, "daily": {str(d): float(v) for d, v in daily.items()}}
        chain.save()
    return chain.memo[key]


def stage_trend(chain: Chain644) -> None:
    trend = chain.report.setdefault("trend", {})
    for trial in list(TREND_TRIALS)[: 1 if chain.args.smoke else None]:
        trend[trial] = {window: trend_run(chain, trial, window, *TREND_WINDOWS[window])["summary"] for window in TREND_WINDOWS}
        chain.save()
    chosen = max(trend, key=lambda t: trend[t]["trainval"]["median_net_sharpe"])
    entry = trend[chosen]
    chain.report["trend_choice"] = {
        "chosen": chosen,
        "K2": entry["train"]["median_net_sharpe"] >= 0.0 and entry["validation"]["median_net_sharpe"] >= 0.0
        and entry["trainval"]["median_net_sharpe"] >= 0.30,
        "K3": entry["backtest"]["median_net_sharpe"] > 0.0 and entry["backtest"]["median_max_drawdown"] <= 0.03,
    }
    chain.save()
    print("trend:", json.dumps(chain.report["trend_choice"]), flush=True)


def _sharpe(values) -> float:
    values = np.asarray(list(values), dtype=float)
    values = values[np.isfinite(values)]
    return float(values.mean() / values.std(ddof=1) * np.sqrt(252)) if len(values) > 1 and values.std(ddof=1) > 0 else 0.0


def stage_trend_main(chain: Chain644) -> None:
    choice = chain.report["trend_choice"]["chosen"]
    symbols = chain.config["phase_v2"]["trend_sleeve"]["symbols"]
    out = {}
    for split in SPLITS:
        harness = chain.harness(split)
        key = f"trend_main|{split}|{chain.args.max_phases}"
        if key not in chain.memo:
            from as_live_levers import summarize
            from lean_calibration import ANALYZER_INCLUDE, calibrated_overrides

            mechanisms = harness.v610_mechanisms(chain.config, legacy=False)
            per_phase, daily = [], {}
            with chain.exclude_tickers(harness, symbols):
                for phase in chain.phases():
                    extra = {"log_weights": True} if not daily else {}
                    result = harness.as_live(**dict(calibrated_overrides(harness, phase=phase), **mechanisms, **extra),
                                             include=ANALYZER_INCLUDE)
                    per_phase.append(summarize(result))
                    if not daily:
                        daily = {str(d)[:10]: float(r) for d, r in zip(result.per_date, result.per_date_net_return)}
                        held = {str(t) for row in result.weights_log or [] for t, w in (row or {}).items() if w}
                        chain.memo[f"trend_main_held|{split}"] = sorted(held & set(symbols))
                        chain.memo[f"trend_main_gross|{split}"] = float(result.mean_gross_exposure)
            from v640_research import extended_summary

            chain.memo[key] = {"summary": extended_summary(per_phase), "daily": daily}
            chain.save()
        main_excluded = pd.Series(chain.memo[key]["daily"])
        main_base = pd.Series(chain.as_live("base", split, None)["daily"])
        sleeve = pd.Series(trend_run(chain, choice, split, *TREND_WINDOWS[split])["daily"])
        combined = main_excluded.add(sleeve, fill_value=0.0)
        joined = pd.concat([main_base, sleeve], axis=1, join="inner").dropna()
        out[split] = {
            "main_base_sharpe_phase0": _sharpe(main_base), "main_excluded_sharpe_phase0": _sharpe(main_excluded),
            "sleeve_sharpe_phase0": _sharpe(sleeve), "combined_sharpe_phase0": _sharpe(combined),
            "base_median_net_sharpe": chain.report.get("baseline_as_live", {}).get(split, {}).get("median_net_sharpe")
            or chain.as_live("base", split, None)["summary"]["median_net_sharpe"],
            "excluded_median_net_sharpe": chain.memo[key]["summary"]["median_net_sharpe"],
            "correlation_sleeve_vs_main": float(joined.corr().iloc[0, 1]) if len(joined) > 2 else None,
            "trend_symbols_held_while_excluded": chain.memo.get(f"trend_main_held|{split}"),
            "main_base_annual_vol": float(main_base.std(ddof=1) * np.sqrt(252)),
            "main_excluded_mean_gross_phase0": chain.memo.get(f"trend_main_gross|{split}"),
        }
    backtest, validation = out["backtest"], out["validation"]
    chain.report["trend_main"] = out
    chain.report["units"] = "as-live per_date_net_return and the sleeve's daily return are both fractions of the simulated NAV"
    chain.report["trend_choice"]["K4"] = backtest["correlation_sleeve_vs_main"] is not None and backtest["correlation_sleeve_vs_main"] <= 0.30
    chain.report["trend_choice"]["K5"] = (backtest["combined_sharpe_phase0"] >= backtest["main_base_sharpe_phase0"] + 0.10
                                          and validation["combined_sharpe_phase0"] >= validation["main_base_sharpe_phase0"] - 0.02)
    chain.save()
    print("trend_main:", json.dumps(out, indent=1, default=str), flush=True)


# ---------------------------------------------------------------- holdout and verdict

def stage_holdout(chain: Chain644) -> None:
    holdout = chain.report.setdefault("holdout", {})
    c6 = chain.report.get("c6", {})
    order = (chain.report.get("walkforward_pick") or {}).get("order", [])
    finalist = next((name for name in order if (c6.get(name) or {}).get("passes")), None)
    if finalist and "model" not in holdout:
        candidate = candidate_entries(chain)[finalist]
        spec = trial_specs(chain)[candidate["trial"]]
        chain.report["holdout_reads"].append({"trial": finalist, "what": "IC on its target and as-live Sharpe on the holdout"})
        scores = trial_scores(chain, spec, splits=("holdout",))
        ic = chain.ic_on(scores, candidate["head"], splits=("holdout",))["holdout"]
        sharpe = chain.as_live(spec["name"], "holdout", scores)["summary"]["median_net_sharpe"]
        base = chain.as_live("base", "holdout", None)["summary"]["median_net_sharpe"]
        holdout["model"] = {"finalist": finalist, "ic": ic.get("mean_ic"), "median_net_sharpe": sharpe,
                            "baseline_median_net_sharpe": base,
                            "passes": ic.get("mean_ic") is not None and ic["mean_ic"] > 0 and sharpe >= base - 0.10}
        chain.save()
    choice = chain.report.get("trend_choice") or {}
    if choice and all(choice.get(k) for k in ("K2", "K3", "K4", "K5")) and "trend" not in holdout:
        start, end = chain.config["phase1"]["windows"]["holdout"]["start"], "2026-10-16"
        chain.report["holdout_reads"].append({"trial": choice["chosen"], "what": "trend sleeve net Sharpe on the holdout"})
        summary = trend_run(chain, choice["chosen"], "holdout", start, end)["summary"]
        holdout["trend"] = {"trial": choice["chosen"], "median_net_sharpe": summary["median_net_sharpe"],
                            "passes": summary["median_net_sharpe"] > 0.0}
        chain.save()


def stage_verdict(chain: Chain644) -> None:
    candidates = candidate_entries(chain)
    checks = {name: clauses_c0_c5(chain, entry) for name, entry in candidates.items()}
    for name in checks:
        if name in chain.report.get("c6", {}):
            checks[name]["C6"] = chain.report["c6"][name]["passes"]
    model = (chain.report.get("holdout") or {}).get("model")
    winner = None
    if model:
        checks[model["finalist"]]["C7"] = model["passes"]
        if all(checks[model["finalist"]].values()) and {"C6", "C7"} <= set(checks[model["finalist"]]):
            winner = model["finalist"]
    choice = dict(chain.report.get("trend_choice") or {})
    trend_hold = (chain.report.get("holdout") or {}).get("trend")
    choice["K6"] = bool(trend_hold and trend_hold["passes"])
    trend_passes = all(choice.get(k) for k in ("K2", "K3", "K4", "K5", "K6"))
    chain.report["verdict"] = {
        "R-MODEL12": {"checks": checks, "winner": winner,
                      "winner_spec": candidates.get(winner) if winner else None},
        "R-TREND1": {"chosen": choice.get("chosen"), "signal": TREND_TRIALS.get(choice.get("chosen", ""), None),
                     "checks": {k: choice.get(k) for k in ("K2", "K3", "K4", "K5", "K6")}, "passes": trend_passes},
    }
    chain.save()
    print("verdict:", json.dumps(chain.report["verdict"], indent=1, default=str), flush=True)


STAGES = {"priors": stage_priors, "stage1": stage_stage1, "stage2": stage_stage2, "ensemble": stage_ensemble,
          "aslive": stage_aslive, "pbo": stage_pbo, "spanning": stage_spanning, "trend": stage_trend,
          "trend_main": stage_trend_main, "walkforward_pick": stage_walkforward_pick, "c6": stage_c6,
          "holdout": stage_holdout, "verdict": stage_verdict}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "v644_full_dataset.csv"))
    parser.add_argument("--stages", nargs="*", default=["priors", "stage1"])
    parser.add_argument("--max-phases", type=int, default=10)
    parser.add_argument("--out", default=str(OUT_DIR / "research.json"))
    parser.add_argument("--smoke", action="store_true", help="2 phases, one grid ID and one trend trial")
    parser.add_argument("--wf-candidate", default=None)
    parser.add_argument("--wf-summary", default=None)
    parser.add_argument("--centred", action="store_true", help="R-MODEL13: ICs and priors on group-centred labels")
    parser.add_argument("--memo", default=None, help="share another chain's memo (as-live runs are rule-independent)")
    args = parser.parse_args()
    args.asof_labels = str(OUT_DIR / "unused_asof_labels.parquet")
    if args.smoke:
        args.max_phases = 2
    chain = Chain644(args)
    status = 0
    for stage in args.stages:
        print(f"=== stage {stage}", flush=True)
        result = STAGES[stage](chain)
        if isinstance(result, int):
            status = max(status, result)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
