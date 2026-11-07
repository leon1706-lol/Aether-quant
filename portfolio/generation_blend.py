"""Several model generations sharing one book (V6.6.1): how capital moves between them, and the blended weights the target-weights path trades.

A generation is a frozen signal producer with its own target weights. They blend upstream of `ml/target_weights.csv`, so one file reaches Lean, the offline engine and
the live path, and a generation can't have a code path of its own. A blend is convex, so a cap every generation respects holds for the book (`formal/AetherFormal/GenerationBlend.lean`).

Two ways to move capital:

- `ladder`: the ramping generation gains capital at a fixed rate, the older ones give it up in proportion to what they hold, 70/30, 64/36, ... 0/100. One gains at a time.
- `dynamic`: each generation's target comes from its own record. Its score is its Sharpe so far shrunk toward what it claimed at admission, and targets are proportional to the
  scores above a floor, which is the best split of uncorrelated books of equal risk. Any number can hold capital at once: an old generation still earning keeps a share, one that stops
  fades out, and shares move a fixed fraction of the way to their targets each session, so nothing jumps, a new generation included.

Evidence alone is slow: at one false alarm in five years a decay detector needs over a year to see a Sharpe fall from 1 to 0. So shrinkage keeps a short record from moving much capital, and
a generation's capital leaves at once only on a guard trip or a dead state. Taking risk off is not rate-capped.

Stdlib only at import. Non-finite input holds the shares; output is always in [0, 1] and sums to at most 1, with the rest in T-bills.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

GAINING_STAGES = frozenset({"ramping"})
HOLDING_STAGES = frozenset({"active", "fading", "winding_down", "ramping"})
DEAD_STATES = frozenset({"dead"})
SHARE_TOLERANCE = 1e-9
MODES = ("ladder", "dynamic")
EW_HALF_LIFE_SESSIONS = 126.0
EW_MIN_SESSIONS = 20


@dataclass(frozen=True)
class GlidePolicy:
    glide_sessions: int = 252
    entry_share: float = 0.30
    retire_share: float = 0.05  # 10% of a 0.0127 weight is below the 0.002 deadband: a residue that could never trade
    blend_every: int = 21
    tier2_paper_cap: float = 0.30
    hold_on_watch: bool = False
    accelerate_on_decaying: float = 1.0
    mode: str = "ladder"
    half_life_sessions: int = 126  # dynamic: sessions to move half way to a target
    prior_sessions: float = 252.0  # dynamic: how many sessions of record weigh as much as the claim at admission
    score_floor: float = 0.0  # dynamic: a score at or below this earns no share
    max_generations: int = 4
    min_evidence_sessions: int = 60  # dynamic: with no generation past this and no positive score, nothing is known yet, so hold


def _finite(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def resolve_glide_policy(raw: Mapping | None) -> GlidePolicy:
    raw = raw or {}
    defaults = GlidePolicy()

    def share(name: str) -> float:
        return max(0.0, min(1.0, _finite(raw.get(name), getattr(defaults, name))))

    return GlidePolicy(
        glide_sessions=max(1, int(_finite(raw.get("glide_sessions"), defaults.glide_sessions))), entry_share=share("entry_share"), retire_share=share("retire_share"),
        blend_every=max(1, int(_finite(raw.get("blend_every"), defaults.blend_every))), tier2_paper_cap=share("tier2_paper_cap"), hold_on_watch=bool(raw.get("hold_on_watch", defaults.hold_on_watch)),
        accelerate_on_decaying=max(1.0, _finite(raw.get("accelerate_on_decaying"), defaults.accelerate_on_decaying)),
        mode=str(raw.get("mode")) if raw.get("mode") in MODES else defaults.mode,
        half_life_sessions=max(1, int(_finite(raw.get("half_life_sessions"), defaults.half_life_sessions))),
        prior_sessions=max(0.0, _finite(raw.get("prior_sessions"), defaults.prior_sessions)),
        score_floor=_finite(raw.get("score_floor"), defaults.score_floor),
        max_generations=max(1, int(_finite(raw.get("max_generations"), defaults.max_generations))),
        min_evidence_sessions=max(0, int(_finite(raw.get("min_evidence_sessions"), defaults.min_evidence_sessions))),
    )


def blend_generation_rows(rows_by_generation: Mapping[str, Mapping[str, float]], shares: Mapping[str, float]) -> dict[str, float]:
    """The book: each generation's weights times its share, summed per name. A generation with no row counts as flat; a name that nets to zero leaves the row."""
    book: dict[str, float] = {}
    for generation, row in rows_by_generation.items():
        share = _finite(shares.get(generation, 0.0), 0.0)
        if share <= 0.0:
            continue
        for ticker, weight in row.items():
            book[ticker] = book.get(ticker, 0.0) + share * _finite(weight, 0.0)
    return {ticker: weight for ticker, weight in book.items() if weight != 0.0}


def _evidence_multiplier(states: Mapping[str, str], ramping: str, older: list[str], policy: GlidePolicy) -> float:
    if policy.hold_on_watch and states.get(ramping) in ("watch", "decaying"):
        return 0.0
    if policy.accelerate_on_decaying > 1.0 and any(states.get(name) == "decaying" for name in older):
        return policy.accelerate_on_decaying
    return 1.0


def update_generation_shares(
    shares: Mapping[str, float], stages: Mapping[str, str], states: Mapping[str, str], caps: Mapping[str, float], policy: GlidePolicy, *, sessions: int = 1,
) -> dict[str, float]:
    """The shares after `sessions` sessions. A generation out of a holding stage, or dead, or with a guard trip (state `tripped`), drops to zero at once; a new ramping
    generation enters at `entry_share`; below `retire_share` a generation is gone, and what it held passes to the ramping one up to its cap. What no one may hold stays in T-bills."""
    numbers = {name: _finite(value, math.nan) for name, value in shares.items()}
    if any(math.isnan(value) or value < 0.0 for value in numbers.values()) or sum(numbers.values()) > 1.0 + SHARE_TOLERANCE:
        return {name: _finite(value, 0.0) for name, value in shares.items()}  # damaged shares: hold, don't guess
    sessions = max(0, int(sessions))
    out: dict[str, float] = {}
    for name, stage in stages.items():
        value = numbers.get(name, 0.0)
        if stage not in HOLDING_STAGES or states.get(name) in DEAD_STATES or states.get(name) == "tripped":
            out[name] = 0.0
        else:
            out[name] = value
    ramping = [name for name in stages if stages[name] in GAINING_STAGES and states.get(name) not in DEAD_STATES and states.get(name) != "tripped"]
    # One generation gains at a time, the oldest ramping: its successor waits, so two handovers can't overlap.
    gainer = sorted(ramping)[0] if ramping else None
    if gainer is None:
        return _retire_small(out, None, 1.0, policy)
    cap = max(0.0, min(1.0, _finite(caps.get(gainer, 1.0), 1.0)))
    older = [name for name in out if name != gainer and out[name] > 0.0]
    if out[gainer] <= 0.0:
        wanted = min(cap, policy.entry_share)
    else:
        step = (1.0 - policy.entry_share) / float(policy.glide_sessions) * _evidence_multiplier(states, gainer, older, policy) * sessions
        wanted = min(cap, out[gainer] + step)
    increase = max(0.0, wanted - out[gainer])
    from_tbills = min(increase, max(0.0, 1.0 - sum(out.values())))
    give = sum(out[name] for name in older)
    taken = min(increase - from_tbills, give)
    if give > 0.0:
        for name in older:
            out[name] -= taken * (out[name] / give)
    out[gainer] += from_tbills + taken
    return _retire_small(out, gainer, cap, policy)


def _retire_small(shares: dict[str, float], gainer: str | None, cap: float, policy: GlidePolicy) -> dict[str, float]:
    """Below `retire_share` a generation is gone, and what it held passes to the gainer up to its cap; the rest stays in T-bills."""
    out = dict(shares)
    for name, value in shares.items():
        # The tolerance keeps a share of exactly `retire_share` in float arithmetic from reading as just under it, as the exact-arithmetic model says.
        if name != gainer and 0.0 < value < policy.retire_share - SHARE_TOLERANCE:
            out[name] = 0.0
            if gainer is not None:
                out[gainer] = min(cap, out[gainer] + value)
    return {name: max(0.0, min(1.0, value)) for name, value in out.items()}


def ew_update(state: tuple[float, float, float, int], value: float, half_life: float = EW_HALF_LIFE_SESSIONS) -> tuple[float, float, float, int]:
    """One more session of an exponentially weighted record: (weight, weighted sum, weighted squares, sessions). A non-finite return leaves it as it is."""
    number = _finite(value, math.nan)
    if math.isnan(number):
        return state
    decay = 0.5 ** (1.0 / float(half_life))
    weight, total, squares, sessions = state
    return weight * decay + 1.0, total * decay + number, squares * decay + number * number, sessions + 1


def ew_sharpe(state: tuple[float, float, float, int], *, sessions_per_year: float = 252.0) -> float | None:
    """The annualised Sharpe of that record. None until it holds `EW_MIN_SESSIONS` or if it has no variance."""
    weight, total, squares, sessions = state
    if sessions < EW_MIN_SESSIONS or weight <= 0.0:
        return None
    mean = total / weight
    variance = squares / weight - mean * mean
    return mean / math.sqrt(variance) * math.sqrt(sessions_per_year) if variance > 0.0 else None


def shrunk_sharpe(observed: float | None, sessions: int, prior: float, prior_sessions: float) -> float:
    """What a generation's Sharpe is believed to be: its record and its claim, weighted by sessions of record against `prior_sessions`. No usable record leaves the claim."""
    claim = _finite(prior, 0.0)
    number = _finite(observed, math.nan)
    count = max(0.0, _finite(sessions, 0.0))
    if math.isnan(number) or count + prior_sessions <= 0.0:
        return claim
    return (count * number + prior_sessions * claim) / (count + prior_sessions)


def dynamic_targets(scores: Mapping[str, float], caps: Mapping[str, float], policy: GlidePolicy) -> dict[str, float]:
    """Each generation's target: proportional to its score above the floor, for the best `max_generations`. What a capped generation can't hold goes to the others, and what none may hold stays in T-bills."""
    usable = {name: _finite(score, math.nan) - policy.score_floor for name, score in scores.items()}
    positive = sorted(((value, name) for name, value in usable.items() if value > 0.0), key=lambda item: (-item[0], item[1]))[: policy.max_generations]
    targets = {name: 0.0 for name in scores}
    open_names = {name: value for value, name in positive}
    remaining = 1.0
    while open_names and remaining > SHARE_TOLERANCE:
        total = sum(open_names.values())
        over = {
            name: max(0.0, min(1.0, _finite(caps.get(name, 1.0), 1.0))) for name, value in open_names.items()
            if remaining * value / total > max(0.0, min(1.0, _finite(caps.get(name, 1.0), 1.0))) + SHARE_TOLERANCE
        }
        if not over:
            for name, value in open_names.items():
                targets[name] = remaining * value / total
            break
        for name, cap in over.items():
            targets[name] = cap
            remaining -= cap
            del open_names[name]
    return targets


def step_toward(shares: Mapping[str, float], targets: Mapping[str, float], fraction: float, retire_share: float) -> dict[str, float]:
    """A fixed fraction of the way to the targets, so nothing jumps. A blend of two allocations that each sum to at most one sums to at most one (proved in Lean). A generation headed to nothing
    is gone below `retire_share`, as it couldn't trade its residue."""
    step = max(0.0, min(1.0, _finite(fraction, 0.0)))
    out: dict[str, float] = {}
    for name in sorted(set(shares) | set(targets)):
        before, target = _finite(shares.get(name, 0.0), 0.0), _finite(targets.get(name, 0.0), 0.0)
        value = before + step * (target - before)
        out[name] = 0.0 if target <= 0.0 and value < retire_share - SHARE_TOLERANCE else value
    return out


def dynamic_generation_shares(
    shares: Mapping[str, float], stages: Mapping[str, str], states: Mapping[str, str], evidence: Mapping[str, Mapping], caps: Mapping[str, float], policy: GlidePolicy, *, sessions: int = 1,
) -> dict[str, float]:
    """The `dynamic` mode. `evidence` holds, per generation, `ew_sharpe`, `sessions` and `prior`. A generation out of a holding stage, dead or tripped drops to zero at once, whatever its score;
    `winding_down` aims for zero. With no positive score and no generation past `min_evidence_sessions`, nothing is known yet, so shares hold."""
    numbers = {name: _finite(value, math.nan) for name, value in shares.items()}
    if any(math.isnan(value) or value < 0.0 for value in numbers.values()) or sum(numbers.values()) > 1.0 + SHARE_TOLERANCE:
        return {name: _finite(value, 0.0) for name, value in shares.items()}
    now = {
        name: 0.0 if stage not in HOLDING_STAGES or states.get(name) in DEAD_STATES or states.get(name) == "tripped" else numbers.get(name, 0.0)
        for name, stage in stages.items()
    }
    scores: dict[str, float] = {}
    seasoned = False
    for name, stage in stages.items():
        if stage not in HOLDING_STAGES or stage == "winding_down" or states.get(name) in DEAD_STATES or states.get(name) == "tripped":
            scores[name] = -math.inf
            continue
        record = evidence.get(name) or {}
        count = int(_finite(record.get("sessions"), 0.0))
        seasoned = seasoned or count >= policy.min_evidence_sessions
        scores[name] = shrunk_sharpe(record.get("ew_sharpe"), count, _finite(record.get("prior"), 0.0), policy.prior_sessions)
    finite_scores = {name: (score if math.isfinite(score) else policy.score_floor - 1.0) for name, score in scores.items()}
    targets = dynamic_targets(finite_scores, caps, policy)
    if not any(value > 0.0 for value in targets.values()) and not seasoned:
        return {name: max(0.0, min(1.0, value)) for name, value in now.items()}
    fraction = 1.0 - 0.5 ** (max(0, int(sessions)) / float(policy.half_life_sessions))
    return {name: max(0.0, min(1.0, value)) for name, value in step_toward(now, targets, fraction, policy.retire_share).items()}


def blend_due(*, decided_today: bool, sessions_since_blend: int, guard_tripped: bool, policy: GlidePolicy) -> bool:
    """Whether to write a blended row. A row retargets every name and resets drift, so not daily: on a generation's decision day, every `blend_every` sessions, or on a guard trip."""
    return bool(decided_today or guard_tripped or int(sessions_since_blend) >= policy.blend_every)
