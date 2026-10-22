# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----
# Current objective: next phase (V6.5.0) — owner to write

The V6.4.x brief (leads L1-L12 and the open leads after V6.4.0) is closed; only the parked items below remain.

## Where V6.4.1 left things (details: `development/Changelog.md` "V6.4.0" / "V6.4.1", Problems #215-#230)
- Shipped `config.json` sha256 `bb695c741033bccfc5d4ba6fcf5360564b2a93969faeab517ed149f16569ac81` = BT5's config plus the default `core_only: false`; models unchanged since V5.8.0.
  README pinned to Lean run `backtests/2026-10-22_10-56-13` (BT5: +14.77% net, strategy +$3.9k, Sharpe +0.35 without risk-free, drawdown 4.33%).
- The offline rules' one adoption (10-session rebalance, 20-session hold, crypto core only) **lost $10.9k in Lean (BT6) and was reverted** by R-LEAN13 (#230).
  Lesson: the offline as-live simulator tracks Lean's daily returns at ~0.7 and cannot rank book cadences; a cadence or fill-path change needs a Lean run, not a rule on the simulator.
- Verified this phase: BT5 = BT4 order for order through 2026-09-30, R-L11 parity (444 of 444 calls, inside tolerance), the engine image (`/api/assets-status` 200), the CI view of the suite (3,796 passed, 0 failed, clean worktree on the PC).
- No Codespace exists or runs; **the owner's Codespace budget is spent**. Docker Desktop is closed (it holds ~1.8 GB of the PC's RAM; start it only for a Lean run or an image build).

## Open leads
1. **A paper period** — needs the IB paper account. Judge it with `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-10-22_10-56-13`; the bands are frozen in Problems #228 / `ml/evaluation/v640/paper_bands.json` (RUNBOOK "Paper period protocol"). With IB: #35, #38, #58, #59, #60, #61, #67, the IB part of #116, `aq paper-readiness`.
2. **Crypto live venue** (#192): Coinbase, or crypto off before live; with the IB items.
3. **Attribution of BT6** (optional, one Lean run each, ~2 h on the PC): book 10 / 20 alone, and `core_only` alone — to learn which of the two changes lost the $10.9k (R-LEAN13 judged them together). Not needed to ship anything; it is only worth a run if a faster book or core-only crypto is wanted again.
4. **Local dataset refresh** — `ml/datasets/full_dataset.csv` on the PC is the pre-refresh build (rows to 2026-09-30); the 2026-10-16 build (`v640_full_dataset.csv`) existed only on the training Codespace and was not pulled. Rebuild it with `python scripts/build_holdout_dataset.py --full-splits --write-split-files` when the PC has the memory (the Codespace needed ~8 GB), then re-run the offline blocks.
5. **Retrained candidate** `v640_mt_leg_s1..5` and the `v640_cand_*` leftovers live only on the stopped training Codespace's `ml/versions/` (not installed, not pulled); delete them with the next Codespace lifetime, never start one for that alone.
6. **Walk-forward blocks** carry no date (models unchanged since V5.8.0; `scripts/readme_freshness.py --allow WALKFORWARD ...`): retrain on a Codespace to refresh them, not before.

## README items that are not up to date (checked 2026-10-22; `python scripts/readme_freshness.py --since <date>` lists the blocks)
1. **Walk-forward blocks** (`AQ:WALKFORWARD`, `AQ:WALKFORWARD_FULL_STATS`): still the V5.8.0 retrain's 12 windows (net Sharpe -0.158, 4 of 12 positive) and undated. The models have not changed, so the numbers are right; the block has no date. Refresh = a retrain on a Codespace (budget spent), so it stays.
2. **Holdout block** (`Holdout (2025-07-01 to 2026-09-30)`, as-live +1.439): computed on the PC's pre-refresh dataset, which ends 2026-09-29; the config's holdout window already ends 2026-10-16. Fix = rebuild the dataset locally (lead 4), then `python scripts/holdout_report.py --models multitask sequence --book`.
3. **Overview window label** (`AQ:BACKTEST`): reads "2023-07-01 to 2026-10-18" although BT5 ends 2026-10-16 (the generator takes the chart's last date); cosmetic, fix in `generate_backtest_report.py` if wanted.
4. **Feature-permutation audit** (`aq evaluate --audit-features --permutation`): not re-run (stopped after 1 h on the PC; it does not read the book config, so V6.3's result stands). Re-run it with the dataset rebuild if the audit block should carry a V6.4 date.
5. **Run history table** (`AQ:BACKTEST_HISTORY`): lists the runs but carries no date and keeps the rejected BT6; correct, only undated.
6. **Offline blocks were computed on the pre-refresh local dataset** (rows to 2026-09-30, labels as of V6.1): as-live, evaluation, Monte Carlo, class IC, gate audit, sleeve / topology / RL research. The 1,296 new rows only resolve labels, so the backtest and validation numbers do not move; recomputing after the dataset rebuild would only extend the holdout.
7. **Research block** (`AQ:RESEARCH`) shows the V6.4.0 rules as the offline decided them (L5 10 / 20, L9 core-only adopted) with the R-LEAN13 row saying they were reverted; the as-live numbers in that table are the simulator's, which Lean did not confirm.

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 need a live/paper IB connection; `aq paper-readiness` needs the deployed Postgres and the paper broker config, so it belongs here too, and so does the paper period itself.

## Resume checklist
- Codespaces bill the owner's budget and **the budget is spent (2026-10-19)**: `gh codespace list` at session start and end (AGENTS.md rule 13); run everything that fits on the PC locally.
- **Lean on the PC works** (V6.4.1): `wsl --shutdown`, start Docker Desktop, wait ~10 minutes until `docker info` shows a server, put the frozen config over `config.json`, `python aq_cli.py backtest` (BT5 took 1 h 46 min, BT6 1 h 52 min), restore `config.json`, `python -m evaluation.lean_verdict` / `aq evaluate --lean-report --backtest-dir`; never run another heavy process during Initialize (90 s limit). `docker compose build engine` needs `BUILDX_BAKE_ENTITLEMENTS_FS=0` and takes ~2 hours (CUDA torch wheels); quit Docker Desktop afterwards (`Stop-Process 'Docker Desktop'`, `wsl --shutdown`).
- The dev PC (~270 MB free) runs the test buckets one at a time (`aq test --risk`, `--portfolio`, ...) and, with Docker closed, even CI's whole command in a clean worktree (`git worktree add` + copy the changed and new files + `PYTHONPATH=<worktree> python -m pytest tests -m "not lean_backtest"`: `scripts/clean_checkout_test.ps1` failed on a non-ASCII diff). Block waits with `python -c "import time; time.sleep(N)"` (<= 590 s); the Monitor tool's sleep does not wait.
- `gh codespace ssh -c` needs the real codespace name (`gh codespace list` column 1), not the display name; the ssh host is `cs.<name>.main`.
- Never push to the Codespace without `-CodeOnly` after a retrain; a `-CodeOnly` push also overwrites `config.json` - put a frozen run config back afterwards.
- Lean's `code/` folder holds no config.json: freeze a run's config at `ml/evaluation/run_configs/<run folder>.json` (`scripts/freeze_run_config.py`, `aq backtest` loop in `scripts/` notes).
- PowerShell 5.1 strips double quotes inside single-quoted ssh commands: put remote logic in a script file. The Bash tool unescapes backslashes in heredocs: write patch scripts with the Write tool.
- `config.json` is LF; `tests/` is not a package on CI: never `from tests.x import ...`; never `git checkout -- <file>` a file with uncommitted work.
- A data refresh appends (`scripts/data_append_refresh.py`) and is verified by `scripts/data_append_guard.py`; never rewrite the stored vintage.
