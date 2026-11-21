"""lab/report_html.py: self-contained pages (no scripts, no external files) with lines, bars, heatmaps, histograms and tables."""

from __future__ import annotations

import numpy as np
import pandas as pd

from lab import report_html as rh


def test_numbers_format_and_non_finite_values_show_a_dash():
    assert rh.fmt(None) == "-" and rh.fmt(float("nan")) == "-" and rh.fmt(np.float64(0.123456), 2) == "0.12"
    assert rh.fmt(np.int64(3)) == "3" and rh.fmt(True) == "True" and rh.fmt("x") == "x"


def test_every_chart_is_inline_svg_and_empty_inputs_draw_nothing():
    lines = rh.svg_lines([pd.Series([1.0, 1.1, np.nan, 1.3]), pd.Series([1.0, 0.9])], label="Equity <&>")
    assert lines.startswith("<svg") and lines.count("<polyline") == 2 and "Equity &lt;&amp;&gt;" in lines
    assert rh.svg_lines([]).count("<polyline") == 0
    bars = rh.svg_bars({"a": 0.2, "b": -0.1, "c": None, "d": float("nan")})
    assert bars.count("<rect") == 2 and rh.svg_bars({}) == ""
    heat = rh.svg_heatmap(pd.DataFrame([[1.0, -0.5], [-0.5, np.nan]], index=["x", "y"], columns=["x", "y"]))
    assert heat.count("<rect") == 4 and "rgba(37,99,235,0.50)" in heat and "<title>" in heat
    assert rh.svg_histogram([1.0, 2.0, 2.5, np.inf], bins=3).count("<rect") == 3 and rh.svg_histogram([np.nan]) == ""


def test_a_page_holds_its_sections_and_escapes_text():
    page = rh.page("Run <1>", [("Stats", rh.table([["a", 1.23456]], ["name", "value"])), ("", rh.legend(["one", "two"]))], subtitle="sub", footer="N = 3")
    assert page.startswith("<!doctype html>") and "<script" not in page and "http" not in page.replace("http-equiv", "")
    assert "Run &lt;1&gt;" in page and "<th>name</th>" in page and "1.235" in page and "<strong>N = 3</strong>" in page
    assert rh.table([["x"]]).startswith("<table><tbody>")
