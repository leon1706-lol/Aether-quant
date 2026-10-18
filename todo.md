# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Current objective: next phase (V6.3.0)

## Owner brief (V6.3.0)

-the first objective is to conriune chasing and closing the open leads in problem and tod.md

- I also want to rework te backtest result section iif readme:
- It should now be caled Backtest statistics
- It should have these makjorsubpoints: 
- general characteristics, performance, runs/drawdowns, inplementation shortfall, return/risk efficency, clasification score, attribution
- under these maor subpoints it should have these subpoints:
- general characteristicks: time range, average aum, capacety, laverage, maximum dolar possition, ratio of longs/shorts, frequency of bets, average holding periode, anualized turnover, correlation of underlining
- performance: Pnl, pnl from long positions, aulized rate of return, Hit ratio, Average return from its, average return from misses, time weighted returns
- runs: Herfindahl-Hirschman Index on positive retunrns, Herfindahl-Hirschman Index  on negative returns, Herfindahl-Hirschman Index on time between bets, 95-percentile DD, 95 percentile Tuw
- implementation shortfall: roker fees per turnover, Average slipage per turnover, dollar performance per trunover, return of execution costs
- Efficenccy: Anualized sharp ratio, Informational ratio, propebalistic sharp ratio, deflated sharp rartio
- clasification scores: accuracy, precison, recall,F1,negative log-loss
-  attribution: compute the risk and return of each class of assets
- you hsould also put the currently existing metrics inside the new classes where they fit and if needed create an new major sub point
- the main Table of content shpuld contain the new  üoints so you cna get the re with one click
- make all these stats like the old ones autoupdateablle with either aq evaluate comand or automaticly after an lean backtest and ddisplay everyhting in tables 
- keep the text minimal and bloat free and clean too read

Also (2026-10-18): plan an improved performance, a Docker image for use, and a full recapture at the end so the whole
backtest section is current; write AGENTS.md rules that Codespaces are off when not directly used (budget). "Full end to
end implementation without deferring anything; use the Codespace as conservatively as possible, the monthly budget is
already 90% used."

## Owner decisions (2026-10-18)
- **D1** at most 2 Lean runs: BT4 (baseline = BT2's config, the open V6.2 request) and BT5 (final; skipped when no rule
  changes the shipped config). Both in ONE DinD Codespace lifetime.
- **D2** a pre-registered rule that passes ships by rule.
- **D3** no model retrain (walk-forward block keeps its run, says so).
- **D4** delete leftovers at the end (after a safety copy of the installed `ml/`).
- **D5** AGENTS.md Codespace on/off budget rules. Budget 90% used: offline research runs LOCALLY, not on a Codespace.

Full plan: `C:\Users\Blackhead\.claude\plans\please-now-go-through-joyful-llama.md`. Tick items as they finish.

## Work items
- [x] **W1** AGENTS.md rule 13 (Codespaces on only while used) + infrastructure.md mirror and stale-text fix (lead 5 decided:
      Lean on a DinD Codespace); `scripts/codespace_lean_dind.sh` + `scripts/codespace_lean_run.ps1` + static test.
- [x] **W2** #198 CI check (green on 5d5ae86); one Lean-run resolver for every `aq evaluate` Lean flag (honours the README pin); BIL as class
      `cash_sweep` in audit/attribution; Problems header count, development/README legend.
- [x] **W3** `evaluation/backtest_statistics.py` (AFML ch.14 set), trial registry for the deflated Sharpe, classification
      scores, README "Backtest Statistics" restructure + TOC, `aq evaluate --backtest-stats` / `--lean-report`, `aq backtest`
      runs the report automatically; first render on BT2.
- [x] **W4** `scripts/v630_research.py` on the training Codespace (`codespace_session_v630.sh`; the PC has ~270 MB free):
      R-CAL3 branch B (R-GATE3 skipped), R-KILL branch C (KS0 stays), R-STAGGER2 not adopted (IQR 0.50 -> 0.67). Ship list empty.
- [x] **W5/W6** BT4 `backtests/2026-10-18_12-55-00` = BT2 order for order (1,596 events); BT5 not run (nothing to ship).
- [x] **W7** engine image built and `/api/assets-status` 200 (now with `cash_sweep`) on the DinD Codespace; the PC's Docker
      Desktop still cannot start, so the LOCAL image is still stale (owner item below).
- [x] **W8** recapture: `--lean-report` on BT4 (pinned), every offline block on the shipped config, `readme_freshness.py` 0 stale
      (walk-forward kept, no retrain); Problems #206-#214, Changelog V6.3.0, docs, D4 cleanup, vault, memory.

## V6.3.0 outcome (COMPLETE 2026-10-18, nothing committed)
- README "Backtest Statistics" live: 7 AFML sections, auto-updated by `aq backtest` / `aq evaluate --lean-report`.
- Rules adopted nothing; shipped config = V6.2's + `risk.kill_switch.release_rolling_sharpe: null`
  (sha256 `e78dc29cc42503da4fa3bba0b5ccc8436e23c7c4a2fa89491bfd467e47d268d1`); models unchanged since V5.8.0.
- Suite: Codespace 3,692 passed (+1 Codespace-only docs-link miss), clean checkout 3,666 passed / 0 failed; ruff clean.
- Codespaces: training 11:37-14:34 UTC (stopped), DinD 12:30-13:51 UTC (deleted); both listed in the Changelog.

## Open for the owner
- Commit? (all V6.3.0 files uncommitted). The local engine image is stale until Docker Desktop starts on the PC
  (`aq docker build`; the image itself is verified on the DinD host, Problems #214).
- Leads still open: 2 (crypto dedupe, needs more data), 4 (paper period; S2 is the strongest candidate), 6 (crypto venue).

## Starting point
- Shipped `config.json` sha256 `58a0fd40bb48e720151932e9d571f4aa710ae9d2c454a96f22b903837a3fb77d`; installed models unchanged
  since V5.8.0 (`ml/evaluation/v620/manifest_bt1.txt`). Pinned README run `backtests/2026-10-17_21-39-55` (BT2).
- To delete at the end (D4): `data_v580_staging/`, `ml/datasets/v580_active_dataset.csv`, `ml/datasets/v600_rank60_dataset.csv`,
  `ml/versions/v600cs20261015_*`; on the Codespace `ml/versions/v610_*`, `v620_*`, `v620_cand_*`; DinD Codespace(s).

## Leads (status for V6.3.0)
1. **Staggered book S2** -> R-STAGGER2 (W4).
2. **Crypto IC dedupe**: stays open, no new data (the rule is not loosened).
3. **Kill switch at its floor** (#200, #205) -> R-KILL (W4).
4. **Alpha unproven out of sample**: a paper period (IB).
5. **Lean host**: decided, DinD Codespace (W1).
6. **Crypto live venue** (#192): with the IB items.

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 need a live/paper IB connection; `aq paper-readiness` needs the deployed Postgres and the paper broker config, so it belongs here too.

## Resume checklist
- Codespaces bill the owner's budget: `gh codespace list` at session start and end, stop/delete anything not in active use (AGENTS.md rule 13).
- Never push to the Codespace without `-CodeOnly` after a retrain (a full push overwrites the remote `ml/`); a `-CodeOnly` push also overwrites `config.json` - put a frozen run config back afterwards.
- A Codespace job stops when the Codespace idles out (~30 minutes without ssh): check by ssh every <= 15 minutes, and resume with `RESUME=1`. `pgrep -f` through ssh matches its own command line.
- Files written from Python on Windows get CRLF: `sed -i 's/\r$//'` a `.sh` before running it on the Codespace.
- `tests/` is not a package on CI or the Codespace: never `from tests.x import ...`.
- Lean's `code/` folder holds no config.json: freeze a run's config at `ml/evaluation/run_configs/<run folder>.json`.
- Never `git checkout -- <file>` a file with uncommitted work.
- Lean on the DinD Codespace: Docker's data root on `/tmp` before building the ~20 GB image; `lean backtest . --image aether-quant-lean:17900` needs no login.
- Long bash heredocs with `\n` escapes or quotes break through the tool shell: write the text to a file first.
