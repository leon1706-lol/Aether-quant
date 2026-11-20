# Train on a small machine

The model stack (the multitask network, the sequence network, the gate and the walk-forward) retrains on a laptop with 4 GB of RAM. It is slower than on a large machine, and it trains the same models.

```bash
pip install -e ".[train]"
aq cycle retrain --host local --estimate          # each memory profile's estimated peak for your dataset, and your RAM
aq cycle retrain --host local --smoke             # every stage on a synthetic panel, about a minute
aq cycle retrain --host local --procedure stack --memory-profile low --score-end 2023-06-30
```

## What `--memory-profile low` changes

| | `standard` | `low` |
|---|---|---|
| RAM the preflight asks for | 14 GB | 3.5 GB |
| Sequence windows | one dense (rows, window, features) array per split, about 2 GB | one (rows, features) matrix and an index; each batch's windows are gathered when it is drawn |
| Reading the dataset | the whole CSV in float64 | chunks, kept as float32 |
| The gate | reads the whole dataset | reads only its validation and backtest rows |
| Interruptions | a stage restarts | the sequence trainer saves a checkpoint every epoch; `--resume` continues it |

The gathered windows are the dense windows exactly: a test compares the two element by element, and the low profile trains bit-identical weights on the same seed. Interrupting a low-profile run and resuming it also gives the same weights as one uninterrupted run.

## Each trainer on its own

Every trainer takes the profile directly:

```bash
python train_sequence.py --version-id my_seq --memory-profile low --log-peak-memory peaks.jsonl
python train_sequence.py --version-id my_seq --memory-profile low --resume   # after an interruption
python train_multitask.py --version-id my_mt --memory-profile low
python train_gating.py --version-id my_gate --memory-profile low
python train.py --walk-forward --include-multitask --include-sequence --memory-profile low
```

`--log-peak-memory` appends the run's measured peak (Windows: the peak working set; Linux: VmHWM) to a JSONL file.

## Tips for a 4 GB machine

- Close the browser and chat apps first. They take the memory the trainer needs, and Windows then pages instead of failing, which makes a run hours slower.
- Run one heavy job at a time: a training run, a Lean backtest and the test suite each need most of the machine.
- Stop any time and continue later with `aq cycle retrain --resume` (or `--resume <run id>`). The run's folder, `ml/cycle/retrain_<id>/`, keeps its settings, its finished stages and the walk-forward it started, so nothing finished is trained again.
- `aq train` works the same way: every mode but `--init-only` records `ml/cycle/train_<id>/` when it starts, and `aq train --resume` continues it with its own settings. A walk-forward continues at its next window and reuses a window's dataset and baseline when they were written completely; the sequence trainer continues from its last epoch.
- `aq train --list-runs` (or `aq cycle retrain --list-runs`) shows every run, its finished steps, and whether it can be resumed, so you never need to look up a run id.

## The proof in CI

The `lowmem-proof` CI job builds a synthetic dataset the size of the real one (280,000 rows by 254 columns) and trains the multitask and sequence stages on it under the low profile. It fails if either stage's peak memory passes 2.6 GB (`scripts/lowmem_proof.py`).
