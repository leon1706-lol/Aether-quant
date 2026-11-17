# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: V6.6.9 — the multi-asset model book back on the trusted path, a docs pass

**State (2026-11-17): COMPLETE, uncommitted** (the owner commits). Plan: `C:\Users\Blackhead\.claude\plans\now-for-the-next-velvet-codd.md`. Evidence: `ml/evaluation/v669/`; entries #382 to #397 in `development/Problems.md`. Verified on this PC: the full `aq test --coverage` (every module at 100%), the clean-checkout run (7,222 passed), `aq prove --regen-cases`, `mkdocs build --strict`, the notebooks check and the guards.

**What it did.**
- **The book:** the model book is back beside the crypto sleeve (70% crypto, 30% model book), installed by the owner's rule as "reinstated, not verified", on paper.
- **The research:** no trial survived R-SLEEVE2 (R-BOOK1: 12 optimizers; R-MIX1: 6 signal mixes; 26 new trials, N now 243). The candidate is b03: inverse-volatility ranks, every 20 sessions.
- **The pin:** Lean run `2026-11-16_16-25-28` is the new README pin, Sharpe 0.57 (the crypto sleeve alone was 0.65), and the engine reproduces it at 0.99999.
- **The rest:** a book optimizer, the default-off in-Lean mode, the model-stack retrain (`stack`), the scaler restore with pins, HRP and forex-sweep fixes, and the docs pass.

**Still open in this phase's own work:** only what needs a Codespace (the first real model retrain) or the keys (the paper period).

-----
# Owner steps still open
- **Commit and tag V6.6.9.** Nothing is committed.
- **Rebuild the Docker images.** Live-path code changed (`main.py`, `portfolio/`, `risk/`).
- **The first g0006 decision:** `python scripts/model_book_decide.py --session D --out ml/cycle/g0006_D.csv --ledger <worktree>/forward/decisions.jsonl --generation g0006`, then push the branch (RUNBOOK "Research cycle").
- **Two decisions:** keep the model book at 30%? And should the kill switch's Sharpe, rank-IC, loss-streak, velocity and slippage triggers (off since V6.5.0 for a crypto sleeve) come back for a four-class book? Only the 15% drawdown lock and the 5% daily lock protect it now.
- bestpractices.dev: enter the remaining answers so the badge reads "passing" (#366).

# Open leads (untested; each needs a pre-registered round)
- **Crypto, new information, cell CS (fits the PC):** the taker-buy share of daily volume, Binance perpetual open interest and the long/short ratio, stablecoin supply growth as a market timer. x08 (idiosyncratic volatility) only as a new, counted trial.
- **Equity data that needs a key or payment** (analyst estimates, true short interest, option chains): your call. Nothing free covers them.

# When a Codespace can start again
1. The model-stack retrain: `aq cycle retrain --host codespace --procedure stack` (RUNBOOK "Retraining the model stack"). The models are dated 2026-10-12, and the kill switch stops a model book at 180 days (2027-04-10).
2. `aq cycle retrain --host codespace --procedure k06`, from PowerShell, not Git Bash (#321).
3. `scripts/codespace_verify.ps1 -Start` on the final tree before a push.
Delete a DinD Codespace when its runs are pulled.

# Waiting on time (nothing to do until sessions pass)
- **Forward records (#299, #313, #319, #323).** `aq cycle status` weekly. Judge at 60 sessions (about the first week of February 2027) and again at 252. The observers are judged the same way, at zero capital.
- **k09's decision** is good for 25 sessions; the refresh every 20 is in RUNBOOK "Research cycle". A missed one reads `no_data`; it never fakes a record.
- **Closing entries.** #299 closes when the older ledger is judged at 60 sessions; #313 when `generations.jsonl` has run for 60; #319 and #323 also wait on a paper period, which needs a key. #301 is judged on the forward record.
- **GitHub disables a schedule after 60 days without repo activity.** `keepalive.yml` re-enables them monthly, but GitHub does not document that this resets the timer, so `aq cycle status` still warns.

# Your laptop (#321)
A real local retrain needs a machine with 14 GB of RAM: `aq cycle retrain --host local --smoke`, then `--procedure k06`, then `aq cycle schedule install` (RUNBOOK "Local retraining"). Every stage is proved on a synthetic panel; k06 already failed (#315), so a real run shows plumbing only.

# Waiting on the Interactive Brokers and Coinbase keys
None of it can progress without an account. RUNBOOK "When the keys arrive" is the checklist, and the keys arrive together.
- **Crypto venue (#192, #312).** You assume Coinbase. Interactive Brokers can't fill crypto, Kraken is the fallback, and Coinbase direct is the only route for all 11 coins.
- **Paper period (#228, #319, #323).** `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/<pinned run>`. The plumbing is proved without a broker; what still needs a key and 120 days is a real paper period.
- **IB field test (#338).** Real combo routing and fills, IB's margin against `options_margin_sizing`, assignment notices, IB chain quotes for the detector, the strategy selector on real outcomes, the live items of `aq paper-readiness`.
- **QuantConnect terms (to accept yourself).** Only if a candidate reaches the survivorship check; nothing is blocked now.

# PC notes (not covered in AGENTS.md / `development/infrastructure.md`)
- Close ChatGPT / WhatsApp / Google Drive before heavy work (the 4 GB PC thrashes otherwise). One heavy job at a time, downloads included. A tree-wide `grep -r` is slow here; search `git ls-files` instead.
- The suite can only run on a Codespace; run `scripts/codespace_verify.ps1 -Start` on the final tree before a push (it found five failures the PC never showed). `aq verify --quick` is what fits the PC.
- A stopped DinD Codespace loses its `/tmp`, including the Lean image (the first start rebuilds it, about 8 minutes). Lean runs on a temporary DinD Codespace, deleted after use; the training Codespace `aq-Training-Ground-Fixed` is kept stopped, and a push to it needs `-CodeOnly` once `ml/` holds results there.
- The system Python's pip is broken: `.venv\Scripts\python.exe -m pip --python "C:\Program Files\Python314\python.exe" install --user --no-deps --no-build-isolation -e .`
- Data refresh without the 8 GB build: `scripts/data_append_refresh.py` (checked by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>`. Wide roots: `data_wide/`, `data_crypto_wide/` (gitignored; `scripts/build_wide_root.py`, `build_wide_info.py`, `build_filing_signals.py`, `build_crypto_wide_root.py`).
- Windows shells: `gh codespace cp` needs forward-slash paths and, in Git Bash, `MSYS_NO_PATHCONV=1`; Git Bash also rewrites `/workspaces/...` arguments, which hangs `aq cycle retrain`, so run that from PowerShell. From Git Bash `scp -F` fails on a path with spaces in the ssh config: use PowerShell for `scp`/`ssh`. Never write `sed -i "s/\r$//"` or `tr -d "\r"` through PowerShell (the backslash is lost and it strips every `r`); put such a command in a script written with the Write tool. The git credential manager hangs on push: `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push`.
- `config.json` is LF; `tests/` is not a package on CI (never `from tests.x import ...`); never `git checkout -- <file>` with uncommitted work.
