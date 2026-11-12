"""R-GLIDE1 (V6.6.1): which handover policy loses least to an oracle, when new generations often have no alpha and old ones decay.

It simulates with the running code (`update_generation_shares`, `blend_due`, `decay_state`'s statistic), so what is calibrated is what would trade. Each year brings a generation of true
Sharpe `sharpe` with probability 1 - `zero_alpha_probability`, otherwise zero; a generation's alpha halves every `half_life_years`. Returns are correlated across generations.
The oracle holds, each session, the generation with the highest true Sharpe. Regret is the gap in annualised Sharpe to that oracle, and the rule also limits how long capital sits
mostly on a generation with no alpha.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

from evaluation.alpha_decay import DecayConfig
from portfolio.generation_blend import (
    EW_HALF_LIFE_SESSIONS,
    GlidePolicy,
    blend_due,
    dynamic_generation_shares,
    ew_sharpe,
    ew_update,
    update_generation_shares,
)
from typing import Any

TRADING_DAYS = 252
FALLBACK_POLICY = "fixed_252"
VOL = 0.01
SWITCH_COST_PER_TURNOVER = 0.0005
DEADBAND = 0.002


def default_configs() -> list[dict]:
    """The grid of simulated worlds (Sharpe, alpha half-life, correlation, zero-alpha probability) the glide calibration runs over."""
    return [
        {"sharpe": sharpe, "half_life_years": half_life, "correlation": correlation, "zero_alpha_probability": zero}
        for sharpe in (0.5, 1.0) for half_life in (1.0, 2.0, 3.0) for correlation in (0.0, 0.3, 0.6) for zero in (0.5, 0.8)
    ]


def default_policies() -> list[dict]:
    """The handover policies the glide calibration compares: fixed glides of several lengths and the evidence-driven variants."""
    fixed = [{"name": f"fixed_{sessions}", "kind": "glide", "glide_sessions": sessions} for sessions in (126, 252, 504)]
    evidence = [
        {"name": "fixed_252_hold_on_watch", "kind": "glide", "glide_sessions": 252, "hold_on_watch": True},
        {"name": "fixed_252_accelerate", "kind": "glide", "glide_sessions": 252, "accelerate_on_decaying": 2.0},
        {"name": "fixed_252_hold_and_accelerate", "kind": "glide", "glide_sessions": 252, "hold_on_watch": True, "accelerate_on_decaying": 2.0},
    ]
    return [{"name": "instant", "kind": "instant"}, {"name": "equal", "kind": "equal"}, *fixed, *evidence]


def glide2_policies() -> list[dict]:
    """R-GLIDE2's grid: the dynamic mode, and the two it must be judged against. Four generations may hold capital at once."""
    grid = [
        {
            "name": f"dynamic_h{half_life}_p{prior}_f{int(floor * 100):02d}_b{blend}", "kind": "dynamic", "half_life_sessions": half_life, "prior_sessions": float(prior), "score_floor": floor,
            "blend_every": blend, "max_generations": 4,
        }
        for half_life in (63, 126) for prior in (126, 252, 504) for floor in (0.0, 0.2) for blend in (5, 21)
    ]
    return [{"name": "fixed_252", "kind": "glide", "glide_sessions": 252}, {"name": "equal", "kind": "equal"}, *grid]


def simulate_generations(config: Mapping[str, Any], seed: int, *, years: int = 8) -> dict[str, Any]:
    """{"true_sharpe": sessions x generations, "returns": sessions x generations, "born": first session of each}. A generation exists from its birth."""
    rng = np.random.default_rng(seed)
    sessions = years * TRADING_DAYS
    generations = years
    born = np.arange(generations) * TRADING_DAYS
    has_alpha = rng.random(generations) >= float(config["zero_alpha_probability"])
    has_alpha[0] = True  # the incumbent is the one that won its place
    decay = 0.5 ** (1.0 / (float(config["half_life_years"]) * TRADING_DAYS))
    true = np.zeros((sessions, generations))
    for index in range(generations):
        if has_alpha[index]:
            age = np.maximum(0, np.arange(sessions) - born[index])
            true[:, index] = float(config["sharpe"]) * decay ** age
            true[: born[index], index] = 0.0
    common = rng.normal(size=(sessions, 1))
    own = rng.normal(size=(sessions, generations))
    rho = float(config["correlation"])
    shocks = math.sqrt(rho) * common + math.sqrt(1.0 - rho) * own
    returns = true / math.sqrt(TRADING_DAYS) * VOL + VOL * shocks
    return {"true_sharpe": true, "returns": returns, "born": born, "has_alpha": has_alpha, "claimed_sharpe": float(config["sharpe"])}


def _cusum_step(level: np.ndarray, returns: np.ndarray, expected: np.ndarray, config: DecayConfig) -> np.ndarray:
    steps = expected / math.sqrt(TRADING_DAYS) - returns / VOL - config.slack / math.sqrt(TRADING_DAYS)
    return np.maximum(0.0, level + steps)


def _state_of(level: float, config: DecayConfig) -> str:
    if level >= config.threshold * config.dead_multiple:
        return "dead"
    if level >= config.threshold:
        return "decaying"
    if level >= config.threshold * config.watch_fraction:
        return "watch"
    return "healthy"


def run_policy(world: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    """A path of shares and what they earned, net of turnover cost, with blended rows only when due and the deadband on."""
    returns, true, born = world["returns"], world["true_sharpe"], world["born"]
    sessions, generations = returns.shape
    glide = GlidePolicy(
        glide_sessions=int(policy.get("glide_sessions", 252)), hold_on_watch=bool(policy.get("hold_on_watch", False)),
        accelerate_on_decaying=float(policy.get("accelerate_on_decaying", 1.0)), entry_share=float(policy.get("entry_share", 0.30)),
        mode="dynamic" if policy["kind"] == "dynamic" else "ladder", half_life_sessions=int(policy.get("half_life_sessions", 126)), prior_sessions=float(policy.get("prior_sessions", 252.0)),
        score_floor=float(policy.get("score_floor", 0.0)), blend_every=int(policy.get("blend_every", 21)), max_generations=int(policy.get("max_generations", 4)),
    )
    records = [(0.0, 0.0, 0.0, 0) for _ in range(generations)]
    holders_total = 0
    traded_total = 0.0
    kind = policy["kind"]
    names = [f"g{index}" for index in range(generations)]
    wanted = {names[0]: 1.0}
    held = np.zeros(generations)
    held[0] = 1.0
    level = np.zeros(generations)
    earned = np.zeros(sessions)
    zero_alpha_majority = 0
    since_blend = 0
    config = DecayConfig()
    # Every generation is judged against the same claim, its selection Sharpe halved: a zero-alpha one also won its round, and nobody can know its true alpha when it arrives.
    expected = np.full(generations, float(world["claimed_sharpe"]) * 0.5)
    retired = np.zeros(generations, dtype=bool)
    births = set(born.tolist())
    for session in range(sessions):
        alive = born <= session
        level = _cusum_step(level, returns[session], expected, config) * alive
        states = {names[index]: _state_of(float(level[index]), config) for index in range(generations)}
        retired |= np.array([states[name] == "dead" for name in names]) & alive
        new_today = bool(session in births and session > 0)
        if kind == "instant":
            if new_today:
                wanted = {names[int(np.nonzero(born == session)[0][0])]: 1.0}
        elif kind == "equal":
            live = [names[index] for index in np.nonzero(alive & ~retired)[0]]
            wanted = {name: 1.0 / len(live) for name in live} if live else {}
        elif kind == "dynamic":
            living = np.nonzero(alive)[0]
            for index in living:
                records[index] = ew_update(records[index], float(returns[session, index]), EW_HALF_LIFE_SESSIONS)
            stages = {names[index]: "retired" if retired[index] else "active" for index in living}
            evidence = {names[index]: {"ew_sharpe": ew_sharpe(records[index]), "sessions": records[index][3], "prior": float(world["claimed_sharpe"]) * 0.5} for index in living}
            wanted = dynamic_generation_shares({name: wanted.get(name, 0.0) for name in stages}, stages, states, evidence, {}, glide)
        else:
            stages = {}
            for index in np.nonzero(alive)[0]:
                name = names[index]
                if retired[index]:
                    stages[name] = "retired"
                elif wanted.get(name, 0.0) >= 1.0 - 1e-9 and sum(1 for value in wanted.values() if value > 0.0) <= 1:
                    stages[name] = "active"
                else:
                    stages[name] = "ramping" if born[index] > 0 and index >= _newest_active(wanted, names) else "active"
            wanted = update_generation_shares({name: wanted.get(name, 0.0) for name in stages}, stages, states, {}, glide)
        target = np.array([wanted.get(name, 0.0) for name in names])
        earned[session] = float(held @ returns[session])
        since_blend += 1
        changed = np.abs(target - held).sum()
        if blend_due(decided_today=new_today, sessions_since_blend=since_blend, guard_tripped=bool(np.any(retired & (held > 0.0))), policy=glide) and changed > DEADBAND:
            earned[session] -= changed * SWITCH_COST_PER_TURNOVER
            traded_total += changed
            held = target
            since_blend = 0
        no_alpha = true[session] <= 0.0
        if float(held[no_alpha].sum()) > 0.5:
            zero_alpha_majority += 1
        holders_total += int((held >= glide.retire_share).sum())
    years = sessions / TRADING_DAYS
    return {
        "daily": earned, "zero_alpha_majority_share": zero_alpha_majority / sessions, "mean_holders": holders_total / sessions, "turnover_per_year": traded_total / years,
    }


def _newest_active(wanted: Mapping[str, float], names: Sequence[str]) -> int:
    """Generations after the newest one holding capital wait their turn; the one directly at or after it may ramp."""
    holding = [index for index, name in enumerate(names) if wanted.get(name, 0.0) > 0.0]
    return (holding[0] + 1) if holding else 0


def oracle_daily(world: Mapping[str, Any]) -> np.ndarray:
    """The daily return of an oracle that always holds the generations with the best true Sharpe, the calibration's upper bound."""
    true, returns, born = world["true_sharpe"], world["returns"], world["born"]
    out = np.zeros(true.shape[0])
    for session in range(true.shape[0]):
        alive = born <= session
        pick = int(np.argmax(np.where(alive, true[session], -np.inf)))
        out[session] = returns[session, pick]
    return out


def _sharpe(daily: np.ndarray) -> float:
    deviation = daily.std(ddof=1)
    return float(daily.mean() / deviation * math.sqrt(TRADING_DAYS)) if deviation > 0.0 else 0.0


def _score_worlds(job: tuple[Any, ...]) -> dict[str, Any]:
    """One config's worlds, for every policy. A worker's unit of work, so the result can't depend on how many workers ran."""
    config, config_index, per_config, policies, seed, years = job
    out: dict[str, dict[str, list[float]]] = {policy["name"]: {"regret": [], "majority": [], "holders": [], "turnover": []} for policy in policies}
    for path in range(per_config):
        world = simulate_generations(config, seed * 1_000_003 + config_index * 1009 + path, years=years)
        oracle = _sharpe(oracle_daily(world))
        for policy in policies:
            result = run_policy(world, policy)
            row = out[policy["name"]]
            row["regret"].append(oracle - _sharpe(result["daily"]))
            row["majority"].append(result["zero_alpha_majority_share"])
            row["holders"].append(result["mean_holders"])
            row["turnover"].append(result["turnover_per_year"])
    return out


def evaluate_policies(configs: Sequence[Mapping], policies: Sequence[Mapping], *, paths: int = 2000, seed: int = 1, years: int = 8, workers: int = 1) -> dict[str, Any]:
    """{policy: median regret, time above half of capital on a zero-alpha generation, generations holding capital, turnover}. Every policy meets the same fixed-seed worlds, across all the configs."""
    per_config = max(1, paths // max(1, len(configs)))
    jobs = [(config, index, per_config, list(policies), seed, years) for index, config in enumerate(configs)]
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(_score_worlds, jobs))
    else:
        parts = [_score_worlds(job) for job in jobs]
    report = {}
    for policy in policies:
        name = policy["name"]
        merged = {key: [value for part in parts for value in part[name][key]] for key in ("regret", "majority", "holders", "turnover")}
        report[name] = {
            "median_regret": float(np.median(merged["regret"])), "zero_alpha_majority_share": float(np.mean(merged["majority"])), "mean_holders": float(np.mean(merged["holders"])),
            "turnover_per_year": float(np.mean(merged["turnover"])), "paths": len(merged["regret"]),
            "parameters": sum(key in policy for key in ("glide_sessions", "hold_on_watch", "accelerate_on_decaying", "half_life_sessions", "prior_sessions", "score_floor", "blend_every")),
        }
    return report


def pick_glide2(results: Mapping[str, Mapping], *, baseline: str = "fixed_252", tie: float = 0.005) -> dict[str, Any]:
    """R-GLIDE2: the dynamic policy with the lowest median regret among those no worse than the baseline on zero-alpha time, and it replaces the baseline only if its regret is no worse than the
    baseline's, within `tie`. Ties among dynamic policies go to less turnover. The owner asked for the dynamic form, so no worse is enough: it holds several generations, and the ladder can't."""
    base = results[baseline]
    dynamic = {name: row for name, row in results.items() if name.startswith("dynamic_")}
    eligible = {name: row for name, row in dynamic.items() if row["zero_alpha_majority_share"] <= base["zero_alpha_majority_share"] + 1e-12}
    report = {"baseline": baseline, "baseline_row": dict(base), "eligible": sorted(eligible), "meets_r_glide1_limit": sorted(name for name, row in results.items() if row["zero_alpha_majority_share"] <= 0.20)}
    if not eligible:
        return {**report, "policy": baseline, "adopted": False, "reason": "no dynamic policy is as good on zero-alpha time"}
    best = min(row["median_regret"] for row in eligible.values())
    close = [name for name, row in eligible.items() if row["median_regret"] <= best + tie]
    chosen = sorted(close, key=lambda name: (eligible[name]["turnover_per_year"], name))[0]
    adopted = eligible[chosen]["median_regret"] <= base["median_regret"] + tie
    reason = "no worse than the ladder on both counts" if adopted else "its regret is worse than the ladder's"
    return {**report, "policy": chosen if adopted else baseline, "best_dynamic": chosen, "best_dynamic_row": dict(eligible[chosen]), "adopted": adopted, "reason": reason}


def pick_policy(results: Mapping[str, Mapping], *, max_zero_alpha_share: float = 0.20, tie: float = 0.005) -> dict[str, Any]:
    """R-GLIDE1: the lowest median regret among policies whose time mostly on a zero-alpha generation is at most 20%. Ties go to fewer parameters. None qualifying: fixed 252."""
    qualifying = {name: row for name, row in results.items() if row["zero_alpha_majority_share"] <= max_zero_alpha_share}
    if not qualifying:
        return {"policy": FALLBACK_POLICY, "reason": "no policy qualified", "results": dict(results)}
    best = min(row["median_regret"] for row in qualifying.values())
    close = [name for name, row in qualifying.items() if row["median_regret"] <= best + tie]
    chosen = sorted(close, key=lambda name: (qualifying[name]["parameters"], qualifying[name]["median_regret"], name))[0]
    return {"policy": chosen, "reason": "lowest median regret among qualifying policies, ties to fewer parameters", "results": dict(results)}
