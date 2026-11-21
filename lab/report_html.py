"""Self-contained HTML pages for the lab's reports: one file, no scripts, no external assets, light and dark.

`evaluation/hello_world.py`'s page is built from these too. Pure; numbers go in, a string comes out.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

PALETTE = ("#d97706", "#2563eb", "#059669", "#7c3aed", "#dc2626", "#64748b", "#0891b2", "#ca8a04")

STYLE = """:root{color-scheme:light dark;--fg:#111827;--bg:#ffffff;--muted:#6b7280;--line:#e5e7eb}
@media (prefers-color-scheme: dark){:root{--fg:#f3f4f6;--bg:#111827;--muted:#9ca3af;--line:#374151}}
body{font:15px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);max-width:900px;margin:2rem auto;padding:0 16px}
table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border-bottom:1px solid var(--line);padding:.35rem .5rem;text-align:right}
td:first-child,th:first-child{text-align:left}.muted{color:var(--muted)}svg{max-width:100%;height:auto}"""


def fmt(value: object, digits: int = 3) -> str:
    """A number to `digits` places, '-' for None or a non-finite float, anything else as text."""
    if value is None:
        return "-"
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}" if math.isfinite(float(value)) else "-"
    return str(value)


def svg_lines(series: Sequence[pd.Series], colors: Sequence[str] = PALETTE, width: int = 720, height: int = 260, label: str = "Equity curves") -> str:
    """One polyline per series on a shared vertical scale."""
    values = np.concatenate([np.asarray(curve, dtype=float) for curve in series]) if series else np.array([])
    values = values[np.isfinite(values)]
    low, high = (float(values.min()), float(values.max())) if values.size else (0.0, 1.0)
    span = high - low or 1.0
    paths = []
    for curve, color in zip(series, colors, strict=False):
        data = np.asarray(curve, dtype=float)
        steps = max(len(data) - 1, 1)
        points = " ".join(f"{i / steps * width:.1f},{height - (value - low) / span * height:.1f}" for i, value in enumerate(data) if math.isfinite(value))
        paths.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{points}"/>')
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{html.escape(label)}">{"".join(paths)}</svg>'


def svg_bars(values: Mapping[str, float], width: int = 720, bar: int = 18, label: str = "Bars") -> str:
    """Horizontal bars, one per key, signed around a zero line."""
    items = [(name, float(value)) for name, value in values.items() if value is not None and math.isfinite(float(value))]
    if not items:
        return ""
    scale = max(abs(value) for _, value in items) or 1.0
    zero, half, rows = width * 0.45, width * 0.25, []
    for index, (name, value) in enumerate(items):
        y = index * (bar + 6)
        length = abs(value) / scale * half
        x = zero if value >= 0 else zero - length
        color = PALETTE[2] if value >= 0 else PALETTE[4]
        rows.append(f'<text x="0" y="{y + bar - 4}" font-size="12" fill="currentColor">{html.escape(name)}</text>'
                    f'<rect x="{x:.1f}" y="{y}" width="{length:.1f}" height="{bar}" fill="{color}"/>'
                    f'<text x="{zero + half + 8:.1f}" y="{y + bar - 4}" font-size="12" fill="currentColor">{fmt(value)}</text>')
    total = len(items) * (bar + 6)
    return f'<svg viewBox="0 0 {width} {total}" width="100%" role="img" aria-label="{html.escape(label)}"><line x1="{zero}" y1="0" x2="{zero}" y2="{total}" stroke="currentColor" stroke-opacity=".3"/>{"".join(rows)}</svg>'


def svg_heatmap(matrix: pd.DataFrame, cell: int = 26, label: str = "Correlation") -> str:
    """A square matrix in [-1, 1] as coloured cells (blue negative, orange positive) with row and column names."""
    names = [str(name) for name in matrix.columns]
    pad = 8 + 7 * max((len(name) for name in names), default=1)
    size = pad + cell * len(names)
    cells = []
    for row, row_name in enumerate(matrix.index):
        cells.append(f'<text x="{pad - 4}" y="{pad + row * cell + cell * 0.65:.1f}" font-size="11" text-anchor="end" fill="currentColor">{html.escape(str(row_name))}</text>')
        for column, _ in enumerate(matrix.columns):
            value = float(matrix.iat[row, column])
            alpha = min(abs(value), 1.0) if math.isfinite(value) else 0.0
            color = "217,119,6" if value >= 0 else "37,99,235"
            tip = f"{html.escape(str(row_name))} / {html.escape(names[column])}: {fmt(value, 2)}"
            cells.append(f'<rect x="{pad + column * cell}" y="{pad + row * cell}" width="{cell - 1}" height="{cell - 1}" fill="rgba({color},{alpha:.2f})"><title>{tip}</title></rect>')
    for column, name in enumerate(names):
        cells.append(f'<text x="{pad + column * cell + cell / 2:.1f}" y="{pad - 4}" font-size="11" text-anchor="start" transform="rotate(-60 {pad + column * cell + cell / 2:.1f} {pad - 4})" fill="currentColor">{html.escape(name)}</text>')
    return f'<svg viewBox="0 0 {size} {size}" width="100%" role="img" aria-label="{html.escape(label)}">{"".join(cells)}</svg>'


def svg_histogram(values: Sequence[float], bins: int = 30, width: int = 720, height: int = 160, label: str = "Distribution") -> str:
    """An inline SVG histogram of `values`."""
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if data.size == 0:
        return ""
    counts, _ = np.histogram(data, bins=bins)
    top = counts.max() or 1
    step = width / bins
    rects = "".join(
        f'<rect x="{i * step:.1f}" y="{height - count / top * height:.1f}" width="{step - 1:.1f}" height="{count / top * height:.1f}" fill="{PALETTE[1]}"/>'
        for i, count in enumerate(counts)
    )
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{html.escape(label)}">{rects}</svg>'


def table(rows: Sequence[Sequence[object]], header: Sequence[str] | None = None) -> str:
    """An HTML table from rows and a header."""
    head = "<thead><tr>" + "".join(f"<th>{html.escape(str(cell))}</th>" for cell in header) + "</tr></thead>" if header else ""
    body = "".join("<tr>" + "".join(f"<td>{html.escape(fmt(cell))}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table>{head}<tbody>{body}</tbody></table>"


def legend(names: Sequence[str], colors: Sequence[str] = PALETTE) -> str:
    """An HTML legend for a chart's series, each name in its colour."""
    return '<p class="muted">' + " &nbsp; ".join(f'<span style="color:{color}">&#9632;</span> {html.escape(name)}' for name, color in zip(names, colors, strict=False)) + "</p>"


def page(title: str, sections: Sequence[tuple[str, str]], subtitle: str = "", footer: str = "") -> str:
    """A whole page: a title, an optional muted subtitle, (heading, html) sections and an optional footer line."""
    parts = [f"<h1>{html.escape(title)}</h1>"]
    if subtitle:
        parts.append(f'<p class="muted">{html.escape(subtitle)}</p>')
    for heading, body in sections:
        parts.append((f"<h2>{html.escape(heading)}</h2>" if heading else "") + body)
    if footer:
        parts.append(f"<p><strong>{html.escape(footer)}</strong></p>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title)}</title><style>\n{STYLE}</style></head><body>\n" + "\n".join(parts) + "</body></html>\n")
