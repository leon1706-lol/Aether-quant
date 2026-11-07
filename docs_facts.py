"""Numbers the docs quote, kept true by reading them from their source.

A doc writes `<!--fact:universe.total-->104<!--/fact-->`, which renders as plain "104". `aq docs sync` rewrites each value
from `compute_facts`, `aq docs sync --check` reports drift (`tests/test_docs_facts.py` runs it, so CI fails on a stale number),
and a full `aq test` syncs too. Facts read tracked files only, so a clean checkout computes the same values."""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FACT_RE = re.compile(r"<!--fact:([a-z0-9_.]+)-->(.*?)<!--/fact-->")
EXCLUDED_PREFIXES = ("Aether-quant-Obsidian-Vault/", "development/backups/", "backtests/", "webui/node_modules/")
_PROBLEM_HEADING_RE = re.compile(r"^### ([0-9]+[a-z]?)\. ", re.MULTILINE)
_STATUS_MARKERS = {"fixed": "🟢", "partial": "🟡", "closed": "🔴"}


def universe_facts(config: dict) -> dict[str, str]:
    assets = config["phase1"]["universe"]["assets"]
    counts = Counter(str(asset.get("asset_class") or asset.get("security_type")) for asset in assets)
    facts = {"universe.total": str(len(assets))}
    facts.update({f"universe.{kind}": str(count) for kind, count in counts.items()})
    for kind in counts:
        tickers = (str(asset["ticker"]) for asset in assets if str(asset.get("asset_class") or asset.get("security_type")) == kind)
        facts[f"universe.list.{kind}"] = ", ".join(sorted(tickers))
    return facts


def window_facts(config: dict) -> dict[str, str]:
    windows = config["phase1"]["windows"]
    return {f"windows.{name}": f"{window['start']} to {window['end']}" for name, window in windows.items() if isinstance(window, dict) and "start" in window}


def _status_line(entry: str) -> str:
    return next((line.strip() for line in entry.splitlines()[1:] if line.strip()), "")


def problem_facts(text: str) -> dict[str, str]:
    """Entry count, highest number and how many entries carry each status marker."""
    numbers = _PROBLEM_HEADING_RE.findall(text)
    highest = max((int(re.match(r"\d+", number).group()) for number in numbers), default=0)
    facts = {"problems.total": str(len(numbers)), "problems.last": str(highest)}
    entries = re.split(r"^### ", text, flags=re.MULTILINE)[1:]
    for name, marker in _STATUS_MARKERS.items():
        facts[f"problems.{name}"] = str(sum(1 for entry in entries if _status_line(entry).startswith(marker)))
    return facts


def changelog_facts(text: str) -> dict[str, str]:
    phases = re.findall(r"^## Phase (\S+)", text, flags=re.MULTILINE)
    return {"changelog.latest": phases[-1]} if phases else {}


def python_facts(pyproject: str, ci_workflow: str) -> dict[str, str]:
    facts = {}
    requires = re.search(r'^requires-python\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if requires:
        facts["python.requires"] = requires.group(1)
    versions = re.findall(r'python-version:\s*"?([0-9.]+)"?', ci_workflow)
    if versions:
        facts["python.ci"] = Counter(versions).most_common(1)[0][0]
    return facts


def _option_structures() -> dict[str, str]:
    from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY

    return {"options.structures": str(len(MULTI_LEG_STRATEGY_REGISTRY))}


def _aq_commands() -> dict[str, str]:
    from aq_cli import build_parser

    parser = build_parser()
    commands = next(action.choices for action in parser._actions if isinstance(getattr(action, "choices", None), dict))
    return {"aq.commands": str(len(commands))}


def compute_facts(root: Path = ROOT) -> dict[str, str]:
    root = Path(root)
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    facts = {**universe_facts(config), **window_facts(config)}
    facts.update(problem_facts((root / "development" / "Problems.md").read_text(encoding="utf-8")))
    facts.update(changelog_facts((root / "development" / "Changelog.md").read_text(encoding="utf-8")))
    facts.update(python_facts((root / "pyproject.toml").read_text(encoding="utf-8"), (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")))
    api = json.loads((root / "tests" / "data" / "aether_quant_api.json").read_text(encoding="utf-8"))
    facts["library.modules"] = str(len(api))
    facts["library.names"] = str(sum(len(names) for names in api.values()))
    engine = re.search(r"^ARG LEAN_BASE_IMAGE=(\S+)", (root / "Dockerfile.lean").read_text(encoding="utf-8"), re.MULTILINE)
    if engine:
        facts["lean.engine"] = engine.group(1)
    jobs = re.search(r"^jobs:\n(.*)", (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL)
    if jobs:
        facts["ci.jobs"] = str(len(re.findall(r"^  [a-z0-9-]+:$", jobs.group(1), re.MULTILINE)))
    facts["formal.specs"] = str(sum(1 for _ in (root / "formal" / "AetherFormal").glob("*.lean")))
    facts.update(_option_structures())
    facts.update(_aq_commands())
    return facts


def apply_facts(text: str, facts: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """(new text, keys with no known value, keys whose value changed)."""
    unknown: list[str] = []
    changed: list[str] = []

    def replace(match: re.Match) -> str:
        key, value = match.group(1), match.group(2)
        if key not in facts:
            unknown.append(key)
            return match.group(0)
        if facts[key] != value:
            changed.append(key)
        return f"<!--fact:{key}-->{facts[key]}<!--/fact-->"

    return FACT_RE.sub(replace, text), unknown, changed


def tracked_docs(root: Path = ROOT) -> list[Path]:
    output = subprocess.run(["git", "ls-files", "*.md"], cwd=root, capture_output=True, text=True, check=True, timeout=30).stdout
    paths = [Path(root) / line for line in output.splitlines() if line and not line.startswith(EXCLUDED_PREFIXES)]
    return [path for path in paths if path.exists()]


def sync_docs(paths: Iterable[Path], facts: dict[str, str], *, check: bool = False) -> dict[str, list[str]]:
    """{"changed": ["file: key"], "unknown": ["file: key"]}. Writes only the files whose text moved, and nothing with `check`."""
    report: dict[str, list[str]] = {"changed": [], "unknown": []}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        updated, unknown, changed = apply_facts(text, facts)
        report["changed"] += [f"{path.name}: {key}" for key in changed]
        report["unknown"] += [f"{path.name}: {key}" for key in unknown]
        if updated != text and not check:
            path.write_text(updated, encoding="utf-8", newline="\n")
    return report
