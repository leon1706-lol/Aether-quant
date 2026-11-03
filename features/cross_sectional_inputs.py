"""Cross-sectionally ranked model inputs (V6.4.4, Problems.md #247).

A scaled feature's level across assets is mostly asset identity (the installed model ranked worse than an asset-class
prior); its percentile rank among the assets of the same class on the same bar is the comparable part. With
`phase1.features.cross_sectional_inputs.enabled`, every `*_scaled` model input is replaced by ("replace") or joined by
("append", as `<name>_csr`) its rank within (bar, asset class), centred to [-0.5, 0.5].

Groups are asset classes because each class's bars reach live on their own tick (equities and bonds at the close, crypto
at midnight UTC, forex on its own calendar): a rank across classes could not be reproduced live.

One definition, two forms with identical values: `rank_input_matrix` (lists, `main.py` on the tick's pending symbols) and
`rank_input_frame` (pandas, the trainer and the offline scorer per dataset date). A value that is not finite, or a group
with fewer than `min_group_size` finite values, becomes 0.0 (the centre) - never NaN into a model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

CSR_SUFFIX = "_csr"
RANKED_SUFFIX = "_scaled"
MODES = ("replace", "append")
GROUPS = ("asset_class",)


def resolve_cross_sectional_inputs(raw: Mapping | None) -> dict | None:
    """`phase1.features.cross_sectional_inputs` -> settings, or None when absent / disabled (today's behaviour)."""
    if not isinstance(raw, Mapping) or not bool(raw.get("enabled", False)):
        return None
    group = str(raw.get("group", "asset_class"))
    mode = str(raw.get("mode", "replace"))
    try:
        min_group_size = int(raw.get("min_group_size", 5))
    except (TypeError, ValueError):
        min_group_size = 5
    return {
        "group": group if group in GROUPS else "asset_class",
        "mode": mode if mode in MODES else "replace",
        "min_group_size": max(2, min_group_size),
    }


def settings_from_config(config: Mapping | None) -> dict | None:
    return resolve_cross_sectional_inputs(((config or {}).get("phase1") or {}).get("features", {}).get("cross_sectional_inputs"))


def ranked_input_names(names: Sequence[str]) -> list[str]:
    """The inputs that get ranked: the scaled features (categorical / class context inputs stay as they are)."""
    return [str(name) for name in names if str(name).endswith(RANKED_SUFFIX)]


def expand_input_names(names: Sequence[str], settings: Mapping | None) -> list[str]:
    """Model input names after the transform: unchanged for "replace", `<name>_csr` appended for "append"."""
    names = [str(name) for name in names]
    if not settings or settings.get("mode") != "append":
        return names
    extra = [name + CSR_SUFFIX for name in ranked_input_names(names) if name + CSR_SUFFIX not in names]
    return names + extra


def asset_class_of(asset: Mapping | None) -> str:
    """The class main.py's _class_raw_scores uses: asset_class, else security_type (bond ETFs are equity / bond)."""
    asset = asset or {}
    return str(asset.get("asset_class") or asset.get("security_type") or "unknown")


def asset_class_by_ticker(config: Mapping | None) -> dict[str, str]:
    assets = (((config or {}).get("phase1") or {}).get("universe") or {}).get("assets") or []
    return {str(asset.get("ticker")): asset_class_of(asset) for asset in assets}


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _centred_ranks(values: Sequence[float | None], min_group_size: int) -> list[float]:
    """Average-rank percentile minus 0.5 over the finite values (pandas rank(pct=True) - 0.5); 0.0 elsewhere."""
    finite = [(value, index) for index, value in enumerate(values) if value is not None]
    out = [0.0] * len(values)
    count = len(finite)
    if count < min_group_size:
        return out
    finite.sort(key=lambda pair: pair[0])
    position = 0
    while position < count:
        end = position
        while end + 1 < count and finite[end + 1][0] == finite[position][0]:
            end += 1
        average_rank = (position + 1 + end + 1) / 2.0
        for _, index in finite[position:end + 1]:
            out[index] = average_rank / count - 0.5
        position = end + 1
    return out


def rank_input_matrix(
    rows: Sequence[Sequence[float]], names: Sequence[str], groups: Sequence[str], settings: Mapping
) -> tuple[list[list[float]], list[str]]:
    """Live form: `rows` are the model input vectors (in `names` order) of the symbols of ONE bar, `groups` their asset
    classes. Returns (new rows, new names) - new lists, the inputs are never mutated."""
    names = [str(name) for name in names]
    out_names = expand_input_names(names, settings)
    out_rows = [list(row) + [0.0] * (len(out_names) - len(names)) for row in rows]
    min_group_size = int(settings.get("min_group_size", 5))
    append = settings.get("mode") == "append"
    members: dict[str, list[int]] = {}
    for index, group in enumerate(groups):
        members.setdefault(str(group), []).append(index)
    for name in ranked_input_names(names):
        source = names.index(name)
        target = out_names.index(name + CSR_SUFFIX) if append else source
        for indexes in members.values():
            ranks = _centred_ranks([_finite(rows[i][source]) for i in indexes], min_group_size)
            for i, rank in zip(indexes, ranks):
                out_rows[i][target] = rank
    return out_rows, out_names


def rank_input_frame(frame, names: Sequence[str], groups, settings: Mapping, *, date_column: str = "date"):
    """Offline form, same values as rank_input_matrix per (date, group): returns a copy of `frame` with the scaled
    inputs replaced (or `<name>_csr` columns added). `groups` is aligned to `frame` (a Series or a sequence)."""
    import numpy as np
    import pandas as pd

    names = [str(name) for name in names]
    ranked = [name for name in ranked_input_names(names) if name in frame.columns]
    out = frame.copy()
    if out.empty or not ranked:
        return out
    min_group_size = int(settings.get("min_group_size", 5))
    keys = [out[date_column].astype(str).str[:10].to_numpy(), np.asarray(list(groups), dtype=object)]
    values = out[ranked].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    grouped = values.groupby(keys, sort=False)
    ranks = grouped.rank(pct=True, method="average") - 0.5
    counts = grouped.transform("count")
    ranks = ranks.where(counts >= min_group_size).fillna(0.0)
    append = settings.get("mode") == "append"
    for name in ranked:
        out[name + CSR_SUFFIX if append else name] = ranks[name].to_numpy(dtype=float)
    return out


def apply_cross_sectional_inputs(frame, config: Mapping | None, names: Sequence[str], *, ticker_column: str = "ticker",
                                 date_column: str = "date"):
    """The trainer's / offline scorer's one call: `frame` unchanged when the setting is off, else ranked per (date, class)
    with each row's class from the config universe (the same mapping main.py uses)."""
    settings = settings_from_config(config)
    if settings is None:
        return frame
    classes = asset_class_by_ticker(config)
    groups = [classes.get(str(ticker), "unknown") for ticker in frame[ticker_column].tolist()]
    return rank_input_frame(frame, names, groups, settings, date_column=date_column)
