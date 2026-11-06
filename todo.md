# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: next phase — owner to write

V6.6.0 (Problems #283-#309) did not verify an edge: zero of 28 pre-registered trials on never-read data survived selection. Nothing was installed, so the book is still the V6.5.0 long-only crypto sleeve, `config.json` sha `933a3724…` (the sleeve of `38a24ffd…` plus `vault.min_version` and `target_weights.velocity_decision`), README pinned to `backtests/2026-11-04_18-10-49`, which BT24 equals order for order.

## Owner calls
1. **Keep trading the crypto sleeve?** By the rule you set it stays, but its rule scored Sharpe -0.06 on never-read coins (2024 on: -0.45, alpha t -1.94; #301). Paper only until you say otherwise.
2. **Crypto venue (#192):** Coinbase direct, ETFs for BTC and ETH only, or crypto off (`ml/evaluation/v660/venue_study.json`). With the shipped sleeve, off means no book.
3. **QuantConnect terms:** its API still asks for the latest terms to be accepted, which only you can do. Nothing is blocked now; it's needed only if a later candidate reaches the survivorship check.

## Unspent evidence
- **Equity holdouts V1, V2, V3 and P (`evaluation/research_cells.py`) stay unread:** no candidate was frozen. Side-B names and 2019-2026 are real holdout evidence for one future frozen candidate. Don't score anything on them without a freeze.
- **Crypto side B** has been read once, by the installed rule only.

## Open (needs time or an external account)
- **Forward ledger (Problems #299):** one row a session on branch `forward-ledger`. `aq evaluate --forward-ledger`: judge at 60 sessions (about 2027-01-29) and 252 (about 2027-11).
- **Forward check** (RUNBOOK "Forward check"): sessions after 2026-11-02 are unseen by everything.
- **Paper period** (IB paper account): `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-11-04_18-10-49`. The IB items go with it: #58, #59, #60 (IB data), #61, #116 (IB part), #147, #228, `aq paper-readiness` live items.

## PC notes (not covered in AGENTS.md / `development/infrastructure.md`)
- Close ChatGPT / WhatsApp / Google Drive before heavy work (the 4 GB PC thrashes otherwise). One heavy job at a time, downloads included.
- Lean runs on a temporary DinD Codespace; the training Codespace `aq-Training-Ground-Fixed` (4-core / 16 GB) is kept **stopped** - push before reusing it (local is the source of truth).
- The system Python's pip is broken: `.venv\Scripts\python.exe -m pip --python "C:\Program Files\Python314\python.exe" install --user --no-deps --no-build-isolation -e .`
- Data refresh without the 8 GB build: `scripts/data_append_refresh.py` (checked by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>`. Wide roots: `data_wide/`, `data_crypto_wide/` (gitignored; `scripts/build_wide_root.py`, `build_wide_info.py`, `build_crypto_wide_root.py`).
- `gh codespace cp` needs forward-slash paths: from PowerShell a `C:\...` path fails with only "shell closed". Pass several `-Run` configs from PowerShell directly, not through `-File`.
- `config.json` is LF; `tests/` is not a package on CI (never `from tests.x import ...`); never `git checkout -- <file>` with uncommitted work.
