# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: next phase (V6.5.0) — owner to write

Everything that needs no external account is closed (V6.4.3, Problems #239-#250). Baseline: `config.json` sha256
`bb695c741033bccfc5d4ba6fcf5360564b2a93969faeab517ed149f16569ac81` (BT5's book), models from V5.8.0, README pinned to BT5
(`backtests/2026-10-22_10-56-13`).

## Open (needs an external account — do not start without the owner)
1. **Paper period** (IB paper account): judge it with `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-10-22_10-56-13` against the bands frozen in #228 (RUNBOOK "Paper period protocol"). The IB items go with it: #38, #58, #59, #60, #61, #67, #116 (IB part), #147, `aq paper-readiness`.
2. **Crypto live venue** (#192): Coinbase, or crypto off before live; decided with the IB items.

## Owner calls
- **Sector cap after the dollar step** (#241): `phase_v2.portfolio_book.neutrality.reapply_sector_cap_after_dollar_neutral` (default `false`). Today 5 of BT5's 38 rebalances end with a sector up to 1.45 pp over its cap; turning it on is a behaviour change that needs a Lean run.
- **Retrain** (#247): start from per-date cross-sectional inputs and `phase1.target.ranking.beta_estimation: "asof"`; it must beat the asset-identity (0.021) and asset-class (0.066) validation IC before any as-live or Lean test. Training host is the owner's call (no Codespace budget). The walk-forward refreshes only with a retrain.

## PC notes (not covered in AGENTS.md / `development/infrastructure.md`)
- Close ChatGPT / WhatsApp / Google Drive before heavy work (the 4 GB PC thrashes otherwise).
- Lean on the PC: start Docker (WSL `CreateVm` fix in infrastructure.md), wait ~10 min, put the frozen config over `config.json`, `python aq_cli.py backtest`, copy the frozen config to `ml/evaluation/run_configs/<run folder>.json`, restore `config.json`, re-pin the README (`aq evaluate --lean-report --backtest-dir backtests/<shipped run>`), quit Docker (`Stop-Process` every `com.docker.*`, `wsl --shutdown`).
- The system Python's pip is broken: `.venv\Scripts\python.exe -m pip --python "C:\Program Files\Python314\python.exe" install --user --no-deps --no-build-isolation -e .`
- Data refresh without the 8 GB build: `scripts/data_append_refresh.py` (checked by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>`.
- `config.json` is LF; `tests/` is not a package on CI (never `from tests.x import ...`); never `git checkout -- <file>` with uncommitted work.
