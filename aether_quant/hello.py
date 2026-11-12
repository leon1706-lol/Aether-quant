"""The hello world as a library call (V6.6.5): what `aq hello` does, for a notebook or a script.

    from aether_quant import hello
    report = hello.run(offline=True)        # the bundled sample; offline=False downloads from Coinbase's public candles
    print(hello.render_text(report))
    report.equity.plot()                    # the shipped rule's equity curve (needs matplotlib)
"""

from __future__ import annotations

from pathlib import Path

from data_pipeline.public_candles import DEFAULT_CACHE_DIR
from evaluation.hello_world import HELLO_RULE, RESEARCH_TRIALS, HelloReport, StatsRow, known_at_sessions, load_closes, render_html, render_text, rule_weights, run_hello

__all__ = ["HELLO_RULE", "RESEARCH_TRIALS", "HelloReport", "StatsRow", "known_at_sessions", "load_closes", "render_html", "render_text", "rule_weights", "run", "run_hello", "save"]


def run(offline: bool = False, *, start: str = "2022-01-01", end: str | None = None, cache: bool = True) -> HelloReport:
    """Load the data (download unless `offline`, falling back to the sample) and run the whole demo."""
    closes, source, notice = load_closes(offline=offline, start=start, end=end, cache_dir=DEFAULT_CACHE_DIR if cache else None)
    if notice:
        print(notice)
    return run_hello(closes, start=start, end=end, data_source=source)


def save(report: HelloReport, *, html_path: str | Path | None = None, json_path: str | Path | None = None) -> None:
    """Write the HTML page and/or the JSON report."""
    from json_safety import atomic_write_json, atomic_write_text

    if html_path:
        atomic_write_text(Path(html_path), render_html(report))
    if json_path:
        atomic_write_json(Path(json_path), report.to_dict(), indent=2)

