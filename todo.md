# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Current objective: next phase (V6.3.0)

_(write the objective here)_

## What V6.2.0 decided (nothing committed yet; see `development/Changelog.md` "V6.2.0")
- **Lean Sharpe -1.673 -> +0.082** on the shipped code (BT2 = BT3, +16.85%, drawdown 4.30%): Lean's risk-free file is refreshed from FRED (5.49% -> 4.69% average), Lean annualises at 365 days (`runtime.trading_days_per_year`), and idle cash sits in BIL (`phase_v2.cash_sweep`, +$10.7k carry). On V6.1's basis the same run is -0.776. The carry is not alpha: ex-sweep the strategy made $6.1k (Sharpe +0.54 without the risk-free rate), V6.1 $5.3k.
- **Rules adopted nothing:** R-DEDUPE (crypto counted once: validation +0.58, backtest -0.09), R-STAGGER (S2 two tranches: +0.26 / +0.52 and every margin passed, but the phase range widened), R-MODEL10 (label noise and the 17-feature subset lose; nothing beats the resampled-ensemble yardstick 0.034). Legacy L2 declined.
- **CI:** the red test is fixed and a clean-checkout run is part of the wrap-up (`scripts/clean_checkout_test.ps1`); the Linux jobs pin ubuntu-24.04.
- **Hosts:** Docker Desktop could not start on the dev PC (WSL VM timeout at ~400 MB free); the three Lean runs ran on a temporary Docker-in-Docker Codespace (~10 min a run, clean teardown: #104 is the PC). `development/infrastructure.md` "V6.2.0" has the recipe.

## Starting point
- Shipped `config.json` sha256 `58a0fd40bb48e720151932e9d571f4aa710ae9d2c454a96f22b903837a3fb77d` (window override null, sweep on, 365 days); installed models unchanged since V5.8.0 (`ml/evaluation/v620/manifest_bt1.txt`). Lean runs: `backtests/2026-10-17_19-10-42` (BT1), `_19-45-55` (BT3), `_21-39-55` (BT2, the README's pinned run).
- Not approved for deletion and still on disk: `data_v580_staging/`, `ml/datasets/v580_active_dataset.csv`, `ml/datasets/v600_rank60_dataset.csv`, `ml/versions/v600cs20261015_*`; on the Codespace `ml/versions/v610_*`, `v620_*`, `v620_cand_*`.
- Docker Desktop is off; the training Codespace is Shutdown; the DinD Codespace was deleted.

## Open from V6.2.0 (not done yet)
- **Rebuild the engine image locally:** the live path changed (BIL sweep, strategy-only risk value, per-model inputs, `trading_days_per_year`), so `aether-quant-engine:latest` is stale for any paper/live deploy. Docker Desktop could not start on the dev PC on 2026-10-17/18 (WSL `CreateVm/ERROR_TIMEOUT` at ~350-450 MB free): reboot (or free memory), start Docker Desktop, then `aq docker build`, `aq docker up` and check `GET /api/assets-status` returns 200 with the `cash_sweep` settings.
- **Extra Lean run BT4 (owner request) not run:** the shipped config with only the window override (`ml/evaluation/v620/config_bt4.json`, byte-identical to BT2's) on a Docker-in-Docker Codespace; the project push to `aq-lean-dind2-9749jgpxrgw537544` was stopped by the PC's memory pressure. That Codespace still exists (idle-stops after 60 minutes): finish the push, build the Lean image there (`development/infrastructure.md` "V6.2.0"), run, pull, write up (expected = BT2), then delete it.

## Leads for the next objective
1. **Staggered book S2** passed every R-STAGGER margin (+0.26 validation, +0.52 backtest median Sharpe, 80% / 70% of phases) and failed only the phase-range clause; the live tranche path is not built. The honest next test is out of sample (paper), or a pre-registered re-look with a range measure that does not reward a single lucky phase.
2. **Crypto IC dedupe** is far more robust on validation (worst phase -2.04 -> -0.43, every phase better) at -0.09 on backtest; revisit with more data, not by loosening the rule.
3. **Kill switch at its floor:** one borderline order moves the whole lock path (46 against 14 lock dates on identical rebalance decisions, #200, #205). The kill switch's input window and floor are a design question, not a tuning one.
4. **Alpha is still unproven out of sample;** the retrained candidates stay inside seed noise. A paper period is the test.
5. **Lean host:** the dev PC can no longer run Docker reliably; decide whether Lean runs move to a Codespace permanently (the DinD recipe works, ~10 min a run) or the PC gets more memory.
6. **Crypto live venue:** unchanged (Coinbase or switch crypto off before live; with the IB items).

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 need a live/paper IB connection; `aq paper-readiness` needs the deployed Postgres and the paper broker config, so it belongs here too.

## Resume checklist
- Never push to the Codespace without `-CodeOnly` after a retrain (a full push overwrites the remote `ml/`); a `-CodeOnly` push also overwrites `config.json` - put a frozen run config back afterwards.
- A Codespace job stops when the Codespace idles out (~30 minutes without ssh): hold `scripts/codespace_keepalive.sh` open, or check by ssh every <= 15 minutes, and resume with `RESUME=1`. `pgrep -f` through ssh matches its own command line.
- Files written from Python on Windows get CRLF: `sed -i 's/\r$//'` a `.sh` before running it on the Codespace.
- `tests/` is not a package on CI or the Codespace: never `from tests.x import ...`.
- Lean's `code/` folder holds no config.json: freeze a run's config at `ml/evaluation/run_configs/<run folder>.json`.
- Never `git checkout -- <file>` a file with uncommitted work.
- Lean on the DinD Codespace: Docker's data root on `/tmp` before building the ~20 GB image; `lean backtest . --image aether-quant-lean:17900` needs no login.
- Long bash heredocs with `\n` escapes or quotes break through the tool shell: write the text to a file first.
