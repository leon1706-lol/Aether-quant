# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Current objective: next phase (V6.4.0)


Tier 1 — model edge (do these first)
L1 — Equity rank skill only on engaged days

Question: When the rolling-IC gate does not veto, is rank_20d IC high enough to pay for top-6/bottom-6 costs?
Why: Mean strategy exposure ~0.17×; most rebalances vetoed; pooled IC ~0.05 does not clear a full book.
Method: On backtest + validation, split dates by gate (trade vs veto). Report rank IC, long-short spread, and as-live Sharpe only on trade dates. Same for holdout (report-only).
Bar: Engaged-day IC and as-live Sharpe must beat full-sample by a pre-set margin (e.g. +0.02 IC and +0.15 Sharpe) or the gate is hiding weakness, not protecting capital.

L2 — Multitask / sequence direction calibration

Question: Can direction heads become useful signals, or should they stay out of the book blend?
Why: Accuracy ~57–58%, multitask recall ~90%, weak log-loss; Lean book side accuracy ~51%.
Method: Reliability curves; temperature scaling / isotonic fit on validation only; thresholds by asset class; score as-live book with calibrated probs vs rank-only baseline.
Bar: Ship calibration only if as-live Sharpe improves on both val and backtest without raising turnover > X%. Else document “direction = diagnostic only.”

L3 — Legacy signal vs main MoE book

Question: Is legacy a better primary signal, a feature for the experts, or a permanent parallel sleeve?
Why: Attribution: legacy ~+$1.45k vs main_book ~+$1.04k on the same Lean run.
Method: (a) as-live with legacy off / half / full; (b) add legacy score as a feature and retrain rank heads (one controlled recipe); (c) IC of legacy vs rank_20d by class and regime.
Bar: Change budget only if combined book improves on both splits; pure retrain must beat seed yardstick (your ~0.034 IC bar).

L4 — Within-class equity ranking

Question: Does ranking only inside equities (or sectors) beat global cross-asset ranks for the equity risk bucket?
Why: Equity = ~88% of risk share but Sharpe ~0.23; class IC tables exist for a reason.
Method: rank_20d within equity only vs current global rank; as-live equity sleeve metrics; optional sector-neutral ranks.
Bar: Equity-only net Sharpe and engaged IC up on val + backtest; no large degradation on holdout report.


Tier 2 — structure (same models, different book)
L5 — Turnover vs IC tradeoff (hold / rebalance grid)

Question: What (rebalance, max hold) grid maximizes net Sharpe given IC ≈ 0.05?
Why: V6 slower book (20/40) helped; walk-forward net Sharpe negative in 8/12 windows with high turnover.
Method: Offline grid on calibrated/as-live sim: e.g. rebalance {10,20,40}, hold {20,40,60}; cost-aware; phase-median Sharpe (not one phase).
Bar: Beat current 20/40 on median and worst-quartile phase; then at most one Lean confirm.

L6 — Staggered book with a better range metric

Question: Can tranches reduce phase luck without widening dispersion the way S2 did?
Why: R-STAGGER / R-STAGGER2: S2 passed level margins but widened IQR / phase range.
Method: 2–3 tranches, partial adjust toward target; optimize/report IQR or p10 phase Sharpe, not only median.
Bar: Median ≥ baseline and phase IQR ≤ baseline; else no ship (same discipline as V6.3).

L7 — Kill-switch design (not fine-tune)

Question: Should lock use strategy equity only, longer window, or hysteresis so one borderline order cannot flip 14 → 46 lock days?
Why: V6.2 NAV/sweep interaction; R-KILL rejected “lock less often” as unsafe.
Method: Replay on Lean order stream + offline: window {60,120}, floor, release rule; count lock-days vs max DD vs net.
Bar: Prefer fewer false locks (lock days that precede strong forward book returns) without increasing 95% DD above a fixed cap.


Tier 3 — experts & stack (only after L1–L4 signals)
L8 — Expert-level contribution audit

Question: Which of bullish / bearish / sideways / vol experts improve rank IC on engaged equity days?
Why: Attribution is by class/component, not by expert; MoE may be carrying dead experts.
Method: aq evaluate --audit-heads + ablate one expert at a time (gate fixed); IC and as-live delta.
Bar: Drop or down-weight experts with ≤ 0 IC contribution on engaged days on both splits.

L9 — Crypto_core vs graduates

Question: Is crypto PnL a repeatable rank effect or a few lucky fills?
Why: crypto_core +$3.9k on 13 fills; graduates +$85 on $141 fees.
Method: Bootstrap by trade; leave-one-name-out; rank IC for crypto only; graduates at 0 vs current cap.
Bar: Keep graduates only if they add Sharpe on val+backtest; else core-only.

L10 — Residual rank head

Question: Should residual_rank_20d (WF IC ~0.024) stay demoted or return as a blend component?
Why: Historically demoted; still shows positive WF IC.
Method: Blend grid vs rank_20d only on engaged days; factor exposure check.
Bar: Net as-live improvement both splits; no large factor-bet increase.


Tier 4 — measurement (supports research, not alpha itself)
L11 — Log book-call probabilities in Lean

Why: Classification table has n/a log-loss for Lean book calls.
Method: Log p(side) or rank score per member decision; reuse offline classification pipeline.
Bar: Parity of Lean vs offline classification metrics within a fixed tolerance.

L12 — Paper period protocol

Question: Does engaged-day behavior match Lean on a forward window?
Why: Every recent rule says paper is the honest test.
Method: Fixed config, fixed checklist (fills, veto rate, exposure, strategy vs sweep PnL), minimum duration/N rebalances pre-registered.
Bar: No live capital; success = metrics inside pre-set bands vs BT4, not “make money.”


Suggested research sequence








































Week focusLeadsOutput1L1, L8Engaged-day IC + expert ablation report2L2, L3Calibration decision + legacy decision memo3L4, L5Rank geometry + turnover grid4L6, L7Structure rules only if L1 shows enough conditional edgeParallelL11, L12Instrumentation + paper protocolLaterL9, L10Crypto / residual once equity baseline is clear

Explicit non-leads (from the same stats)

Forex trading experts (sleeve dropped; IC negative historically).
RL sizing (repeated ~0 gain).
Bond sleeve expansion (Lean losses at higher caps).
Retuning gates before R-CAL passes or L1 proves engaged-day skill.
Chasing headline Sharpe that includes T-bill carry.


One-page “definition of done” for a research lead

Pre-register metric + splits + ship bar in Problems or todo.
Run offline on as-live (and engaged-day subset where relevant).
Report nulls as closures.
At most one Lean confirm if a rule would ship.
Live capital stays zero until L12-style paper says otherwise.


-----

## Where V6.3.0 left things (details: `development/Changelog.md` "V6.3.0", Problems #206-#214)
- Shipped `config.json` sha256 `e78dc29cc42503da4fa3bba0b5ccc8436e23c7c4a2fa89491bfd467e47d268d1`; models unchanged since V5.8.0.
  README pinned to Lean run `backtests/2026-10-18_12-55-00` (BT4 = V6.2's BT2 order for order).
- The local engine image is stale until Docker Desktop starts on the PC (`aq docker build`); the image itself is verified on a
  DinD Codespace (#214).
- Both Codespaces are off: the training Codespace is Shutdown, no DinD Codespace exists.

## Open leads
1. **A paper period**: the only out-of-sample test left; the staggered book S2 is the strongest offline candidate (#212).
2. **Crypto IC dedupe**: revisit with more data, not by loosening the rule (#201).
3. **Crypto live venue** (#192): Coinbase, or crypto off before live; with the IB items.

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 need a live/paper IB connection; `aq paper-readiness` needs the deployed Postgres and the paper broker config, so it belongs here too.

## Resume checklist
- Codespaces bill the owner's budget: `gh codespace list` at session start and end, stop/delete anything not in active use (AGENTS.md rule 13).
- The dev PC (~270 MB free) cannot run the full suite or offline research: run them on the training Codespace (`scripts/codespace_run_tests.sh`, `scripts/codespace_clean_checkout_test.sh`).
- Lean runs: `scripts/codespace_lean_run.ps1` on a temporary DinD Codespace, then `aq evaluate --lean-report --backtest-dir backtests/<run>`.
- Never push to the Codespace without `-CodeOnly` after a retrain (a full push overwrites the remote `ml/`); a `-CodeOnly` push also overwrites `config.json` - put a frozen run config back afterwards.
- A Codespace job stops when the Codespace idles out (~30 minutes without ssh): check by ssh every <= 15 minutes, and resume with `RESUME=1`.
- PowerShell 5.1 strips double quotes inside single-quoted ssh commands: put remote logic in a script file. `pgrep -f` through ssh matches its own command line.
- Files written from Python on Windows get CRLF: `sed -i 's/\r$//'` a `.sh` before running it on the Codespace.
- `tests/` is not a package on CI or the Codespace: never `from tests.x import ...`.
- Lean's `code/` folder holds no config.json: freeze a run's config at `ml/evaluation/run_configs/<run folder>.json`.
- Never `git checkout -- <file>` a file with uncommitted work.
