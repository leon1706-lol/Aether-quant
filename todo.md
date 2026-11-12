# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: V6.6.5 — open the door: a 5-minute start, a first-class library, a hardened live path

**State (2026-11-12): COMPLETE, uncommitted.** Every box below is ticked and verified on the PC: `aq test` 5349 of 5349, the field test 9 of 9, the dashboard image smoke-tested, mutation 0.982 on an independent seed (`ml/evaluation/v665/`). Left for the owner: commit and tag v6.6.5, rebuild the engine image, an `aq backtest` of the default account. Next is V6.6.6 below. Same book and record as before (no verified alpha, paper only); V6.6.5 spent no alpha trial. Plan: `C:\Users\Blackhead\.claude\plans\for-the-next-plan-starry-scott.md`; evidence in `ml/evaluation/v665/`.

**Owner decisions (2026-11-08).** Library and everything the wheel and dashboard ship become Apache-2.0, the trading system stays PolyForm Noncommercial · no broker keys: the field test runs on Lean's PaperBrokerage · `main.py` may be edited with stub and parity tests, defaults unchanged · `aq hello` reads keyless Coinbase candles with a bundled sample as fallback · verification on the PC only, the owner commits and tags · the agent may enable GitHub Pages · the field test runs on the PC's Docker.

## Checklist
- [x] **0.** This file: the old V6.6.5 draft is now V6.6.6 (below).
- [x] **A1.** A light install: `pip install aether-quant` pulls numpy and pandas only; every facade imports without httpx, scipy or torch (#342).
- [x] **A2.** Keyless public candles and a bundled sample (#343).
- [x] **A3.** `aq hello`: download, the shipped rule, a backtest and a clean report in one command (#343).
- [x] **A4.** Four notebooks with Colab badges: hello world, signal evaluation, book construction, overfitting tests (#343).
- [x] **A5.** The dashboard in one Docker command, with demo data, onboarding, login, accounts and readiness (#344).
- [x] **B1.** Library gaps: Kelly, vol targeting, beta/factor neutrality, cost models, min track record, haircut Sharpe, `backtest()`, signal tools, facades by job (#345).
- [x] **B2.** Type completeness of the public API, and docstrings (#346).
- [x] **B3.** API docs on MkDocs, examples, GitHub Pages (#346).
- [x] **B4.** License split: library Apache-2.0, system PolyForm Noncommercial (#347).
- [x] **C1.** Secret management: env, file and keyring refs, `aq secrets`, Coinbase keys renderable (#348).
- [x] **C2.** Multi-account: registry, risk overrides that only tighten, per-account state and deploys (#349).
- [x] **C3.** Multi-user API: tokens, roles, account scope, an audited trade lock (#350).
- [x] **C4.** The field test without a broker: orders, kill-switch trip, reconciliation breach, restart, two accounts (#351).
- [x] **C5.** Paper-to-live scorecard with measured metrics, `aq live-readiness` (#352).
- [x] **C6.** Runbooks: secrets, accounts, users, backups, field test, paper to live.
- [x] **C7.** CI: badges, coverage reports, CodeQL, Scorecard, bandit, trivy, blocking secret scan, SBOM and provenance (#353).
- [x] **C8.** GitHub Pages enabled.
- [x] **D.** Problems, Changelog, docs, vault, verification.

-----
# Next objective: V6.6.6 — let the forward record speak, and close what needs no new alpha trial

**State (2026-11-08).** V6.6.4 is released: `v6.6.4` is tagged on `faac641`, CI is green, PyPI reports 6.6.4 and the image is on `ghcr.io/leon1706-lol/aether-quant` (tags `6.6.4`, `latest`). There is no verified alpha: 25 more pre-registered trials found none, the holdouts V1, V2, V3, P and CV are unread, N is 217, and `ml/generations/policy.json` is `enabled: false`. The book is the long-only crypto sleeve (11 coins, Lean pin `2026-11-07_17-54-01`), on paper only. The forward record started with session 2026-11-06 and four observers at zero capital are watching beside it (k09 and the crypto trials x10, x14, x12).

**Why this phase looks different.** Cell S has absorbed 48 trials and CS 19, and every round since V6.6.0 has failed the same bar. Another variant on the same data is the weakest next step; time (the forward record) and new information are the strongest. So V6.6.6 spends its effort on three things: reading the forward record as it forms, one pre-registered round on genuinely new crypto data that fits the 4 GB PC, and the engineering backlog that needs neither a key nor a Codespace.

## Guardrails (unchanged)
- No `aq backtest` by an agent, no sign-ups, no accepted terms, no payment. A step that needs one is closed as unavailable.
- The holdouts V1, V2, V3, P and CV stay unread unless a frozen survivor exists (`holdout_ledger.jsonl` refuses a second read). Rules are hashed in the vault before any score and never edited; a defect voids a trial with no re-score (re-register it as a new one).
- `main.py` is not edited without your word. The live path reuses the pure function the simulator calls, or ships a parity test.
- The SEC contact is your address in `AQ_SEC_CONTACT`, for one process, never written down.
- Codespaces only while a job runs, and none can start right now (below).

## Do first
1. **Monday 2026-11-09, after 22:45 UTC: did the record keep going?** `aq cycle status` and `aq evaluate --forward-ledger` should show session 2026-11-09 on `forward/generations.jsonl`, with g0001-g0005 and `chain_valid: true`. A red run or a `no_data` row is a P1: the late-run fix (#332) is what protects the record.
2. **The 11 open dependency pull requests (numbers 19 to 30).** Merge the small ones that CI passes (`pytest-cov`, `pytest-xdist`, `joblib`, `psycopg`, `drei`, `docker/login-action`). Hold the `torch >= 2.14.1` PR (24), `typescript 7` (25) and `vite` (21): a torch bump can change the model files' numbers and TypeScript 7 is a major, so each wants its own CI run and, for torch, `tests/test_exported_model.py` and a parity check before merging.
3. **Codespace quota.** GitHub refuses to start a Codespace (HTTP 402) until the monthly quota resets or you raise the limit. When it is back, spend the first hours in this order: the real `aq cycle retrain --host codespace --procedure k06` (run it from PowerShell, not Git Bash), then any Lean run V6.6.6 needs, then a research round that needs the equity cell. Delete the DinD Codespace when its runs are pulled.

## V6.6.6 scope (proposed; your call on each)
**A. Forward record first (no cost).**
- Check `aq cycle status` weekly; at 60 sessions (about the first week of February 2027) judge g0001-g0005 on `forward/generations.jsonl`, and the older ledger for #299.
- k09's decision (dated 2026-11-06) is good for 25 sessions, and the refresh every 20 is due about 7 December: `AQ_SEC_CONTACT=<your address> python scripts/build_wide_info.py --parts extended --refresh`, then `python scripts/k09_decide.py --session <last session> --out ml/cycle/k09_<D>.csv --ledger <worktree>/forward/decisions.jsonl --generation g0005`, then push the branch (RUNBOOK "Research cycle"). A missed one reads `no_data`; it never fakes a record.

**B. One pre-registered round on new crypto information, on the PC.** Crypto cell CS fits in 4 GB (round 4C ran on this PC); the equity cell does not. Nothing below has been tested, and each idea is a hypothesis to register before any score:
- Order flow: the taker-buy share of daily volume. First check whether the Binance archive's kline files in `data_crypto_wide` carry the taker-buy columns; if they do, this costs only code.
- Positioning: Binance perpetual open interest and the long/short ratio (the archive's metrics files, free, from about 2020-21), lagged like funding.
- Stablecoin supply growth as a market-wide timer, if a free daily series is on hand.
- Rules: new rule file hashed in the vault first; the observers are x10, x14 and x12 (picked by the pre-registered rule), not the near miss x08 (idiosyncratic volatility, Sharpe 0.62, IC t 4.45, first half 0.39) can only be tested again as a new, counted trial. Expect zero survivors; N rises either way.
- The equity holdouts and crypto side B stay unspent for a survivor that earns them.

**C. Engineering backlog (all PC-only).**
- `library_gate`: 288 legacy unexported names. Export what is pure and stable, explain the rest, and lower `LEGACY_CEILING` as it shrinks.
- `tests/data/modules_without_own_test.json`: 24 modules still lack their own test file; give them one and shrink the list.
- 113 scripts, of which many have no test naming them: mark each as a past-round record or a tool in `scripts/README.md`, and give each tool a `--help` test.
- Option coverage: only 8 of the 43 structures built through `main.py` on the sample chain. Widening the dates scanned needs a DinD Codespace (quota), so it waits.
- Mutation survivors are equivalent today; rerun `scripts/mutation_check.py` (a fresh seed) after any change to the safety or ledger modules.

**D. Decisions only you can make.**
- Whether to pay for, or key into, data that could be new information for equity: analyst estimates, true short interest, options chains. Nothing free covers them; this is the one way past the cell-S ceiling.
- Whether to raise the Codespace spending limit or wait for the reset.

## Waiting on time (nothing to do until sessions pass)
- **Forward records (#299, #313, #319, #323).** Judge at 60 sessions and again at 252. The observers are judged the same way, at zero capital.
- **Closing entries.** #299 closes when the older ledger is judged at 60 sessions; #313 when `generations.jsonl` has run for 60; #319 and #323 also wait on a paper period, which needs a key. #301 is judged on the forward record.
- **GitHub disables a schedule after 60 days without repo activity.** `keepalive.yml` re-enables them monthly, but GitHub does not document that this resets the timer, so `aq cycle status` still warns.

## Your laptop (#321)
A real local retrain needs a machine with 14 GB of RAM: `aq cycle retrain --host local --smoke`, then `--procedure k06`, then `aq cycle schedule install` (RUNBOOK "Local retraining"). Every stage is proved on a synthetic panel; k06 already failed (#315), so a real run shows plumbing only.

## Waiting on the Interactive Brokers and Coinbase keys
None of it can progress without an account. RUNBOOK "When the keys arrive" is the checklist, and the keys arrive together.
- **Crypto venue (#192, #312).** You assume Coinbase. Interactive Brokers can't fill this sleeve, Kraken is the fallback, and Coinbase direct is the only route for all 11 coins.
- **Paper period (#228, #319, #323).** `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-11-07_17-54-01`. The plumbing is proved without a broker; what still needs a key and 120 days is a real paper period.
- **IB field test (#338).** Real combo routing and fills, IB's margin against `options_margin_sizing`, assignment notices, IB chain quotes for the detector, the strategy selector on real outcomes, the live items of `aq paper-readiness`.
- **QuantConnect terms (to accept yourself).** Only if a candidate reaches the survivorship check; nothing is blocked now.

## PC notes (not covered in AGENTS.md / `development/infrastructure.md`)
- Close ChatGPT / WhatsApp / Google Drive before heavy work (the 4 GB PC thrashes otherwise). One heavy job at a time, downloads included. A tree-wide `grep -r` is slow here; search `git ls-files` instead.
- The suite can only run on a Codespace; run `scripts/codespace_verify.ps1 -Start` on the final tree before a push (it found five failures the PC never showed). `aq verify --quick` is what fits the PC.
- A stopped DinD Codespace loses its `/tmp`, including the Lean image (the first start rebuilds it, about 8 minutes). Lean runs on a temporary DinD Codespace, deleted after use; the training Codespace `aq-Training-Ground-Fixed` is kept stopped, and a push to it needs `-CodeOnly` once `ml/` holds results there.
- The system Python's pip is broken: `.venv\Scripts\python.exe -m pip --python "C:\Program Files\Python314\python.exe" install --user --no-deps --no-build-isolation -e .`
- Data refresh without the 8 GB build: `scripts/data_append_refresh.py` (checked by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>`. Wide roots: `data_wide/`, `data_crypto_wide/` (gitignored; `scripts/build_wide_root.py`, `build_wide_info.py`, `build_filing_signals.py`, `build_crypto_wide_root.py`).
- Windows shells: `gh codespace cp` needs forward-slash paths and, in Git Bash, `MSYS_NO_PATHCONV=1`; Git Bash also rewrites `/workspaces/...` arguments, which hangs `aq cycle retrain`, so run that from PowerShell. From Git Bash `scp -F` fails on a path with spaces in the ssh config: use PowerShell for `scp`/`ssh`. Never write `sed -i "s/\r$//"` or `tr -d "\r"` through PowerShell (the backslash is lost and it strips every `r`); put such a command in a script written with the Write tool. The git credential manager hangs on push: `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push`.
- `config.json` is LF; `tests/` is not a package on CI (never `from tests.x import ...`); never `git checkout -- <file>` with uncommitted work.
