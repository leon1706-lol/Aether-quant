"""Atheris entry point (V6.6.7, #363): `python fuzz/run_fuzz.py <target> [libFuzzer flags] [corpus dir]`.

Runs in `.github/workflows/fuzz.yml` (Atheris has Linux wheels only). The targets live in `fuzz/targets.py`, which
the tests drive with hypothesis on any machine.
"""

from __future__ import annotations

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent))

with atheris.instrument_imports():
    from targets import TARGETS


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in TARGETS:
        raise SystemExit(f"usage: run_fuzz.py <{'|'.join(sorted(TARGETS))}> [libFuzzer flags] [corpus]")
    atheris.Setup([argv[0], *argv[2:]], TARGETS[argv[1]])
    atheris.Fuzz()


if __name__ == "__main__":
    main(sys.argv)
