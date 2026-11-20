# {{name}}

A signal project made with `aq init` (aether-quant).

```bash
pip install aether-quant pytest
pytest                      # the signal's own checks, including no look-ahead
aq pipeline run             # data, signal, evaluate, gate, report: runs/<id>/report.md
aq pipeline status          # the last run's stages
```

- `my_signal.py`: your `score(closes)`. Keep a name no Python module has (a `signal.py` here would shadow the standard `signal` module and stop pytest).
- `pipeline.toml`: the data, the signal file and the gate. Set the gate before the first run.
- The workflow .github/workflows/pipeline.yml: the same on every push and every Monday, on GitHub's free runners. Its report is the
  workflow run's artifact.

The gate reads the information coefficient (IC) at the gate horizon and its Newey-West t. A pass is evidence on one sample, not
a promise: every new idea you test is another trial, and luck grows with their number.
