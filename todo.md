# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----
# Current objective: next phase (V6.5.0) — owner to write

The V6.4.0 brief (leads L1-L12) is closed or parked below; nothing else is queued.

## Where V6.4.0 left things (details: `development/Changelog.md` "V6.4.0", Problems #215-#228)
- Shipped `config.json` sha256 `1998a98f8177d7b8693521c4fffffeb8c78bc32d3db660255706548f9043733a`; models unchanged since V5.8.0.
  README still pinned to Lean run `backtests/2026-10-18_12-55-00` (BT4, the V6.3 config).
- **Adopted offline by pre-registered rule, NOT confirmed in Lean:** `portfolio_book.rebalance_every_bars` 10 and `exits.max_holding_bars` 20
  (R-L5, #221), `class_weight_caps.crypto.core_only` true (R-L9, #225). The frozen configs: `ml/evaluation/run_configs/v640_bt5.json`
  (BT4's config + book-call probability logging + the Lean window to 2026-10-16) and `v640_bt6.json` (BT5 + the three adopted keys).
- Closed by rule with nothing adopted: R-DEDUPE2 (#216, closes #201), L1 gate skill (#217: the gate hides weakness), L2 direction (#218: diagnostic only),
  L3 legacy budget and legacy-input retrain (#219), L4 within-class ranks (#220), L6 staggered book and L7 kill-switch confirmation (#222, #223: closed by
  the L1 precondition), L8 experts (#224), L10 residual head (#226). #214 (stale local engine image) closes as moot: the image of record is the DinD engine check.
- The training Codespace is stopped (06:18-14:11 UTC today); no DinD Codespace exists. **The owner's Codespace budget is spent: do not start one.**

## Open leads (all of them need a Codespace or the IB paper account; parked, not deferred by choice)
1. **Lean confirm of the V6.4 book (BT6)** — one run of `v640_bt6.json` on a temporary DinD Codespace (`scripts/codespace_lean_run.ps1`), then
   `aq evaluate --lean-report --backtest-dir backtests/<run>`. R-LEAN13 keeps it iff strategy-ex-sweep Sharpe (no risk-free) >= BT4's - 0.10,
   max drawdown <= BT4's + 1 pp and the engine log (`log.txt`) tears down clean; otherwise revert the three keys to BT5's values
   (`python scripts/freeze_run_config.py` and the Changelog's Freeze bullet say which) and write the reason in Problems #221 / #225.
2. **BT5 (R-L11 parity)** — a run of `v640_bt5.json` should equal BT4 order for order through 2026-09-30 and gives the Lean book-call log-loss;
   then `aq evaluate --classification-parity --backtest-dir backtests/<run>` (tolerance: |accuracy delta|, |neg log-loss delta| <= 0.01, median |dp| <= 0.005).
   Both runs fit one DinD lifetime (AGENTS.md rule 13).
3. **Rebuild the paper bands from the confirmed run** — `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/<BT6>`, then freeze the
   bands in Problems #228 (RUNBOOK "Paper period protocol"). The paper run itself needs an IB paper connection (IB items below).
4. **README blocks not recomputed on the final config** (no Codespace): the sleeve / topology / RL research rows if the local run did not reach them,
   `--audit-features --permutation`, the walk-forward block (models unchanged) — `python scripts/readme_freshness.py` lists every stale block.
5. **Engine image on the deploy host** — build it there before any paper deploy (RUNBOOK step 2); the dev PC's Docker does not start.
6. **Full suite + clean checkout on CI's Python 3.11** — every test bucket passes on the PC one at a time; `scripts/codespace_run_tests.sh` and
   `scripts/codespace_clean_checkout_test.sh` (or `clean_checkout_test.ps1` locally if memory allows) are the CI view.
7. **Crypto live venue** (#192): Coinbase, or crypto off before live; with the IB items.
8. **Retrained candidate** `v640_mt_leg_s1..5` lives only on the training Codespace (`ml/versions/`, not installed, not pulled); delete it with the next
   Codespace lifetime or never start one for that.

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 need a live/paper IB connection; `aq paper-readiness` needs the deployed Postgres and the paper broker config, so it belongs here too, and so does the paper period itself.

## Resume checklist
- Codespaces bill the owner's budget and **the budget is spent (2026-10-19)**: `gh codespace list` at session start and end (AGENTS.md rule 13); run everything that fits on the PC locally.
- The dev PC (~270 MB free) runs the test buckets one at a time (`aq test --risk`, `--portfolio`, `--evaluation`, ...), not the whole suite in one process; background shells are killed by the memory reaper, so block on `python -c "import time; time.sleep(N)"` for waits.
- `gh codespace ssh -c` needs the real codespace name (`gh codespace list` column 1), not the display name; the ssh host is `cs.<name>.main`.
- Never push to the Codespace without `-CodeOnly` after a retrain (a full push overwrites the remote `ml/`); a `-CodeOnly` push also overwrites `config.json` - put a frozen run config back afterwards.
- Lean's `code/` folder holds no config.json: freeze a run's config at `ml/evaluation/run_configs/<run folder>.json` (`scripts/freeze_run_config.py`).
- PowerShell 5.1 strips double quotes inside single-quoted ssh commands: put remote logic in a script file. The Bash tool unescapes backslashes in heredocs: write patch scripts with the Write tool.
- Files written from Python on Windows get CRLF: `sed -i 's/\r$//'` a `.sh` before running it on the Codespace; `config.json` is LF.
- `tests/` is not a package on CI or the Codespace: never `from tests.x import ...`.
- Never `git checkout -- <file>` a file with uncommitted work.
- A data refresh appends (`scripts/data_append_refresh.py`) and is verified by `scripts/data_append_guard.py`; never rewrite the stored vintage.
