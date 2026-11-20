# Your own pipeline

`aq init` starts a project for your own signal, and `aq pipeline run` takes it from data to a verdict in one command. The same runs on GitHub's free runners every week.

```bash
pip install aether-quant pytest
aq init my-signal
cd my-signal
pytest                    # your signal's checks, including no look-ahead
aq pipeline run           # data, signal, evaluate, gate, report: runs/<id>/report.md
aq pipeline status        # which stages the last run finished
```

## What `aq init` writes

| File | What it is |
|---|---|
| `my_signal.py` | `score(closes)`: dates x tickers, higher is better. The starter is 60-session momentum that skips the last 5 sessions. A file named after a Python module (`signal.py`) would shadow it |
| tests/test_signal.py | The score has the closes' shape, and a later close never changes an earlier score |
| `pipeline.toml` | The data, the signal file, an optional small model, and the gate |
| .github/workflows/pipeline.yml | The tests and the pipeline on every push and every Monday; the report is the run's artifact |

## The stages

Each stage records its result in `runs/<id>/state.json`, so a run stopped halfway continues where it was (`aq pipeline run --run-id <id>`).

1. **data**: the bundled sample, or your wide CSV (a date column, then one column per ticker).
2. **signal**: your `score(closes)`.
3. **train** (optional, `train = true`): a small model trained on the same closes with the example-model recipe and `--memory-profile low`. It needs a source checkout with the `train` extra.
4. **evaluate**: for each signal, the IC by horizon (1 to 60 sessions), its half-life, the long-short spread after costs, the exposure to 20-session momentum and the IC left after it, and breadth (`aether_quant.research.alpha_report`).
5. **gate**: the IC at the gate horizon and its Newey-West t against the thresholds in `pipeline.toml`.
6. **report**: `report.json` and `report.md`.

`aq pipeline run` exits 0 when every signal passes its gate and 3 when one fails, so a workflow can tell the two apart.

The evaluate stage is one library call, so a notebook can run it on any signal:

```python
from aether_quant import research, samples

closes = samples.load_sample_prices()
signal = closes.pct_change(20, fill_method=None)   # 20-session momentum, known at each close
report = research.alpha_report(signal, closes, groups={ticker: "crypto" for ticker in closes}, factors={}, horizon=20)
print(report["term_structure"][20], report["half_life_sessions"])
```

## Set the gate first

Write `min_ic` and `min_t` before the first run. A threshold picked after seeing the result is not a test. Every idea you try is another trial, and the best of many trials looks better than it is. The project's own research counts its trials and deflates its Sharpe for them ([Overfitting](overfitting.md)).

## Without a project

`aq pipeline run` in an empty folder runs the defaults: the bundled sample and 20-session momentum. The project's weekly `model-cycle.yml` workflow runs exactly that, builds and scores the example models, and records one row on the `forward-ledger` branch.
