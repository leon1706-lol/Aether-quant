# Model lab

The model lab is where you build, train and judge your own models with the same networks, losses and statistics the trading system uses. It runs on any close table: the bundled public sample, coins you download with `aq data fetch`, or your own CSV. A lab is a folder; nothing in it touches the project's installed models.

The lab applies the project's research rules on every run:

- **Every training run counts as a trial.** Each seed of each run, failed sweep points included, is appended to the lab's `trials.jsonl`. Every report shows N, the number of trials so far, and judges a Sharpe by the deflated Sharpe at that N.
- **The holdout is sealed.** A dataset's `holdout` split is never fitted, scored or evaluated. `aq lab eval RUN --holdout --i-understand-this-spends-it` reads it once, records the read in `holdout_ledger.jsonl` first, and refuses a second read.
- **Purged splits.** Rows whose 20-session label overlaps the next split are labelled `purged`. They are kept so a sequence model's windows see every date, as live does, but they are never fitted or scored.
- **Inputs are ranks.** Features go in as within-date cross-sectional ranks, so no scaler is fitted and none can see the future.

## From a close table to a trained model

```bash
aq lab init mylab && cd mylab
aq data sample --out data                                   # or: aq data fetch --coins BTC,ETH,SOL --out data/closes.csv
aq data explore data/closes.csv                             # data/closes.html: returns, correlations, drawdowns, gaps
aq dataset build --prices data/closes.csv --out data/dataset.csv
aq dataset leakage data/dataset.csv                         # tail NaNs, label shuffle, single-feature IC, identity priors
aq lab new first --template multitask                       # models/first/model.py, config.toml, a shape test
aq lab train first --seeds 1,2,3
aq lab eval latest --book --html eval.html
```

The same steps from Python, offline on the bundled sample with the `linear` template:

```python
import tempfile
from pathlib import Path

from aether_quant import lab, samples

folder = Path(tempfile.mkdtemp()) / "mylab"
lab.init_lab(folder)
lab.build_dataset(samples.load_sample_prices(), features="core", targets=(5, 20)).to_csv(folder / "data" / "dataset.csv", index=False)
lab.new_model(folder, "ridge", "linear")
record = lab.train_run(folder, "ridge", seeds=[1], log=lambda line: None)
report = lab.evaluate_run(lab.find_run(folder, "latest"), lab_dir=folder)
print(record["trials_n"], lab.render_eval(report).splitlines()[1])   # N, then the out-of-sample IC with its HAC t and interval
```

`aq lab train` prints the run's out-of-sample IC, its spread across seeds, and N. The run folder `runs/<id>/` holds the frozen config, the fold metrics, the out-of-sample scores (`scores.csv`), the weights with their sha256 pins, the environment and the seeds.

## Templates

| Template | Network | Needs torch |
|---|---|---|
| `linear` | A ridge regression on the ranked features | No |
| `mlp` | `AetherNet`, the project's feed-forward network | Yes |
| `multitask` | `AetherNetMultiTaskHorizons`, the network the multitask trainer installs: rank and direction heads over several horizons | Yes |
| `tcn` | `AetherNetSequenceMultiTaskHorizons`, the causal convolutional network the sequence trainer installs | Yes |

The neural templates import the classes from `lab.architectures`, the same module the production trainers use. A lab model is therefore trained on exactly the code that production trains. Without torch (`pip install "aether-quant[train]"`), `aq lab train` says so and the `linear` template still runs.

A model's `config.toml` sets its features, target, loss, epochs, learning rate, patience and seeds. `lab.toml` holds the lab's defaults, and `--set train.lr=3e-4` overrides either for one run. The losses are the production ranking objectives: `mse`, `soft_spearman`, `listnet`, `ic_pearson`, `ls_sharpe`, `class_balanced` and `cost_aware`.

## Judging a model

```bash
aq lab runs                                                 # every run: status, IC with its seed spread, N
aq lab compare <run-a> <run-b> --baseline momentum_20       # leaderboard on common rows, HAC t and bootstrap CI against the best
aq lab explain latest                                       # out-of-sample permutation importance per feature and group
aq lab ablate latest                                        # retrain without each feature group
aq lab seeds latest --seeds 5                               # flags a model whose IC spread is over half its mean
aq lab sweep first --grid "train.lr=1e-3,3e-4 model.dropout=0.0,0.1" --max-trials 20
aq lab card latest                                          # MODEL_CARD.md from the run's own numbers
```

`aq lab eval` reports the IC by split and by year, the decay curve and half-life, the quintile spreads and the gap between fitted and out-of-sample IC. With `--book` it adds a cost-aware quintile book with its PSR and its deflated Sharpe at the lab's N. A sweep reports its probability of backtest overfitting (PBO) over the trials' out-of-sample return series.

## Exporting

```bash
aq lab export latest --name my-model                        # my-model.zip in the aq models format
aq models install my-model --from my-model.zip
aq models score my-model --csv data/closes.csv --out scores.csv
```

The zip holds the network as JSON weights, so scoring runs on the numpy forward pass with no torch. It also holds the feature list it reads (`lab_features.json`), the model card and a sha256 manifest that `install` checks. A linear run exports its coefficients.

## Signals and features without a network

The lab's statistics also judge a signal you computed elsewhere: a CSV of `date, ticker, score`.

```bash
aq signal check my_signal.csv                               # columns, duplicates, NaN and inf, thin dates
aq signal eval my_signal.csv --prices data/closes.csv --html signal.html
aq signal compare a.csv b.csv --prices data/closes.csv      # correlation, the IC left after the others, the combination
aq signal neutralize my_signal.csv --prices data/closes.csv # residual on rolling market betas
aq signal backtest my_signal.csv --prices data/closes.csv --top-n 3 --cost coinbase
aq features list                                            # the registry: name, group, lookback, what it is
aq features inspect ret_20 --prices data/closes.csv         # its IC by horizon, its decay, its overlap with the rest
aq overfit dsr --returns returns.csv --trials 50 --trial-variance 0.3
```

## Improving the project's own models (source checkout)

In a checkout of Aether Quant with its private `ml/` folder:

- `aq stack inspect` shows the installed models, their heads, windows, metrics and pins.
- `aq stack decay --by class` shows the rolling IC of the live blend by asset class and year, outside the holdout window.
- `aq stack lab-baseline --lab mylab` registers the installed blend as a lab run, so `aq lab compare` sets a lab model against production on the same rows.
- `aq lab train x --engine production --production-kind tcn` runs the real trainers on the project dataset and files their output as a lab run.
- `--project-ledger` counts the trials in the project's ledger as well, and seals the project's holdout window (`config.json`).
- `aq trials count` prints the project's N, and `aq trials dsr` prints the Sharpe a new candidate must beat.
