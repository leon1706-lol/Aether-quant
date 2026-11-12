"""docs_facts.py and the guards that keep the docs true: a fact drifts into a red suite, the README's library example runs,
and a living doc can't name a path, config key, command or problem entry that no longer exists."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

import docs_facts

ROOT = Path(__file__).resolve().parents[1]

# History describes what was true at the time; a generated block and the owner's canvas are not hand-maintained references.
HISTORY_DOCS = {"development/Changelog.md", "development/Problems.md", "development/research_results.md", "todo.md"}
# Written by a run, so a fresh checkout doesn't have them
RUNTIME_OUTPUTS = ("ml/", "visualization/", "grafana/", "backtests/")
_PATH_RE = re.compile(r"`((?:[\w.-]+/)+[\w.-]+\.(?:py|md|json|toml|yml|yaml|ps1|sh|txt|csv|lean))`")
_CONFIG_KEY_RE = re.compile(r"`(phase_v2(?:\.[a-z0-9_]+)+)`")
_COMMAND_RE = re.compile(r"`aq ([a-z][a-z-]*)")
_PROBLEM_RE = re.compile(r"(?:^|[\s(,/])#(\d{1,3})\b")


def _living_docs() -> list[Path]:
    try:
        docs = docs_facts.tracked_docs(ROOT)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    return [doc for doc in docs if doc.relative_to(ROOT).as_posix() not in HISTORY_DOCS]


def _ignored(relatives: list[str]) -> set[str]:
    # bytes, not text: on Windows text mode sends "\r\n", and git reads every path but the last with a trailing "\r"
    done = subprocess.run(["git", "check-ignore", "--stdin"], cwd=ROOT, input="\n".join(relatives).encode("utf-8"), capture_output=True, timeout=60)
    return {line.strip() for line in done.stdout.decode("utf-8", errors="replace").splitlines()}


def test_every_fact_in_the_docs_is_known_and_current():
    report = docs_facts.sync_docs(_living_docs(), docs_facts.compute_facts(ROOT), check=True, blocks=docs_facts.compute_blocks(ROOT))
    assert not report["unknown"], report["unknown"]
    assert not report["changed"], f"stale facts, run `aq docs sync`: {report['changed']}"


def test_apply_facts_replaces_values_and_reports_drift_and_unknown_keys():
    text = "a <!--fact:x.y-->1<!--/fact--> b <!--fact:x.z-->2<!--/fact--> c <!--fact:nope-->3<!--/fact-->"
    updated, unknown, changed = docs_facts.apply_facts(text, {"x.y": "1", "x.z": "9"})
    assert updated == "a <!--fact:x.y-->1<!--/fact--> b <!--fact:x.z-->9<!--/fact--> c <!--fact:nope-->3<!--/fact-->"
    assert unknown == ["nope"] and changed == ["x.z"]


def test_sync_docs_writes_only_outside_check_mode(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("<!--fact:a-->1<!--/fact-->", encoding="utf-8")
    assert docs_facts.sync_docs([doc], {"a": "2"}, check=True)["changed"] == ["doc.md: a"]
    assert "-->1<" in doc.read_text(encoding="utf-8")
    docs_facts.sync_docs([doc], {"a": "2"})
    assert "-->2<" in doc.read_text(encoding="utf-8")


def test_universe_window_problem_changelog_and_python_facts():
    config = {"phase1": {"universe": {"assets": [{"ticker": "BTCUSD", "security_type": "crypto"}, {"ticker": "ADAUSD", "security_type": "crypto"},
                                                 {"ticker": "TLT", "security_type": "equity", "asset_class": "bond"}]},
                         "windows": {"backtest": {"start": "a", "end": "b"}, "purge_label_horizon_days": 20}}}
    assert docs_facts.universe_facts(config) == {"universe.total": "3", "universe.crypto": "2", "universe.bond": "1",
                                                 "universe.list.crypto": "ADAUSD, BTCUSD", "universe.list.bond": "TLT"}
    assert docs_facts.window_facts(config) == {"windows.backtest": "a to b"}
    problems = docs_facts.problem_facts("### 88a. x\n🟢 `fixed`\n### 1. y\n🟡 `partial`\n### 7. z\n🔴 `closed`\n")
    assert problems == {"problems.total": "3", "problems.last": "88", "problems.fixed": "1", "problems.partial": "1", "problems.closed": "1"}
    assert docs_facts.changelog_facts("## Phase V1 — a\n## Phase V2 — b\n") == {"changelog.latest": "V2"}
    assert docs_facts.python_facts('requires-python = ">=3.10"\n', 'python-version: "3.11"\npython-version: "3.11"\npython-version: "3.10"\n') == {
        "python.requires": ">=3.10", "python.ci": "3.11"}


def test_the_python_badge_names_the_version_ci_runs():
    facts = docs_facts.compute_facts(ROOT)
    assert f"badge/python-{facts['python.ci']}-" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_readme_library_example_runs(capsys):
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text[text.index("## The `aether_quant` Library"):text.index("## Download")]
    example = re.search(r"```python\n(.*?)```", section, re.DOTALL).group(1)
    exec(compile(example, "README example", "exec"), {"__name__": "readme_example"})  # noqa: S102 - the repo's own README
    assert "PBO:" in capsys.readouterr().out


def test_living_docs_name_only_paths_that_exist():
    wanted: dict[str, list[str]] = {}
    for doc in _living_docs():
        for path in _PATH_RE.findall(doc.read_text(encoding="utf-8")):
            base = doc.parent / path
            if path.startswith(RUNTIME_OUTPUTS):
                continue
            if not (ROOT / path).exists() and not base.exists():
                wanted.setdefault(path, []).append(doc.relative_to(ROOT).as_posix())
    # gitignored artifacts (ml/evaluation/*.json) exist only after a run
    missing = {path: docs for path, docs in wanted.items() if path not in _ignored(list(wanted))} if wanted else {}
    assert not missing, json.dumps(missing, indent=1)


def test_living_docs_name_only_config_keys_that_exist():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    missing: dict[str, list[str]] = {}
    for doc in _living_docs():
        for key in _CONFIG_KEY_RE.findall(doc.read_text(encoding="utf-8")):
            node = config
            for part in key.split("."):
                node = node.get(part) if isinstance(node, dict) else None
                if node is None:
                    break
            if node is None:
                missing.setdefault(key, []).append(doc.relative_to(ROOT).as_posix())
    assert not missing, json.dumps(missing, indent=1)


def test_living_docs_name_only_commands_and_problem_entries_that_exist():
    from aq_cli import build_parser

    parser = build_parser()
    commands = set(next(action.choices for action in parser._actions if isinstance(getattr(action, "choices", None), dict)))
    numbers = {int(re.match(r"\d+", number).group()) for number in docs_facts._PROBLEM_HEADING_RE.findall((ROOT / "development" / "Problems.md").read_text(encoding="utf-8"))}
    problems = []
    for doc in _living_docs():
        text = doc.read_text(encoding="utf-8")
        problems += [f"{doc.relative_to(ROOT).as_posix()}: aq {name}" for name in _COMMAND_RE.findall(text) if name not in commands]
        problems += [f"{doc.relative_to(ROOT).as_posix()}: #{number}" for number in _PROBLEM_RE.findall(text) if int(number) not in numbers]
    assert not problems, sorted(set(problems))


def test_the_cli_reference_carries_no_version_tags():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text[text.index("## CLI Reference"):text.index("## Release Process")]
    assert not re.findall(r"\bV\d+\.\d+", section)


def _github_anchor(heading: str) -> str:
    text = heading.replace("`", "").strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def test_every_link_in_the_readme_contents_lands_on_a_heading():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    archive = (ROOT / "development" / "research_results.md").read_text(encoding="utf-8")
    headings = {_github_anchor(line.lstrip("#")) for line in readme.splitlines() if line.startswith("#")}
    archive_headings = {_github_anchor(line.lstrip("#")) for line in archive.splitlines() if line.startswith("#")}
    contents = readme[readme.index("## Table of Contents"):readme.index("## The `aether_quant` Library")]
    local = re.findall(r"\]\(#([^)]+)\)", contents)
    moved = re.findall(r"\]\(development/research_results\.md#([^)]+)\)", contents)
    assert local and moved
    assert not [anchor for anchor in local if anchor not in headings]
    assert not [anchor for anchor in moved if anchor not in archive_headings]


def test_the_readme_contents_lists_every_cli_command():
    from aq_cli import build_parser

    parser = build_parser()
    commands = next(action.choices for action in parser._actions if isinstance(getattr(action, "choices", None), dict))
    contents = (ROOT / "README.md").read_text(encoding="utf-8")
    contents = contents[contents.index("## Table of Contents"):contents.index("## The `aether_quant` Library")]
    assert not [name for name in commands if f"(#aq-{name})" not in contents]


def test_the_readme_intro_is_prose():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    intro = text[text.index("</p>\n\nAether Quant"):text.index("## Known Limitations")]
    assert not [line for line in intro.splitlines() if line.startswith("- ")]



# V6.6.5: generated blocks, and the README's map of the documentation site


def test_apply_blocks_rewrites_only_its_block_and_reports_drift():
    text = "a\n<!-- AQ:X_START -->\nold\n<!-- AQ:X_END -->\nb <!-- AQ:Y_START -->keep<!-- AQ:Y_END -->"
    updated, changed = docs_facts.apply_blocks(text, {"X": "new", "Z": "absent"})
    assert updated == "a\n<!-- AQ:X_START -->\nnew\n<!-- AQ:X_END -->\nb <!-- AQ:Y_START -->keep<!-- AQ:Y_END -->" and changed == ["X"]
    assert docs_facts.apply_blocks(updated, {"X": "new"}) == (updated, [])


def test_every_docs_page_is_in_the_site_nav_and_the_readme_shows_the_nav():
    nav = {page for _, pages in docs_facts.docs_site_nav(ROOT) for _, page in pages}
    tracked = subprocess.run(["git", "ls-files", "docs/*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    pages = {path.removeprefix("docs/") for path in tracked}
    missing = sorted(page for page in pages if page not in nav)
    assert not missing, f"add to mkdocs.yml's nav: {missing}"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "<!-- AQ:DOCS_SITE_START -->" in readme and docs_facts.docs_site_block(ROOT) in readme
    for title, page in ((t, p) for section, rows in docs_facts.docs_site_nav(ROOT) if section != "API reference" for t, p in rows):
        target = f"notebooks/{Path(page).name}" if page.startswith("tutorials/") else f"docs/{page}"
        assert f"]({target})" in readme, f"the README does not link {target}"
