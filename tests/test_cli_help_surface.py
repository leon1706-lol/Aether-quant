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
    return {
        opt
        for action in parser._actions
        for opt in action.option_strings
        if opt not in ("-h", "--help")
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


_FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]+)")


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
    for name, parser in all_parsers.items():
        known |= _flags_of(parser)

    allowlist = {
        # Documented pass-through examples of the CHILD commands' own args.
        "--apply", "--tickers", "--series",
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
