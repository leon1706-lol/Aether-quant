"""The multi-asset model book as a definition, and the one function that turns it into a row (V6.6.9).

The book is a blend of generations: a crypto trend sleeve and a model-driven book, each a `SleeveSpec` sized by `signal_to_weights`.
Three callers need the same row and must not drift: the research engine (`evaluation/model_book_round.py`), the daily decision tool
(`scripts/model_book_decide.py`) and `main.py` in its default-off in-Lean mode. Each calls `row_for_session`; they differ only in
where the closes and the scores come from. Pure: no Lean, no file reads, no clock. pandas is imported lazily, so a Lean start that
never runs the model book pays nothing (rule 11).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from portfolio.generation_blend import blend_generation_rows

if TYPE_CHECKING:
    import pandas as pd

    from portfolio.premia_signals import ResearchPanel, SleeveSpec, WeightSettings

CLASSES = ("equity", "bond", "forex", "crypto")
PHASES = 5
HEAD_TABLES = ("ml_a1",)
RANK_HEADS = ("rank_20d", "rank_5d")


def phase_offsets(rebalance_every: int, phases: int = PHASES) -> list[int]:
    """The start offsets a rebalance cycle is averaged over (the same list `evaluation.premia_research.phase_offsets` gives)."""
    return sorted({int(i * rebalance_every / phases) for i in range(phases)})


# --- the definition ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BookPart:
    """One generation's share of the blended book and the spec that produces its rows."""

    generation: str
    share: float
    kind: str  # "sleeve" (a rule sleeve, default sizing) or "book" (the model book, the round's sizing)
    spec: Mapping[str, Any]
    phase_index: int = 0


@dataclass(frozen=True)
class BlendDefinition:
    """The installed book: its parts, when its rows start counting rebalances, and the Lean run that pins it."""

    parts: tuple[BookPart, ...]
    history_start: str
    pinned_run: str | None = None
    shares: Mapping[str, float] = field(default_factory=dict)
    settings: Mapping[str, Any] | None = None  # the book part's WeightSettings fields; the sleeve parts keep the defaults


def parse_definition(raw: Mapping[str, Any]) -> BlendDefinition:
    """The blend shape (`{"kind": "blend", "parts": [...]}`) or the single-rule shape every earlier candidate file uses
    (`{"survivors": [...], "method": ..., "phase_index": ...}`), which reads as one sleeve at share 1."""
    if raw.get("kind") == "blend":
        parts = tuple(
            BookPart(str(part["generation"]), float(part["share"]), "book" if "book" in part else "sleeve", dict(part.get("book") or part["sleeve"]), int(part.get("phase_index", 0)))
            for part in raw["parts"]
        )
        total = sum(part.share for part in parts)
        if not parts or not math.isclose(total, 1.0, abs_tol=1e-9) or any(part.share <= 0.0 for part in parts):
            raise ValueError(f"a blend's shares are positive and sum to 1, got {[part.share for part in parts]}")
    else:
        survivors = list(raw.get("survivors") or [])
        if len(survivors) != 1 or raw.get("method") is not None:
            raise ValueError("the single-rule shape holds exactly one survivor and no combination method")
        parts = (BookPart("g0001", 1.0, "sleeve", {"survivor": survivors[0]}, int(raw.get("phase_index", 0))),)
    return BlendDefinition(parts, str(raw["history_start"]), raw.get("pinned_run"), {part.generation: part.share for part in parts}, raw.get("settings"))


def weight_settings(definition: BlendDefinition) -> tuple[WeightSettings, WeightSettings]:
    """(the book part's settings, the sleeve parts' settings): the definition's own block for the book, the defaults every sleeve was frozen with."""
    from portfolio.premia_signals import WeightSettings as Settings

    return (Settings(**definition.settings) if definition.settings else Settings()), Settings()


def spec_of(fields: Mapping[str, Any]) -> SleeveSpec:
    """A `SleeveSpec` from its stored fields."""
    from portfolio.premia_signals import SleeveSpec

    if "survivor" in fields:
        raise ValueError(f"{fields['survivor']!r} names a V6.5.0 rule by id; resolve it to a spec before building rows")
    return SleeveSpec(
        str(fields["id"]), str(fields.get("track", "BOOK")), str(fields.get("kind", "cross_sectional")), str(fields.get("family", "external_score")),
        tuple(fields["universe"]), int(fields["rebalance_every"] if "rebalance_every" in fields else fields["every"]), dict(fields.get("params") or {}),
    )


# --- spec -> weights -----------------------------------------------------------------------------------------------------------


def spec_weights(
    spec: SleeveSpec, panel: ResearchPanel, signal: pd.DataFrame, *, settings: WeightSettings, listed: Callable[[str, str], bool] | None,
    start: str, end: str, phase_offset: int,
) -> dict[str, dict[str, float]]:
    """The spec's weight rows over [start, end] from one phase offset: its optimizer, no-trade band or partial move, and the guards its
    params name (a class loss guard, a stress scaler). A spec naming none is sized as every earlier round was."""
    from portfolio.book_construction import partial_adjust_weights
    from portfolio.book_optimizer import ClassLossGuard, no_trade_band, optimizer_for, stress_scaler
    from portfolio.premia_signals import signal_to_weights, vix_ratio

    adjust = None
    if spec.params.get("band"):
        band = float(spec.params["band"])

        def adjust(previous, new):
            return no_trade_band(previous, new, band=band)
    elif spec.params.get("partial"):
        fraction = float(spec.params["partial"])

        def adjust(previous, new):
            return partial_adjust_weights(previous, new, fraction)
    guards = []
    if spec.params.get("guard_classes"):
        guards.append(ClassLossGuard(
            panel.known.pct_change(fill_method=None), panel.asset_class, spec.params["guard_classes"],
            lookback=int(spec.params.get("guard_lookback", 60)), max_loss=float(spec.params.get("guard_max_loss", 0.01)),
        ))
    if spec.params.get("vix_halve"):
        guards.append(stress_scaler(vix_ratio(panel), float(spec.params["vix_halve"])))

    def guard(date, row):
        for step in guards:
            row = step(date, row)
        return row

    return signal_to_weights(
        signal, panel, kind=spec.kind, rebalance_every=spec.rebalance_every, phase_offset=phase_offset, settings=settings, start=start, end=end,
        listed=listed, top_k=spec.params.get("top_k"), optimizer=optimizer_for(spec.params), adjust=adjust, guard=guard if guards else None,
    )


# --- signal tables -------------------------------------------------------------------------------------------------------------


def within_class_z(table: pd.DataFrame, asset_class: Mapping[str, str]) -> pd.DataFrame:
    """Each row's z-score inside its asset class; a class with under two names in a row, or no spread, has no view there."""
    import numpy as np
    import pandas as pd

    out = pd.DataFrame(np.nan, index=table.index, columns=table.columns)
    for name in sorted({asset_class.get(ticker) for ticker in table.columns}, key=str):
        members = [ticker for ticker in table.columns if asset_class.get(ticker) == name]
        block = table[members]
        spread = block.std(axis=1, ddof=0).replace(0.0, np.nan)
        z = block.sub(block.mean(axis=1), axis=0).div(spread, axis=0)
        out[members] = z.where(block.notna().sum(axis=1) >= 2, np.nan)
    return out


def composite_signal(parts: Sequence[tuple[float, pd.DataFrame]], asset_class: Mapping[str, str]) -> pd.DataFrame:
    """The weighted sum of the parts' within-class z-scores. A part with no view of a name is left out of that name's sum, which is
    divided by the weights of the parts that had one; a name no part sees is NaN."""
    total = None
    weight = None
    for share, table in parts:
        z = within_class_z(table, asset_class)
        value = z.fillna(0.0) * float(share)
        seen = z.notna() * float(share)
        total = value if total is None else total.add(value, fill_value=0.0)
        weight = seen if weight is None else weight.add(seen, fill_value=0.0)
    return total.div(weight.where(weight > 0.0))


def trend_vote(known: pd.DataFrame, windows: Sequence[int] = (63, 126, 252)) -> pd.DataFrame:
    """The mean sign of the return over each window, in [-1, 1]; NaN until the longest window exists."""
    import numpy as np

    votes = [np.sign(known / known.shift(window) - 1.0).where(known.shift(window).notna()) for window in windows]
    return sum(votes) / float(len(votes))


def momentum_12_1(known: pd.DataFrame) -> pd.DataFrame:
    """The return from 252 to 21 sessions ago (the month just ended is skipped)."""
    return known.shift(21) / known.shift(252) - 1.0


def low_volatility_score(known: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Minus the trailing volatility of daily returns: the calmest name scores highest."""
    return -known.pct_change(fill_method=None).rolling(window, min_periods=window).std()


def signal_tables(panel: ResearchPanel, scores: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """The signal tables a trial or the installed book names, from the aligned score tables `scores` (`ml_a1`, `ml_a2`, `ml_a3`) and the
    panel's known closes. All of them are as known at the session, so none needs a further shift."""
    import numpy as np
    import pandas as pd

    known, classes = panel.known, panel.asset_class
    columns = [ticker for ticker in known.columns if classes.get(ticker) in CLASSES]
    base = scores["ml_a1"].reindex(index=known.index, columns=columns)
    trend, momentum, calm = trend_vote(known[columns]), momentum_12_1(known[columns]), low_volatility_score(known[columns])
    carry = panel.extras.get("fx_carry")
    carry = carry.reindex(index=known.index, columns=columns) if carry is not None else pd.DataFrame(np.nan, index=known.index, columns=columns)
    tables = {
        "ml_a1": base,
        "const": pd.DataFrame(1.0, index=known.index, columns=columns),
        "mix_trend": composite_signal([(0.5, base), (0.5, trend)], classes),
        "mix_mom": composite_signal([(0.5, base), (0.5, momentum)], classes),
        "mix_lowvol": composite_signal([(0.5, base), (0.5, calm)], classes),
        "mix_all4": composite_signal([(1.0, base), (1.0, momentum), (1.0, calm), (1.0, carry)], classes),
    }
    if "ml_a2" in scores and "ml_a3" in scores:
        tables["mix_a23"] = composite_signal(
            [(0.5, scores["ml_a2"].reindex(index=known.index, columns=columns)), (0.5, scores["ml_a3"].reindex(index=known.index, columns=columns))], classes,
        )
    return tables


# --- rows ----------------------------------------------------------------------------------------------------------------------


def forward_fill_rows(rows: Mapping[str, Mapping[str, float]], dates: Sequence[str]) -> dict[str, dict[str, float]]:
    """Each date's row from the latest decision at or before it; a date before the first decision has no row."""
    ordered = sorted(rows)
    out: dict[str, dict[str, float]] = {}
    position = -1
    for date in dates:
        while position + 1 < len(ordered) and ordered[position + 1] <= date:
            position += 1
        if position >= 0:
            out[date] = dict(rows[ordered[position]])
    return out


def blend_rows(parts: Mapping[str, Mapping[str, Mapping[str, float]]], shares: Mapping[str, float]) -> dict[str, dict[str, float]]:
    """On every decision date of any part, each part's latest row times its share (a part with no row yet is flat). Every part is carried
    forward first, so a part that decides rarely is still held between its decisions."""
    dates = sorted({date for rows in parts.values() for date in rows})
    carried = {name: forward_fill_rows(rows, dates) for name, rows in parts.items()}
    return {date: blend_generation_rows({name: carried[name].get(date, {}) for name in parts}, shares) for date in dates}


def definition_rows(
    definition: BlendDefinition, panel: ResearchPanel, tables: Mapping[str, pd.DataFrame], *, settings: WeightSettings, sleeve_settings: WeightSettings,
    listed: Callable[[str, str], bool] | None, start: str, end: str, sleeve_signal: Callable[[SleeveSpec, ResearchPanel], pd.DataFrame],
) -> dict[str, dict[str, dict[str, float]]]:
    """{generation: {date: row}} over [start, end]. A "book" part reads its table from `tables` and is sized by `settings`; a "sleeve" part builds
    its own signal from the panel (`sleeve_signal`) and is sized by `sleeve_settings` (the settings it was frozen with)."""
    from portfolio.premia_signals import ResearchPanel as Panel

    out: dict[str, dict[str, dict[str, float]]] = {}
    extended = Panel(panel.known, panel.asset_class, panel.fred, {**panel.extras, **tables})
    for part in definition.parts:
        spec = spec_of(part.spec)
        offsets = phase_offsets(spec.rebalance_every)
        out[part.generation] = spec_weights(
            spec, extended, sleeve_signal(spec, extended), settings=settings if part.kind == "book" else sleeve_settings, listed=listed,
            start=start, end=end, phase_offset=offsets[part.phase_index % len(offsets)],
        )
    return out


def row_for_session(
    definition: BlendDefinition, panel: ResearchPanel, tables: Mapping[str, pd.DataFrame], session: str, *, settings: WeightSettings,
    sleeve_settings: WeightSettings, listed: Callable[[str, str], bool] | None, sleeve_signal: Callable[[SleeveSpec, ResearchPanel], pd.DataFrame],
) -> dict[str, float] | None:
    """The blended row decided at `session`, or None when no part decides then (the book holds what it has). Rebalances are counted from
    `definition.history_start`, so the row is the one the same definition gives over a longer window."""
    if not decides_at(definition, panel.known.index, session):
        return None
    rows = definition_rows(
        definition, panel, tables, settings=settings, sleeve_settings=sleeve_settings, listed=listed, start=definition.history_start, end=session,
        sleeve_signal=sleeve_signal,
    )
    return blend_rows(rows, definition.shares).get(session)


def decides_at(definition: BlendDefinition, sessions: Iterable[str], session: str) -> bool:
    """Whether any part rebalances at `session`, counting sessions from `definition.history_start` the way `signal_to_weights` does. A cheap test
    that lets the in-Lean book skip building rows on the days between decisions."""
    count = sum(1 for date in sessions if definition.history_start <= str(date) <= session) - 1
    for part in definition.parts:
        every = int(part.spec["rebalance_every"] if "rebalance_every" in part.spec else part.spec["every"])
        offsets = phase_offsets(every)
        offset = offsets[part.phase_index % len(offsets)]
        if count >= offset and (count - offset) % every == 0:
            return True
    return False


def holding_for_session(
    definition: BlendDefinition, panel: ResearchPanel, tables: Mapping[str, pd.DataFrame], session: str, *, settings: WeightSettings,
    sleeve_settings: WeightSettings, listed: Callable[[str, str], bool] | None, sleeve_signal: Callable[[SleeveSpec, ResearchPanel], pd.DataFrame],
) -> dict[str, float] | None:
    """The row the book holds after `session`: its latest decision at or before it (None before the first). A daily decision tool writes this,
    because a decision is the whole target, not a change to it."""
    rows = definition_rows(
        definition, panel, tables, settings=settings, sleeve_settings=sleeve_settings, listed=listed, start=definition.history_start, end=session,
        sleeve_signal=sleeve_signal,
    )
    return forward_fill_rows(blend_rows(rows, definition.shares), [session]).get(session)


# --- the in-Lean side ------------------------------------------------------------------------------------------------------------


def session_scores(heads: Mapping[str, Mapping[str, float]], table: str = "ml_a1") -> dict[str, float]:
    """One session's score per ticker as the walk-forward table defines it (`ml_a1`): the mean of the session's percentile ranks of the
    sequence model's `rank_20d` and `rank_5d`, ranked among the tickers that have both. A ticker with a missing or non-finite head has no score."""
    if table not in HEAD_TABLES:
        raise ValueError(f"no in-Lean definition of the score table {table!r}; expected one of {HEAD_TABLES}")
    usable = {ticker: [float(values[head]) for head in RANK_HEADS] for ticker, values in heads.items()
              if all(head in values and math.isfinite(float(values[head])) for head in RANK_HEADS)}
    if not usable:
        return {}
    ranks = [_percentile_ranks({ticker: pair[index] for ticker, pair in usable.items()}) for index in range(len(RANK_HEADS))]
    return {ticker: sum(rank[ticker] for rank in ranks) / len(ranks) for ticker in usable}


def _percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """pandas' `rank(pct=True)` (average rank of ties over the count)."""
    ordered = sorted(values.values())
    count = len(ordered)
    out = {}
    for ticker, value in values.items():
        below = sum(1 for other in ordered if other < value)
        equal = sum(1 for other in ordered if other == value)
        out[ticker] = (below + (equal + 1) / 2.0) / count
    return out


def permit_model_book_row(pins_ok: bool, row_finite: bool, model_age_ok: bool) -> bool:
    """Whether the in-Lean model book may send a row to the order path: the model files are the pinned ones, every weight is finite, and the
    models are inside their age limit. False holds the current book (the safe failure: nothing new, nothing closed)."""
    return bool(pins_ok) and bool(row_finite) and bool(model_age_ok)


def row_is_finite(row: Mapping[str, float]) -> bool:
    """Every weight of a row is a finite number (an empty row is finite: the book is flat)."""
    return all(isinstance(weight, (int, float)) and not isinstance(weight, bool) and math.isfinite(weight) for weight in row.values())


def lean_panel(dates: Sequence[str], closes: Mapping[str, Iterable[float]], asset_class: Mapping[str, str]) -> ResearchPanel:
    """A research panel from the closes the algorithm kept at each equity-session tick. Each tick's last known close is already the one a
    backtest's `known_closes` would hold there (a crypto or forex bar is the one dated before the session), so nothing is shifted again."""
    import pandas as pd

    from portfolio.premia_signals import ResearchPanel as Panel

    frame = pd.DataFrame({ticker: list(values) for ticker, values in closes.items()}, index=list(dates), dtype=float).ffill()
    return Panel(frame, dict(asset_class), {}, {})


def lean_session_row(
    definition: BlendDefinition, *, dates: Sequence[str], closes: Mapping[str, Iterable[float]], asset_class: Mapping[str, str],
    score_history: Mapping[str, Mapping[str, float]], settings: WeightSettings, sleeve_settings: WeightSettings,
    sleeve_signal: Callable[[SleeveSpec, ResearchPanel], pd.DataFrame], listed: Callable[[str, str], bool] | None = None,
) -> dict[str, float] | None:
    """The row the in-Lean model book decides at the last of `dates`: the same `row_for_session` the research engine calls, over a panel of
    the closes kept so far and a score table of the scores computed so far (`score_history`: session -> ticker -> score)."""
    import pandas as pd

    panel = lean_panel(dates, closes, asset_class)
    table = pd.DataFrame.from_dict(dict(score_history), orient="index").reindex(index=panel.known.index, columns=panel.known.columns)
    tables = signal_tables(panel, {"ml_a1": table})
    return row_for_session(
        definition, panel, tables, panel.known.index[-1], settings=settings, sleeve_settings=sleeve_settings, listed=listed, sleeve_signal=sleeve_signal,
    )
