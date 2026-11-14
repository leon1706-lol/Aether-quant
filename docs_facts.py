"""Numbers the docs quote, kept true by reading them from their source.

A doc writes `<!--fact:universe.total-->104<!--/fact-->`, which renders as plain "104". `aq docs sync` rewrites each value
from `compute_facts`, `aq docs sync --check` reports drift (`tests/test_docs_facts.py` runs it, so CI fails on a stale number),
and a full `aq test` syncs too. Facts read tracked files only, so a clean checkout computes the same values.

A generated block is the multi-line twin: `<!-- AQ:NAME_START -->...<!-- AQ:NAME_END -->` is rewritten whole from `compute_blocks`
(`DOCS_SITE`, the README's map of the documentation site, read from `mkdocs.yml`'s nav; `CHANGELOG_LATEST`, the site's list
of the latest phases, read from `development/Changelog.md`)."""

from __future__ import annotations

import gzip
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
_NAV_SECTION_RE = re.compile(r"^  - ([^:]+):\s*(\S+)?\s*$")
_NAV_PAGE_RE = re.compile(r"^      - ([^:]+):\s*(\S+)\s*$")
SITE_URL = "https://leon1706-lol.github.io/Aether-quant/"


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


def research_facts(problems: str) -> dict[str, str]:
    """The deflated-Sharpe N: the last "The deflated-Sharpe N is now X." in Problems.md (`RESEARCH_TRIALS` is pinned to it)."""
    counts = re.findall(r"The deflated-Sharpe N is now (\d+)\.", problems)
    return {"research.trials": counts[-1]} if counts else {}


def sample_facts(path: Path) -> dict[str, str]:
    """The bundled sample's window, from its own rows (`date` first, ISO dates)."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        dates = [line.split(",", 1)[0] for line in handle.read().splitlines()[1:] if line]
    if not dates:
        return {}
    first, last = min(dates), max(dates)
    return {"sample.first": first, "sample.last": last, "sample.months": f"{first[:7]} to {last[:7]}"}


def hello_facts(path: Path) -> dict[str, str]:
    """`aq hello --offline`'s headline figures, from the summary tests/test_hello_world.py checks against a real run."""
    if not path.exists():
        return {}
    return {f"hello.{key}": str(value) for key, value in json.loads(path.read_text(encoding="utf-8")).items()}


def lean_pin_facts(readme: str) -> dict[str, str]:
    """The pinned Lean run, from the line the README's generated Backtest Statistics write ("_Lean run `<id>`, ...")."""
    run = re.search(r"^_Lean run `([0-9_-]+)`", readme, re.MULTILINE)
    return {"lean.pin_run": run.group(1)} if run else {}


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
    problems = (root / "development" / "Problems.md").read_text(encoding="utf-8")
    facts.update(problem_facts(problems))
    facts.update(research_facts(problems))
    facts.update(sample_facts(root / "aether_quant" / "_sample" / "coinbase_daily.csv.gz"))
    facts.update(hello_facts(root / "tests" / "data" / "hello_offline_summary.json"))
    facts.update(lean_pin_facts((root / "README.md").read_text(encoding="utf-8")))
    facts.update(changelog_facts((root / "development" / "Changelog.md").read_text(encoding="utf-8")))
    facts.update(python_facts((root / "pyproject.toml").read_text(encoding="utf-8"), (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")))
    api = json.loads((root / "tests" / "data" / "aether_quant_api.json").read_text(encoding="utf-8"))
    facts["library.modules"] = str(len(api))
    facts["library.names"] = str(sum(len(names) for names in api.values()))
    engine = re.search(r"^ARG LEAN_BASE_IMAGE=(\S+)", (root / "Dockerfile.lean").read_text(encoding="utf-8"), re.MULTILINE)
    if engine:
        facts["lean.engine"] = engine.group(1).split("@", 1)[0]  # the tag; the digest pin is Dockerfile.lean's
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


def docs_site_nav(root: Path = ROOT) -> list[tuple[str, list[tuple[str, str]]]]:
    """`mkdocs.yml`'s nav as [(section, [(title, docs-relative path)])], read line by line (no YAML dependency)."""
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    in_nav = False
    for line in (Path(root) / "mkdocs.yml").read_text(encoding="utf-8").splitlines():
        if line.startswith("nav:"):
            in_nav = True
            continue
        if in_nav and line and not line.startswith(" "):
            break
        if not in_nav or line.strip().startswith("#"):
            continue
        section, page = _NAV_SECTION_RE.match(line), _NAV_PAGE_RE.match(line)
        if section:
            sections.append((section.group(1).strip(), [("", section.group(2))] if section.group(2) else []))
        elif page and sections:
            sections[-1][1].append((page.group(1).strip(), page.group(2)))
    return sections


def _site_link(title: str, page: str) -> str:
    # tutorials are copied into docs/ at build time (gitignored there); the README links their tracked source
    target = f"notebooks/{Path(page).name}" if page.startswith("tutorials/") else f"docs/{page}"
    return f"[{title}]({target})"


def docs_site_block(root: Path = ROOT) -> str:
    """The README's table of the documentation site: one row per nav section; the API reference collapses to one link."""
    rows = ["| Section | Pages |", "|---|---|"]
    for section, pages in docs_site_nav(root):
        if section == "API reference":
            modules = [page for title, page in pages if title.startswith("aether_quant.")]
            cell = f"[Overview](docs/reference/index.md), one page per facade ({len(modules)}), generated by `scripts/build_docs.py`"
        elif len(pages) == 1 and not pages[0][0]:
            cell = _site_link(section, pages[0][1])
        else:
            cell = " · ".join(_site_link(title, page) for title, page in pages)
        rows.append(f"| {section} | {cell} |")
    return "\n".join(rows)


def changelog_latest_block(root: Path = ROOT, count: int = 3) -> str:
    """The last `count` phases of `development/Changelog.md`, newest first, each linked to its heading on GitHub."""
    text = (Path(root) / "development" / "Changelog.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (Phase .+?)\s*$", text, flags=re.MULTILINE)[-count:]
    base = "https://github.com/leon1706-lol/Aether-quant/blob/main/development/Changelog.md"
    return "\n".join(f"- [{heading}]({base}#{_anchor(heading)})" for heading in reversed(headings))


def _anchor(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def compute_blocks(root: Path = ROOT) -> dict[str, str]:
    """Every generated block a living doc may hold, by name."""
    return {"DOCS_SITE": docs_site_block(root), "CHANGELOG_LATEST": changelog_latest_block(root)}


def apply_blocks(text: str, blocks: dict[str, str]) -> tuple[str, list[str]]:
    """`text` with each `<!-- AQ:NAME_START -->...<!-- AQ:NAME_END -->` it holds rewritten from `blocks`; also the names that moved."""
    changed = []
    for name, body in blocks.items():
        start, end = f"<!-- AQ:{name}_START -->", f"<!-- AQ:{name}_END -->"
        if start not in text or end not in text:
            continue
        head, rest = text.split(start, 1)
        old, tail = rest.split(end, 1)
        new = f"\n{body}\n"
        if old != new:
            changed.append(name)
            text = f"{head}{start}{new}{end}{tail}"
    return text, changed


def tracked_docs(root: Path = ROOT) -> list[Path]:
    output = subprocess.run(["git", "ls-files", "*.md"], cwd=root, capture_output=True, text=True, check=True, timeout=30).stdout
    paths = [Path(root) / line for line in output.splitlines() if line and not line.startswith(EXCLUDED_PREFIXES)]
    return [path for path in paths if path.exists()]


def sync_docs(paths: Iterable[Path], facts: dict[str, str], *, check: bool = False, blocks: dict[str, str] | None = None) -> dict[str, list[str]]:
    """{"changed": ["file: key"], "unknown": ["file: key"]}. Writes only the files whose text moved, and nothing with `check`.
    `blocks` (from `compute_blocks`) also rewrites the generated blocks a doc holds."""
    report: dict[str, list[str]] = {"changed": [], "unknown": []}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        updated, unknown, changed = apply_facts(text, facts)
        if blocks:
            updated, moved = apply_blocks(updated, blocks)
            changed = [*changed, *(f"block {name}" for name in moved)]
        report["changed"] += [f"{path.name}: {key}" for key in changed]
        report["unknown"] += [f"{path.name}: {key}" for key in unknown]
        if updated != text and not check:
            path.write_text(updated, encoding="utf-8", newline="\n")
    return report
