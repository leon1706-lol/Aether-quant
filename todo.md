# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: next phase — owner to write

V6.4.4 (Problems #251-#267) closed everything that needs no external account. Baseline: `config.json` sha256
`c9c8732d4b8eec1b893a29da55a64a016a24d19b749cb9957b3935db8733ff22` (BT11's book: V6.4.3's + the sector cap re-applied after the
dollar step), data to 2026-11-02, models from V5.8.0, README pinned to BT11 (`backtests/2026-11-03_16-26-39`). No alpha is
demonstrated (`aq evaluate --alpha-proof`: alpha t -0.07, deflated Sharpe 3.8% over 78 trials).

## Open (needs an external account — do not start without the owner)
1. **Paper period** (IB paper account): judge it with `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-11-03_16-26-39` against the bands in `ml/evaluation/v644/paper_bands.json` (RUNBOOK "Paper period protocol"). The IB items go with it: #38, #58, #59, #60, #61, #67, #116 (IB part), #147, `aq paper-readiness`.
2. **Crypto live venue** (#192): Coinbase, or crypto off before live; decided with the IB items.

## What V6.4.4 leaves for a next research phase (no external account needed; each needs a new pre-registered rule)
- The installed model's **sector-neutral head** is the best ranking on record (group-centred validation IC 0.055, #263) but S1 (using it as
  the live signal) lost on validation in V6.4.3; a rule that judges it on centred labels and in Lean is the obvious next trial.
- **Label design** (#259): percentile ranks in small groups carry a group-size offset; centring the training labels per (date, group)
  would remove it at the source (a retrain).
- The trend sleeve and ranked inputs exist default-off (`portfolio/trend_sleeve.py`, `features/cross_sectional_inputs.py`); neither has a live path.

## PC notes (not covered in AGENTS.md / `development/infrastructure.md`)
- Close ChatGPT / WhatsApp / Google Drive before heavy work (the 4 GB PC thrashes otherwise).
- Lean runs on a temporary DinD Codespace (`scripts/codespace_lean_run.ps1`; fixed for Windows PowerShell 5.1 and Docker 29 in V6.4.4); the
  training Codespace `aq-Training-Ground-Fixed` (4-core / 16 GB) is kept **stopped** - push before reusing it (local is the source of truth).
- The system Python's pip is broken: `.venv\Scripts\python.exe -m pip --python "C:\Program Files\Python314\python.exe" install --user --no-deps --no-build-isolation -e .`
- Data refresh without the 8 GB build: `scripts/data_append_refresh.py` (checked by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>`.
- `config.json` is LF; `tests/` is not a package on CI (never `from tests.x import ...`); never `git checkout -- <file>` with uncommitted work.
