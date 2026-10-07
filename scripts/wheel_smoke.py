"""Smoke-test an INSTALLED wheel of Aether Quant (V5.5.0, CI `wheel-smoke`).

Run it from OUTSIDE the repo checkout, in an environment where only the built
wheel is installed (not `pip install -e .`, which puts the whole repo root on
sys.path and hides every packaging gap):

    python -m build --wheel
    python -m venv /tmp/aq-wheel && /tmp/aq-wheel/bin/pip install dist/*.whl
    cd /tmp && /tmp/aq-wheel/bin/python /path/to/repo/scripts/wheel_smoke.py

It checks that
1. `aq_cli` resolves from site-packages, not from the working directory,
2. every module in every shipped package imports - a missing FIRST-PARTY
   module is a packaging bug (pyproject.toml `py-modules`/`packages`); a
   missing third-party dependency is reported but tolerated, since optional
   extras (ib_insync, yfinance, ...) are not part of the wheel's own contract,
3. every `aq <subcommand> --help` exits 0 in a fresh interpreter, which runs
   each command's lazy imports far enough to build its parser.

Exit code 0 = healthy, 1 = at least one packaging failure. Prints one line
per problem, so the CI log says exactly what to add to pyproject.toml.
"""

from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys
from pathlib import Path

# First-party roots shipped by pyproject.toml (kept in step by
# tests/test_packaging_modules.py, which fails when this drifts).
SHIPPED_PACKAGES = (
    "risk", "execution", "data_pipeline", "evaluation", "portfolio", "features", "audit", "inference",
    "analyzer", "monitoring", "topology", "liquidity", "experience",
)
SHIPPED_MODULES = (
    "aq_cli", "generate_backtest_report", "generate_evaluation_report", "json_safety", "performance_probe", "risk_controls",
)
FIRST_PARTY = set(SHIPPED_PACKAGES) | set(SHIPPED_MODULES) | {
    "main", "train", "risk_controls", "moe", "regime", "retraining", "notifications", "analyzer",
}


def _iter_module_names() -> list[str]:
    names = list(SHIPPED_MODULES)
    for package_name in SHIPPED_PACKAGES:
        package = importlib.import_module(package_name)
        names.append(package_name)
        for info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            names.append(info.name)
    return names


def check_imports() -> tuple[list[str], list[str]]:
    failures: list[str] = []
    tolerated: list[str] = []
    for name in _iter_module_names():
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as error:
            missing_root = (error.name or "").split(".")[0]
            if missing_root in FIRST_PARTY:
                failures.append(f"{name}: missing first-party module {error.name!r} - add it to pyproject.toml")
            else:
                tolerated.append(f"{name}: optional third-party dependency {error.name!r} not installed")
        except Exception as error:  # noqa: BLE001 - any other import-time crash is also a smoke failure
            failures.append(f"{name}: import raised {type(error).__name__}: {error}")
    return failures, tolerated


def subcommand_names() -> list[str]:
    import aq_cli

    parser = aq_cli.build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public subparser registry
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and choices:
            return sorted(choices)
    return []


def check_help(names: list[str]) -> list[str]:
    failures: list[str] = []
    for name in names:
        result = subprocess.run(
            [sys.executable, "-c", f"import sys, aq_cli; sys.argv = ['aq', {name!r}, '--help']; aq_cli.main()"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            failures.append(f"aq {name} --help exited {result.returncode}: {(result.stderr or result.stdout).strip()[-300:]}")
    return failures


def main() -> int:
    import aq_cli

    location = Path(aq_cli.__file__).resolve()
    if "site-packages" not in location.parts and "dist-packages" not in location.parts:
        print(f"FAIL: aq_cli resolved from {location}, not an installed wheel - run this OUTSIDE the checkout.")
        return 1

    import_failures, tolerated = check_imports()
    names = subcommand_names()
    help_failures = check_help(names) if names else ["no aq subcommands found on the parser"]

    for line in tolerated:
        print(f"note: {line}")
    for line in import_failures + help_failures:
        print(f"FAIL: {line}")
    print(
        f"wheel smoke: {len(import_failures)} import failure(s), {len(help_failures)} help failure(s) "
        f"across {len(names)} subcommands (installed at {location.parent})"
    )
    return 1 if (import_failures or help_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
