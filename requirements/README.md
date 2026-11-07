# requirements

Dependency files live here so Lean CLI doesn't auto-detect and bind-mount one from the root.

| File | Used by | Contents |
|---|---|---|
| `requirements/requirements.txt` | Local dev, `train.py`, `Dockerfile` | The full app and worker stack |
| `requirements/requirements-dev.txt` | Local dev and tests | Lean CLI, pytest, ruff, test doubles, data helpers |
| `requirements/lean-runtime.txt` | `Dockerfile.lean` (`aq backtest`) | Only what the pinned Lean image lacks |

`aq backtest` builds a local image on the pinned <!--fact:lean.engine-->quantconnect/lean:17900<!--/fact--> engine from `Dockerfile.lean`, which avoids Lean CLI's Windows bind mount of a generated `requirements.txt`.

The library's own extras (`lib`, `research`, `train`) are in `pyproject.toml`.
