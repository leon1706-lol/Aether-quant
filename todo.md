# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: after V6.6.4 — hand-over, then wait for time and keys

State: no verified alpha. V6.6.4 ran 25 more pre-registered trials (three rounds) and none survived; the holdouts V1, V2, V3, P and CV are unread, N is 217, and `ml/generations/policy.json` is still `enabled: false`. The book is the long-only crypto sleeve without EOS (11 coins), on paper only. Everything V6.6.4 changed is uncommitted except Part 0 (`ddc673f`). What is open needs your commit, a key, the laptop, or calendar time.

## Do first (yours: the agent never commits, tags or deploys)
1. **Review and commit the V6.6.4 change set.** Run `python scripts/install_hooks.py` once first, so the library gate runs at commit. Suggested message: `V6.6.4: fourth alpha round (none survive), EOS leaves the book, options through main.py in Lean, real-service fixes, verification of every kind`. The observers (g0002-g0005) and the re-pinned config start with this commit.
2. **Wait for CI on that commit** (`gh run list --workflow ci.yml --limit 1`). The Windows job and the webui image build run only there.
3. **Push k09's first decision** so the observer has a record. It is staged in a scratch worktree (`%TEMP%\aq_forward_wt`, decision dated 2026-11-06, valid 25 sessions). After the commit is on `main`: `git fetch origin forward-ledger`, then in that worktree `git add forward/decisions.jsonl && git commit -m "k09 decision 2026-11-06" && git rebase origin/forward-ledger && git push origin HEAD:forward-ledger`. Before the next 22:45 UTC run, or the first sessions read `no_data`.
4. **The tag** (only on a commit whose CI is green, because `tag-tests` does not gate publishing, your V5.3.9 decision): `git tag v6.6.4 <commit> && git push origin v6.6.4`. It publishes PyPI and the image and cannot be undone. Afterwards `pip install aether-quant` should report 6.6.4, and README "Packages lag the repo" can go.
5. **Rebuild the Docker image** before any paper or live deploy: `config.json` changed (EOS), so the old image holds the 12-coin book.
6. **`aq backtest`: not needed.** The re-pin ran on a DinD Codespace and is written up (pins `2026-11-07_17-54-01`, `2026-11-07_17-56-48`).

## Every 20 sessions: k09's decision (about 6 minutes, your own address)
`AQ_SEC_CONTACT=<your address> python scripts/build_wide_info.py --parts extended --refresh`, then `python scripts/k09_decide.py --session <last session> --out ml/cycle/k09_<D>.csv --ledger <worktree>/forward/decisions.jsonl --generation g0005`, then push the branch (RUNBOOK "Research cycle"). `aq cycle status` says when the next one is due. A missed one reads `no_data`; it never fakes a record.

## Waiting on time (nothing to do until sessions pass)
- **Forward records (#299, #313, #319, #323).** `aq evaluate --forward-ledger` (older file) and `aq cycle status` (new file, `forward/generations.jsonl`, started 2026-11-07 with the session of 2026-11-06). Judge at 60 sessions (about February 2027) and 252. The observers are judged the same way, at zero capital.
- **Closing entries.** #299 closes when the older ledger is judged at 60 sessions; #313 when `generations.jsonl` has run for 60; #319 and #323 also wait on a paper period, which needs a key. #301 is judged on the forward record.
- **GitHub disables a schedule after 60 days without repo activity.** `keepalive.yml` re-enables them monthly, but GitHub does not document that this resets the timer, so `aq cycle status` still warns.

## Your laptop (#321)
Every retrain stage is proved on a synthetic panel, but a real local retrain waits for a machine with 14 GB of RAM: `aq cycle retrain --host local --smoke`, then `--procedure k06`, then `aq cycle schedule install` (RUNBOOK "Local retraining"). The real Codespace run of k06 was not done in V6.6.4: the Codespace budget was 90% used.

## Research: where to look next (your call)
Round 4 closed what cheap, free-data ideas could test on cells CS and S. The nearest results were idiosyncratic volatility on crypto (Sharpe 0.62, IC t 4.45, failed the first-half floor and the round's PBO of 0.58), cash profitability (0.39) and filing similarity with accruals (IC t 3.01, Sharpe 0.12). Cell S has now absorbed 48 trials, so a pass there is weak evidence and getting weaker. What stays unspent: the equity holdouts (one frozen candidate, once, `holdout_ledger.jsonl` refuses a second read) and crypto side B (read once, by the installed rule). New information is worth more than new variants: analyst data, true short interest and options chains need a paid or keyed source, which is yours to decide.

## Not in V6.6.4: waiting on the Interactive Brokers and Coinbase keys
Kept so nothing is lost; none of it can progress without an account. RUNBOOK "When the keys arrive" is the checklist, and the keys arrive together.
- **Crypto venue (#192, #312).** You assume Coinbase. Interactive Brokers can't fill this sleeve, Kraken is the fallback, and Coinbase direct is the only route for all 11 coins.
- **Paper period (#228, #319, #323).** `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-11-07_17-54-01`. V6.6.4 proved the plumbing without a broker (Lean's `live-paper` on a fake feed, services stopped under a running algorithm, the audit chain on a real Postgres); what still needs a key and 120 days is a real paper period.
- **IB field test (#338).** Real combo routing and fills, IB's margin against `options_margin_sizing`, assignment notices, IB chain quotes for the detector, the strategy selector on real outcomes, `aq paper-readiness` live items.
- **Quantconnect terms (to accept yourself).** Only if a candidate reaches the survivorship check; nothing is blocked now.

## PC notes (not covered in AGENTS.md / `development/infrastructure.md`)
- Close ChatGPT / WhatsApp / Google Drive before heavy work (the 4 GB PC thrashes otherwise). One heavy job at a time, downloads included.
- Lean runs on a temporary DinD Codespace (deleted after use). The training Codespace `aq-Training-Ground-Fixed` (4-core / 16 GB) is kept **stopped**; push before reusing it (local is the source of truth). The Codespace budget was 90% used at the end of V6.6.4.
- The system Python's pip is broken: `.venv\Scripts\python.exe -m pip --python "C:\Program Files\Python314\python.exe" install --user --no-deps --no-build-isolation -e .`
- Data refresh without the 8 GB build: `scripts/data_append_refresh.py` (checked by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>`. Wide roots: `data_wide/`, `data_crypto_wide/` (gitignored; `scripts/build_wide_root.py`, `build_wide_info.py`, `build_filing_signals.py`, `build_crypto_wide_root.py`).
- `gh codespace cp` needs forward-slash paths and, in Git Bash, `MSYS_NO_PATHCONV=1`. From Git Bash `scp -F` fails on a path with spaces in the ssh config: use PowerShell for `scp`/`ssh`. Never write `sed -i "s/\r$//"` through PowerShell (the backslash is lost and it strips trailing `r` characters). `-CodeOnly` pushes skip `ml/`, so copy tracked `ml/` files by hand.
- `config.json` is LF; `tests/` is not a package on CI (never `from tests.x import ...`); never `git checkout -- <file>` with uncommitted work.
