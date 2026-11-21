# lab

The model lab: build, train, evaluate, explain and package models inside the framework, on any close table. `aq lab`, `aq dataset`, `aq data explore` and `aq signal`/`aq features` (in `aq_lab_cli.py`) are thin commands over these modules, and `aether_quant.lab` exports them. The user guide is `docs/guide/model-lab.md`.

**The research rules are built in.** Every training run (per seed, failed sweep points included) is a trial in the lab's `trials.jsonl`, and every report shows N. A `holdout` split is sealed: it is never fitted, scored or evaluated, except once through `aq lab eval --holdout --i-understand-this-spends-it`, which records the read first. Rows whose label overlaps the next split are `purged`: kept for sequence windows, never fitted or scored.

**Light import.** `import lab` and every module but the three torch ones load no torch, so the lite install keeps working. `aether_quant.lab` exports the torch names lazily (a module `__getattr__`).

## Files

| File | What |
|---|---|
| `architectures.py` | The production networks (`AetherNet`, `AetherNetMultiTaskHorizons`, `AetherNetSequenceMultiTaskHorizons`, …), their head specs and JSON exporters. Moved from `train.py`, which re-exports them, so the trainers and saved artifacts are unchanged (torch) |
| `losses.py` | The ranking objectives (`soft_spearman`, `listnet`, `ic_pearson`, `ls_sharpe`, the class-balanced and cost-aware branches), the masked losses and the combined multitask loss (torch) |
| `training_utils.py` | Seeds, optimisers, schedulers, SWA, early stopping, the date batch sampler, checkpoints with RNG state, `select_device` (torch) |
| `objectives.py` | The objective names without torch: `RANKING_OBJECTIVES`, `CONTEXT_OBJECTIVES` |
| `spec.py` | The config schema: `DEFAULTS`, `load_spec` (lab.toml under the model's config.toml), `validate`, `--set` overrides |
| `lab_dataset.py` | `aq dataset build`: features from the registry, forward rank targets, split labels and purging, in the production dataset's columns; `holdout_window` reads the project's sealed window |
| `trainer.py` | `train_run`: within-date ranked inputs, split or annual folds, the template's fit per seed, scores, weights, pins and ledger trials; resumable (`retraining/run_resume.py`) |
| `run_registry.py` | The lab folder (`init_lab`, `find_lab`), runs indexed from `runs/*/run.json`, `find_run` (`latest` or an id prefix) |
| `run_evaluation.py` | `evaluate_run` (IC by split and year, decay, quintiles, overfit gap, a cost-aware book at N), `compare_runs`, `model_card` |
| `sweep.py` | Grid or random search, resumable, refused past `--max-trials`; the sweep's PBO |
| `explain.py` | Out-of-sample permutation importance, feature-group ablation, seed stability |
| `model_export.py` | A run as an `aq models` zip: JSON weights for the numpy forward pass, `lab_features.json`, card, sha256 manifest |
| `model_templates.py` | `aq lab new`: copies `aether_quant/_templates/lab/<template>/` (linear, mlp, multitask, tcn) |
| `data_explore.py` | `aq data info`/`explore`: coverage, gaps, calendar, returns, correlations, drawdowns, volatility |
| `report_html.py` | Self-contained HTML pages (inline SVG curves, heatmaps, histograms; light and dark) |

## Tests

One file per module (`tests/test_<module>.py`, group `lab` in `_SUBSYSTEM_TEST_FILES`), on `tests/lab_world.py`: a planted-signal close panel and a ready lab folder. `aq test --lab` runs them.
