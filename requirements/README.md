# requirements

Dependency files live here so Lean CLI doesn't auto-detect and bind-mount one from the root.

| File | Used by | Contents |
|---|---|---|
| `requirements/requirements.txt` | Local dev, `train.py`, `Dockerfile` | The full app and worker stack |
| `requirements/requirements-dev.txt` | Local dev and tests | Lean CLI, pytest, ruff, test doubles, data helpers |
| `requirements/lean-runtime.txt` | `Dockerfile.lean` (`aq backtest`) | Only what the pinned Lean image lacks |

`aq backtest` builds a local image on the pinned <!--fact:lean.engine-->quantconnect/lean:17900<!--/fact--> engine from `Dockerfile.lean`, which avoids Lean CLI's Windows bind mount of a generated `requirements.txt`.

The library's own extras (`lib`, `research`, `train`) are in `pyproject.toml`.

## Hash locks (V6.6.7)

Every install in a workflow, Dockerfile or shell script reads a hash-locked file in `requirements/lock/`, because the OpenSSF Scorecard counts a pip install as pinned only with `--require-hashes`. Each `<profile>.in` names what that job needs (it can include the files above with `-r ../<file>`), and `<profile>.txt` is generated from it: exact versions, a sha256 for every file, one resolution for CPython 3.11 on Linux and Windows (the CI interpreter; `compat` is 3.10). The `ci` and `runtime` profiles take torch from the CPU index.

| Profile | Used by |
|---|---|
| `ci` | the suite jobs, release tag-tests, `codespace_verify.sh`, the devcontainer |
| `runtime` | dependency audit, wheel-smoke, the engine image, cli-smoke |
| `tools` | lint, typecheck, bandit, packaging, signing |
| `compat` | the Python 3.10 compatibility job (vermin) |
| `docs`, `notebooks`, `light`, `dashboard`, `build-ext`, `fuzz`, `sbom` | the docs and Pages builds, the notebooks job, the light jobs (formal, forward ledger, research cycle), the dashboard image, the C++ accelerator build, the fuzz workflow, the release SBOM |
| `lean-cli`, `lean-runtime` | the DinD Codespace's Lean CLI; what `Dockerfile.lean` adds to the Lean image |

```powershell
.venv\Scripts\python.exe -m pip install uv          # once
python scripts/lock_requirements.py                  # every profile, or --profile ci
python scripts/scorecard_pins.py                     # must print 0 unpinned
```

Raise a floor in the matching `.in` or in `requirements*.txt`, regenerate, and commit the `.txt`: `tests/test_requirement_locks.py` fails while a lock pin is outside a floor it inherits. A Dependabot floor bump needs the regeneration pushed onto its branch. `pip-audit --requirement requirements/lock/<profile>.txt --require-hashes --disable-pip` audits a lock (the CPU torch wheel is not on PyPI, so it is skipped by name).
