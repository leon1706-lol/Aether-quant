"""V5.4.7 CLI help-surface guards (development/Problems.md #125).

Two regression classes this file pins:

1. **Every `aq <subcommand> --help` must exit 0.** CI's cli-smoke battery
   only ever covered two of the ~23 subcommands; a broken import inside one
   command's parser-builder branch (the #115/#79 class of installed-CLI
   failures) previously shipped invisibly.

2. **README's CLI Reference must stay in sync with build_parser().**
   The `--all` help text drifted from reality for a full release cycle
   (#125: it stopped listing --benchmarks in V5.4.4), and the README's
   train/evaluate blocks were missing flags that existed since V5.2/V5.3.
   Both directions are checked: every parser flag documented, every
   documented flag real.
"""

import re
from pathlib import Path

import pytest

import aq_cli

ROOT = Path(__file__).resolve().parent.parent


def _subcommands():
    parser = aq_cli.build_parser()
    subparsers_action = next(
        action for action in parser._actions if isinstance(action, type(parser._subparsers._group_actions[0]))
    )
    return subparsers_action


def _all_subparsers():
    """{name: ArgumentParser} for every top-level subcommand plus its own
    nested subparsers' choices (config get/set/..., docker up/build, ...)."""
    top = aq_cli.build_parser()
    sub_action = next(a for a in top._actions if getattr(a, "choices", None) and "train" in getattr(a, "choices", {}))
    result = {}
    for name, sub in sub_action.choices.items():
        result[name] = sub
        inner = next(
            (a for a in sub._actions if a.__class__.__name__ == "_SubParsersAction"),
            None,
        )
        if inner is not None:
            for child_name, child in inner.choices.items():
                result[f"{name} {child_name}"] = child
    return result


def _flags_of(parser) -> set[str]:
    """Every long option; a short alias (-k) counts through its long form (--keyword), which the README must name."""
    return {
        opt
        for action in parser._actions
        for opt in action.option_strings
        if opt not in ("-h", "--help") and (opt.startswith("--") or not any(other.startswith("--") for other in action.option_strings))
    }


@pytest.mark.parametrize("command", sorted(_all_subparsers()))
def test_help_exits_zero_for_every_subcommand(command):
    # `_all_subparsers()` already resolves to the LEAF parser (top-level
    # name or "parent child"), so --help is the only argv needed.
    with pytest.raises(SystemExit) as excinfo:
        _all_subparsers()[command].parse_args(["--help"])
    assert excinfo.value.code == 0


# ---------------------------------------------------------------------------
# README <-> parser flag sync
# ---------------------------------------------------------------------------

_README = (ROOT / "README.md").read_text(encoding="utf-8")


def _readme_cli_sections():
    """{command_name: section_text} from README's '#### `aq X`' headings up
    to the next heading - includes prose bullets, so flags documented only
    in bullet lists (e.g. `aq config preset`) count as documented."""
    sections = {}
    pattern = re.compile(r"^#### `aq ([a-z-]+)`\s*$", re.MULTILINE)
    matches = list(pattern.finditer(_README))
    for i, match in enumerate(matches):
        name = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(_README)
        sections.setdefault(name, "")
        sections[name] += _README[start:end]
    return sections


_FLAG_RE = re.compile(r"(?<![\w!-])(--[a-z][a-z0-9-]+)")  # not the "--" that opens an HTML comment (<!--fact:...-->)


def test_readme_documents_every_parser_flag():
    sections = _readme_cli_sections()
    problems = []
    for name, parser in _all_subparsers().items():
        base = name.split()[0]
        section = sections.get(base)
        if section is None:
            problems.append(f"{name}: no README '#### `aq {base}`' section")
            continue
        documented = set(_FLAG_RE.findall(section))
        missing = sorted(_flags_of(parser) - documented)
        if missing:
            problems.append(f"aq {name}: parser flags absent from README: {missing}")
    assert not problems, "\n".join(problems)


def test_readme_documents_no_phantom_flags():
    """The reverse direction: every flag written in a CLI Reference section
    must exist on the corresponding parser (or its nested children), so a
    renamed/dropped flag can't leave stale docs behind."""
    all_parsers = _all_subparsers()
    known = set()
    for parser in all_parsers.values():
        known |= _flags_of(parser)

    allowlist = {
        # Documented pass-through examples of the CHILD commands' own args.
        "--apply", "--tickers", "--series", "--quotes",
        "--version-id", "--to-version-id",  # `aq retrain` args passed verbatim
        # Lean CLI's own flag, documented in render-lean-config's prose as
        # what the DEPLOY step passes to `lean`, not an aq flag.
        "--lean-config",
    }
    problems = []
    for name, section in _readme_cli_sections().items():
        parser_flags = set()
        for cmd, parser in all_parsers.items():
            if cmd.split()[0] == name:
                parser_flags |= _flags_of(parser)
        for flag in _FLAG_RE.findall(section):
            if flag in ("-h", "--help"):
                continue
            if flag not in parser_flags and flag not in known and flag not in allowlist:
                problems.append(f"aq {name}: README documents {flag} but no parser defines it")
    assert not problems, "\n".join(sorted(set(problems)))


# ---------------------------------------------------------------------------
# V6.7.1: the 10/10 rubric (development/cli_audit.md), enforced for every leaf command
# ---------------------------------------------------------------------------

import os  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import aq_devtools  # noqa: E402


def _leaves() -> dict[str, object]:
    return {" ".join(path): parser for path, parser in aq_devtools.walk_commands(aq_cli.build_parser()) if path and not aq_devtools._subparsers_of(parser)}


# The arguments a leaf needs to parse; a new leaf with required arguments and no row fails test_every_leaf_parses_to_its_command.
REQUIRED_ARGS = {
    "models remove": "m", "models install": "m", "models info": "m", "models score": "m", "research": "--signal s.csv", "init": "proj", "cycle schedule": "show", "clean": "coverage", "trade-lock": "--status",
    "kill-switch": "--status", "hooks coverage": "status", "phase check": "--version V1", "data fetch": "--coins BTC --out c.csv", "data sample": "--out d",
    "lab init": "mylab",
    "cycle research": "rules --round r.json", "cycle decide": "--generation g --weights w.csv --ledger-file l.jsonl --session 2026-01-02",
    "cycle promote": "--generation g --to shadow", "config get": "a.b", "config set": "a.b 1", "config preset": "--list", "lean get": "a",
    "lean set": "a 1", "retrain": "plan", "backfill": "fred", "fetch": "crypto --ticker BTCUSD --start 2024-01-01 --end 2024-02-01", "users add": "ana", "users rotate": "ana",
    "users remove": "ana", "secrets set": "IB_ACCOUNT", "secrets delete": "IB_ACCOUNT", "commit": "-m msg", "completion": "bash",
    "ci logs": "1", "deps apply": "58", "deps why": "numpy", "codespace delete": "cs", "vault record": "--label l a.json",
    "vault graph": "--summary s --files a.py", "problems show": "1", "scaffold": "risk/x.py", "examples run": "demo", "notebooks run": "x",
    "data info": "c.csv", "data explore": "c.csv", "data diff": "m.json --root data", "signal check": "s.csv", "signal eval": "s.csv",
    "signal compare": "a.csv b.csv", "signal neutralize": "s.csv", "signal backtest": "s.csv", "features inspect": "ret_20",
    "overfit pbo": "t.csv", "overfit psr": "--returns r.csv", "overfit dsr": "--returns r.csv --trials 5 --trial-variance 0.1",
    "overfit hurdle": "--trials 5 --trial-variance 0.1", "overfit haircut": "--sharpe 1 --obs 100 --trials 5", "overfit mintrl": "--returns r.csv",
    "lab new": "m --template linear", "lab train": "m", "lab show": "latest", "lab eval": "latest", "lab compare": "a b", "lab card": "latest",
    "lab sweep": "m --grid model.ridge=1,2", "lab explain": "latest", "lab ablate": "latest", "lab seeds": "latest", "lab export": "latest --name n",
    "dataset info": "d.csv", "dataset leakage": "d.csv", "trials add": "--trial-id t --role candidate --sharpe 0.1 --obs 10", "runs show": "r",
    "runs diff": "a b", "release check": "v1.0.0",
}

# Every read command prints JSON with --json, every write has --dry-run (or --check), every deletion or loosening asks (--yes).
READ_COMMANDS = {
    "hello", "models list", "models info", "pipeline status", "pipeline validate", "pipeline list", "train", "test", "research", "prove", "cycle status",
    "config get", "config keys", "config diff", "config validate", "lean get", "lean keys", "lean diff", "lean validate", "paper-readiness", "clean",
    "trade-lock", "kill-switch", "fetch", "ib status", "assets status", "evaluate", "users list", "live-readiness", "accounts list", "accounts validate",
    "accounts status", "live status", "secrets status", "secrets-check", "audit-log", "docs sync", "docs links", "verify", "hooks status", "hooks coverage",
    "doctor", "version", "status", "ci status", "ci logs", "deps prs", "deps why", "coverage report", "coverage clean", "codespace list", "problems next",
    "problems show", "problems open", "phase check", "examples list", "notebooks list", "bench run", "bench baseline", "bench compare", "data info", "data diff",
    "signal check", "signal eval", "signal compare", "signal backtest", "features list", "features inspect", "overfit pbo", "overfit psr", "overfit dsr",
    "overfit hurdle", "overfit haircut", "overfit mintrl", "lab train", "lab runs", "lab show", "lab eval", "lab compare", "lab sweep", "lab explain",
    "lab ablate", "lab seeds", "lab export", "dataset build", "dataset info", "dataset leakage", "stack inspect", "stack decay", "stack attrib",
    "trials count", "trials list", "trials dsr", "runs list", "runs show", "runs diff", "api-diff", "release check", "health",
}
WRITE_COMMANDS = {
    "models remove", "init", "train", "test", "backtest", "cycle daily", "cycle retrain", "cycle schedule", "docker up", "docker build", "docker down",
    "docker ps", "docker logs", "config set", "config preset", "lean set", "retrain", "trade-lock", "kill-switch", "render-lean-config", "live up",
    "live down", "docs cli", "hooks install", "hooks coverage", "commit", "ci local", "deps apply", "codespace stop", "codespace delete", "vault record",
    "vault graph", "scaffold", "features build", "lab train", "dataset build", "trials add",
}
CONFIRM_COMMANDS = {"clean", "trade-lock", "kill-switch", "live up", "coverage clean", "codespace delete", "users rotate", "users remove", "secrets delete"}
EXEMPT = {
    "models install": "downloads into the cache after its sha256 check; aq models remove undoes it",
    "models score": "prints scores, or writes the --out file it names",
    "pipeline run": "runs the stages its own file names into its run folder; aq pipeline validate is its dry run",
    "profile": "prints the profiler's own pstats table; aq bench run --json gives the timings as JSON",
    "report": "lists runs, or renders one run's HTML report from that run's own files",
    "cycle research": "each stage is checked against its rule file's hash and refuses to rescore without --force",
    "cycle decide": "appends one dated decision row to the ledger file it names",
    "cycle promote": "R-ADMIT1 refuses a move the evidence does not allow; every move is an append-only ledger row",
    "api": "a server in the foreground (--check asks a running one)",
    "webui": "a server in the foreground",
    "backfill": "passes through to the backfill module, whose default is a dry run (--apply writes)",
    "users add": "prints the new token once; aq users remove undoes it",
    "secrets set": "prompts for the value without echo; aq secrets delete undoes it",
    "docs build": "builds the site into site/",
    "docs serve": "serves the site locally",
    "check": "runs the hook's gates and commits nothing",
    "completion": "prints a script",
    "help": "prints help",
    "deps lock": "rebuilds the tracked locks from their .in files; git shows the change",
    "deps pins": "reads only: scripts/scorecard_pins.py prints its findings",
    "deps audit": "reads only: pip-audit prints its findings",
    "coverage misses": "reads only: scripts/coverage_misses.py prints its findings",
    "lint": "runs ruff; --fix changes only what ruff fixes",
    "bug-report": "prints Markdown, or writes the --out file it names",
    "examples run": "runs an example script",
    "notebooks run": "executes a notebook, or writes the --out file it names",
    "data fetch": "downloads into the cache and writes the --out file it names",
    "data sample": "writes the sample into the --out folder it names",
    "data explore": "writes the HTML page it names",
    "data manifest": "always JSON: to stdout, or to the --out file it names",
    "signal neutralize": "writes the --out file it names",
    "lab init": "creates a lab folder and never overwrites",
    "lab new": "creates a model folder and refuses to overwrite without --force",
    "lab card": "writes the card into the run folder, or the --out file it names",
    "stack lab-baseline": "adds one run to the lab it names",
}


def test_every_leaf_has_examples_and_no_version_history_in_its_help():
    problems = []
    for name, parser in _leaves().items():
        if "aq " not in (parser.epilog or ""):
            problems.append(f"aq {name}: no 'Examples:' epilog")
        texts = [parser.description or ""] + [action.help or "" for action in parser._actions]
        problems += [f"aq {name}: version history in help: {text[:60]!r}" for text in texts if re.search(r"\bV\d+\.\d+", text)]
    assert not problems, "\n".join(problems)


def test_every_leaf_parses_to_its_command():
    parser = aq_cli.build_parser()
    modules = {"aq_cli", "aq_devtools", "aq_testtools", "aq_lab_cli"}
    problems = []
    for name in _leaves():
        argv = [*name.split(), *shlex.split(REQUIRED_ARGS.get(name, ""))]
        try:
            args = parser.parse_args(argv)
        except SystemExit:
            problems.append(f"aq {' '.join(argv)}: does not parse (add the leaf's required arguments to REQUIRED_ARGS)")
            continue
        func = getattr(args, "func", None)
        if func is None or func.__module__ not in modules or not func.__name__.startswith("cmd_"):
            problems.append(f"aq {name}: parses to {func!r}")
    assert not problems, "\n".join(problems)
    assert not set(REQUIRED_ARGS) - set(_leaves()), "REQUIRED_ARGS names a command that no longer exists"


def test_every_leaf_is_classified_and_has_the_flags_its_class_needs():
    leaves = _leaves()
    flags = {name: {option for action in parser._actions for option in action.option_strings} for name, parser in leaves.items()}
    classified = READ_COMMANDS | WRITE_COMMANDS | CONFIRM_COMMANDS | set(EXEMPT)
    problems = [f"aq {name}: in no class (READ_COMMANDS, WRITE_COMMANDS, CONFIRM_COMMANDS, or EXEMPT with a reason)" for name in sorted(set(leaves) - classified)]
    problems += [f"aq {name}: classified but not a command" for name in sorted(classified - set(leaves))]
    problems += [f"aq {name}: a read command without --json" for name in sorted(READ_COMMANDS & set(leaves)) if "--json" not in flags[name]]
    problems += [f"aq {name}: a write without --dry-run or --check" for name in sorted(WRITE_COMMANDS & set(leaves)) if not {"--dry-run", "--check"} & flags[name]]
    problems += [f"aq {name}: a deletion or loosening without --yes" for name in sorted(CONFIRM_COMMANDS & set(leaves)) if "--yes" not in flags[name]]
    problems += [f"aq {name}: exempt with no reason" for name, reason in EXEMPT.items() if len(reason) < 10]
    assert not problems, "\n".join(problems)


def test_the_generated_reference_page_names_every_command():
    page = (ROOT / "docs" / "reference" / "cli.md").read_text(encoding="utf-8")
    missing = [name for name in _leaves() if f"`aq {name}`" not in page]
    assert not missing, f"docs/reference/cli.md is stale (aq docs cli): {missing}"


def test_every_command_in_agents_md_parses():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    block = agents.split("## Commands", 1)[1].split("```powershell", 1)[1].split("```", 1)[0]
    parser = aq_cli.build_parser()
    problems = []
    for line in block.splitlines():
        command = line.split("  #", 1)[0].strip()
        if not command.startswith("aq "):
            continue
        try:
            parser.parse_args(shlex.split(command)[1:])
        except SystemExit:
            problems.append(command)
    assert not problems, f"AGENTS.md's Commands block names commands that do not parse: {problems}"


@pytest.mark.parametrize("argv", [["--help"], ["lab", "--help"], ["doctor", "--help"]])
def test_help_is_fast(argv):
    env = {key: value for key, value in os.environ.items() if not key.startswith("COV")}  # time aq itself, not coverage tracing the child
    started = time.perf_counter()
    subprocess.run([sys.executable, "-m", "aq_cli", *argv], cwd=ROOT, env=env, capture_output=True, timeout=60, check=True)
    elapsed = time.perf_counter() - started
    slow_host = (sys.platform == "win32" and os.environ.get("CI")) or "coverage" in sys.modules  # CI's Windows runner, or a machine busy under coverage
    limit = 6.0 if slow_host else 3.0
    assert elapsed < limit, f"aq {' '.join(argv)} took {elapsed:.2f}s (no heavy import before a command runs, #421)"
