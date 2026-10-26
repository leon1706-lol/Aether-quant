# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----
# Current objective: next phase (V6.5.0) — owner to write

V6.4.2 closed every lead that does not need an external account; only the IB / venue items below remain.

## Where V6.4.2 left things (details: `development/Changelog.md` "V6.4.2", Problems #231-#238)
- Shipped `config.json` unchanged: sha256 `bb695c741033bccfc5d4ba6fcf5360564b2a93969faeab517ed149f16569ac81` (BT5's book); models unchanged since V5.8.0. README pinned to BT5 (`backtests/2026-10-22_10-56-13`).
- BT6 attributed on Lean (R-LEAN14, #237): the 10 / 20 book alone (BT7) cost the strategy $8.8k; core-only crypto alone (BT8) earned $2.2k more (Sharpe +0.46 against +0.35) but drew down 6.0% against 4.3%, so neither was adopted. If core-only crypto is wanted anyway, it is an owner call on the drawdown, not a rule result.
- `ml/datasets/full_dataset.csv` carries the holdout to 2026-10-16 (spliced on the PC, `scripts/splice_holdout_dataset.py`); every offline README block was recomputed on it.
- Lean on the PC: `lean.json` `algorithm-creation-timeout: 600` ended the 90 s ceiling; a run takes 6-13 h on the 4 GB PC when other apps are open (BT5 took 1 h 46 min with the PC idle). Recipe and the WSL-VM workaround: `development/infrastructure.md`.

## Open (needs an external account — do not start without the owner)
1. **A paper period** — needs the IB paper account. Judge it with `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-10-22_10-56-13`; bands frozen in Problems #228 / `ml/evaluation/v640/paper_bands.json` (RUNBOOK "Paper period protocol"). With IB: #35, #38, #58, #59, #60, #61, #67, the IB part of #116, #147, `aq paper-readiness`.
2. **Crypto live venue** (#192): Coinbase, or crypto off before live; decided with the IB items (owner, 2026-10-23).

## Owner calls
- **Stopped training Codespace** (`aq-sshd-only-test-7v49pjgx6jg43r7g6`): it still bills storage and holds only the uninstalled `v640_mt_leg_s1..5` / `v640_cand_*` candidates and an old dataset. Delete it (`gh codespace delete -c aq-sshd-only-test-7v49pjgx6jg43r7g6`) or keep it for the next retrain; there is no Codespace budget to start it for a cleanup.
- **Walk-forward**: refreshes only with a retrain (owner, 2026-10-23: none while models and data are unchanged); the README block now carries its run date and is checked against the installed models.

## Resume checklist
- No Codespace budget: `gh codespace list` at session start and end (AGENTS.md rule 13); everything runs on the PC.
- Lean on the PC: close other apps (ChatGPT, WhatsApp, Google Drive held ~700 MB), boot the `docker-desktop` WSL VM by hand if Docker reports `CreateVm/ERROR_TIMEOUT`, start Docker Desktop, wait ~10 min, put the frozen config over `config.json`, `python aq_cli.py backtest`, copy the frozen config to `ml/evaluation/run_configs/<run folder>.json`, restore `config.json`, re-pin the README (`aq evaluate --lean-report --backtest-dir backtests/<shipped run>`), quit Docker (`Stop-Process` every `com.docker.*`, `wsl --shutdown`).
- The dev PC runs the test buckets one at a time (`aq test --risk`, `--portfolio`, ...); the full CI command runs in a clean `git worktree` with `PYTHONPATH=<worktree>`. Block waits with `python -c "import time; time.sleep(N)"` (<= 590 s).
- A data refresh appends (`scripts/data_append_refresh.py`, verified by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>` refresh the dataset without the 8 GB full build.
- `config.json` is LF; `tests/` is not a package on CI: never `from tests.x import ...`; never `git checkout -- <file>` a file with uncommitted work.
