# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: next phase — owner to write

V6.5.0 (Problems #268-#282) did not reach Lean Sharpe 1 or a verified edge. Baseline: `config.json` sha256
`38a24ffd7f1bea292a996d7dfcaf89a1b0a3d2c0a96d2efab114630e2c309c61`, a long-only crypto trend sleeve installed as "improved, not verified" by rule R-LEAN19 and kept by the owner (2026-11-05),
data to 2026-11-02, README pinned to `backtests/2026-11-04_18-10-49`. Lean Sharpe 0.63, alpha t 0.13, strategy Sharpe 0.06 since mid-2025.

## Owner calls
1. **Docker rebuild:** the owner will do it later; it is needed before any paper or live deploy.
2. **AetherVault:** the owner commits its fixes (Probleme.md #189-#194) manually. A release is what unblocks pinning `av` in the Docker image (#271), so settle it before that rebuild.
3. **Pre-2013 data (`data_pre2013/`):** spent once on multi-asset trend (Sharpe 0.33, alpha t 0.83, 6 of 20 placebos as good). Nothing else has been scored on it, but no crypto sleeve can use it.

## Open (needs time or an external account)
- **Forward check** (RUNBOOK "Forward check"): sessions after 2026-11-02 are unseen by everything; judge at 60 sessions.
- **Paper period** (IB paper account): `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-11-04_18-10-49`. The IB items go with it: #38 (`main.py`'s own option order), #58, #59, #60, #61, #116 (IB part), #147, `aq paper-readiness`. A live run also needs a velocity-control decision (#278) and `scripts/daily_target_weights.py` before each open.
- **Crypto live venue** (#192): Coinbase, or crypto off, which with the shipped sleeve means no book.

## PC notes (not covered in AGENTS.md / `development/infrastructure.md`)
- Close ChatGPT / WhatsApp / Google Drive before heavy work (the 4 GB PC thrashes otherwise).
- Lean runs on a temporary DinD Codespace; the training Codespace `aq-Training-Ground-Fixed` (4-core / 16 GB) is kept **stopped** - push before reusing it (local is the source of truth). Its `ml/versions/` holds the V6.5.0 walk-forward (`ml/evaluation/v650/walkforward_run_id`).
- The system Python's pip is broken: `.venv\Scripts\python.exe -m pip --python "C:\Program Files\Python314\python.exe" install --user --no-deps --no-build-isolation -e .`
- Data refresh without the 8 GB build: `scripts/data_append_refresh.py` (checked by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>`.
- `config.json` is LF; `tests/` is not a package on CI (never `from tests.x import ...`); never `git checkout -- <file>` with uncommitted work.
