"""Run QuantConnect's Lean CLI with Docker-readable Windows temp folders.

Docker Desktop can read ordinary files created by PowerShell, but on some
Windows setups it cannot read files in directories created by Python's
``tempfile.mkdtemp``. Lean CLI uses those directories for config files,
startup scripts, and dependency manifests. Granting inherited read/execute
access on each generated directory fixes all of those mounts without
changing the user's global TEMP permissions.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


_real_mkdtemp = tempfile.mkdtemp


def _docker_readable_mkdtemp(*args, **kwargs) -> str:
    path = Path(_real_mkdtemp(*args, **kwargs))
    if os.name == "nt":
        # S-1-5-11 is Authenticated Users. RX is sufficient for Docker's
        # read-only bind mounts; the current user retains the directory's
        # normal owner permissions for Lean's own writes.
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:e",
                "/grant",
                "*S-1-5-11:(OI)(CI)RX",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return str(path)


tempfile.mkdtemp = _docker_readable_mkdtemp

from lean.main import main  # noqa: E402  (patch must happen before import)


if __name__ == "__main__":
    main()
