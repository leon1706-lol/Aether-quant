# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: V6.7.1 — CI repair, Dependabot, the `aq` CLI to 10/10, the model lab

**State (2026-11-21): in verification.** Plan: `C:\Users\Blackhead\.claude\plans\so-for-the-next-glittery-melody.md`. The agent commits and pushes, then watches CI until green (owner decision). Entries #413-#422 in `development/Problems.md`; the Changelog's "Phase V6.7.1".
- **Done:** main green (#413, #414), every Dependabot PR applied on main and closed with grouped updates (#415, #416), the CLI audit with every command at 10/10 (`development/cli_audit.md`, enforced by `tests/test_cli_help_surface.py`), the new developer, owner and maintainer commands, the model lab with its data, signal and research commands (#422), the docs (guide, notebook, example, `docs/reference/cli.md`).
- **Owner steps after the push:** a Docker image rebuild (the networks the live path imports moved to `lab/`, unchanged), a tag (it publishes the example models and proves `aq models install` and `aq release check` against a real release), and the next real `aq backtest --no-publish` to prove #419.

-----
# Previous objective: V6.6.10 (complete, committed in 997c126)

-----
# Next: leads and suspected bugs from V6.6.10 (untested; each lead needs a pre-registered round)

Evidence lives in `ml/evaluation/v6610/` (gitignored): `alpha_behaviour.json`, `retrain_compare.json`, `book2/r_book2.json`, `bt_r1/blend_blend.json`, `bt_r1_report/backtest_audit.json`. Window for the Lean numbers: 2023-07-01 to 2026-11-02 (BT-R1 `2026-11-20_12-07-55`, pin `2026-11-16_16-25-28`).

**What we know about the 30% model book**
- It earns nothing on its own: Sharpe 0.04 alone (V6.6.9). In BT-R1, bonds lost $511 net over 139 trades, equities $576 over 138, and forex never traded. All the profit came from crypto (+$17.9k net) and the cash sweep (+$3.4k).
- It is decaying: the pin's first half (2023-07 to 2025-06) has Sharpe 1.17 with the risk-free rate, and the second half (2025-07 to 2026-11) has −0.17. Every R-BOOK2 trial also fails its second half (2021-04 to 2023-06).
- The rolling-IC floor is not the brake (#410). The shipped config trades a weights file, so `main.py` never reaches the member book or its gate. What limits it is the design below (leads M3 to M5).

**Model-performance leads (multi-asset book)**
- **M1. Trade the score that predicts.** b03 trades `ml_a1`, whose pooled 20-session rank IC on the selection window is 0.015 (t 0.62). `ml_a2`, the multitask sector-neutral head, has 0.078 (t 2.70), a half-life of 47 sessions, and 0.036 left after momentum, low volatility, carry and beta. R-BOOK2's nine `ml_a2` books still failed their second half. The next round should first explain that half (by class, year and regime with `evaluation/alpha_behaviour.py`) before designing books.
- **M2. One score source per class.** Each class is best predicted by a different score:
  - **Bonds:** `ml_a3` (IC 0.126).
  - **Crypto:** g0007's `ml_a1` (0.152, t 3.49, against 0.121 for the installed models).
  - **Equities:** near zero in every model (g0007 0.006, installed 0.019).
  - **Forex:** weak (0.029 / 0.054, t < 0.9).

  Candidates: a class-specific source, or a model book without equities. Check the crypto part's correlation with the 70% trend sleeve first.
- **M3. Fewer, larger positions.** The book spreads 30% across about 100 names (at most 0.5% per equity, 1.5% per bond). Equity fees come to about 30 bps per fill and bond fees to about 17 bps, because the $1 minimum fee hits tiny orders. Test top-k per class, or a higher `min_trade_usd`, offline with the Lean cost model.
- **M4. Forex never trades.** Forex weights change by at most 1.0% of equity (about $1,300) per rebalance, under `forex_min_trade_usd` 5,000. Either drop forex and give its weight to the other classes, or concentrate it into a few pairs. Check the broker's real forex minimum before lowering the setting.
- **M5. Cadence against half-life.** The book rebalances every 20 sessions, against `ml_a2`'s 47-session half-life. The 40-session trials (n02, n09) failed alone, so test cadence together with M3.
- **M6. Model age.** The installed models date from 2026-10-12. g0007's scores stop at its score-end of 2023-06-30, and later rows are extrapolated with its scaler. Try a rolling retrain with a later score-end; the holdout ledger has to allow it first.
- **M7. The offline-to-Lean gap.** Offline the blend reaches Sharpe 0.617 (installed) / 0.612 (g0007); Lean gives 0.571 / 0.568, about 0.045 lower. Attribute it (`aq evaluate --attribute-lean`: fees, fill timing) before the next round, because a candidate's offline margin has to beat it.
- **M8. A noise band for installs.** g0007 missed R-INSTALL3 by 0.002 Sharpe, inside any bootstrap interval. A future install rule should pre-register a tolerance band, not a bare ≥.
- **Closed, do not repeat:**
  - Loss functions (R-LOSS1 0/5, #407).
  - The 70/30 flip until a book survives R-SLEEVE2 (#409).
  - The trial budget is N = 258 and R-BOOK2's PBO was 0.79, so keep rounds small and well motivated.

**Safety decision (owner, rule 9)**
- **S1. No performance gate acts on the shipped book.** On the target-weights path only the trade locks act (15% drawdown, 5% daily) and the kill switch with its remaining triggers. The rolling-IC gate and the member-decision kill-switch reasons belong to the member book. Decide whether the model book needs its own rolling-IC or Sharpe gate on its own scores; this is the same question as the kill-switch item under "Owner steps".

**Suspected bugs and tooling gaps**
- **B1. The same stale-run risk as #410 elsewhere.** *Done in V6.7.1 (#418).*
  - `aq_cli._default_book_history_path`, which the reconcile tools use, takes the newest per-run file whatever the run's mode.
  - `scripts/sleeve_alpha_check.py` takes the latest segment of the cumulative file.

  Both should check `backtest_audit.member_book_runs` on the run's config.
- **B2. Side effects of Lean runs.** *Done in V6.7.1 (#419, `aq backtest --no-publish`).*
  - `aq backtest` unpins `ml/evaluation/readme_lean_run.json`, and rewrites the README, `development/research_results.md`, the charts and the `ml/evaluation/*.json` reports.
  - `aq evaluate --audit-backtest` re-renders the README sections too.

  A research run needs a no-publish mode. For now: snapshot the hashes, restore, rewrite the pin, and rerun `aq evaluate --lean-report`.
- **B3. Run configs are not frozen under the run's name.** *Done in V6.7.1 (#419, frozen under the run's name).* Lean's `code/` has no `config.json`. BT-R1's config existed only as `v6610_bt_r1.json` until it was copied to `ml/evaluation/run_configs/2026-11-20_12-07-55.json` by hand, and tools fall back to the current config without saying so. `aq backtest` should freeze it.
- **B4. Check the exposure split.** In BT-R1 the mean "Equity - Long Ratio" is 0.89, while the book holds at most 30% outside crypto. This is probably the cash-sweep ETF counted as equity; the audit should list the sweep separately.
- **B5. Coverage hook skipped.** *Done in V6.7.1 (the full coverage run of V6.7.1).* The V6.6.10 commit skipped the coverage hook; `evaluation/backtest_audit.py`, `aq_cli.py` and `evaluation/pipeline.py` changed after the last full run. Watch CI `python-tests` (100% gate) after the push.
- **B6. Hypothesis "too_slow" health checks.** *Done in V6.7.1 (#420, `aq test --light-hypothesis`).* They fail on the 4 GB PC under paging (the cost-model properties among them) and pass alone. Consider a lighter local profile.
- **B7. The old zip is still in git history (#411).** It holds the production weights; removing it needs a history rewrite and a force-push (owner).
- **B8. Unproven until their first real run:**
  - the `lowmem-proof` CI job (#398);
  - the `example-models` release job and `aq models install` from a real release (#401, needs the tag);
  - `model-cycle.yml` (#402);
  - the proof backlog: 881, with the plan target at 0 (#403).
- **B9. #321 can close.** g0007 was a real local retrain on the 4 GB PC (#406), which is what #321 waited for.

-----
# Previous objective: V6.6.9 — the multi-asset model book back on the trusted path, a docs pass

**State (2026-11-17): COMPLETE, uncommitted** (the owner commits). Plan: `C:\Users\Blackhead\.claude\plans\now-for-the-next-velvet-codd.md`. Evidence: `ml/evaluation/v669/`; entries #382 to #397 in `development/Problems.md`. Verified on this PC: the full `aq test --coverage` (every module at 100%), the clean-checkout run (7,222 passed), `aq prove --regen-cases`, `mkdocs build --strict`, the notebooks check and the guards.

**What it did.**
- **The book:** the model book is back beside the crypto sleeve (70% crypto, 30% model book), installed by the owner's rule as "reinstated, not verified", on paper.
- **The research:** no trial survived R-SLEEVE2 (R-BOOK1: 12 optimizers; R-MIX1: 6 signal mixes; 26 new trials, N now 243). The candidate is b03: inverse-volatility ranks, every 20 sessions.
- **The pin:** Lean run `2026-11-16_16-25-28` is the new README pin, Sharpe 0.57 (the crypto sleeve alone was 0.65), and the engine reproduces it at 0.99999.
- **The rest:** a book optimizer, the default-off in-Lean mode, the model-stack retrain (`stack`), the scaler restore with pins, HRP and forex-sweep fixes, and the docs pass.

**Still open in this phase's own work:** only what needs a Codespace (the first real model retrain) or the keys (the paper period).

-----
# Owner steps still open
- **Tag.** V6.6.9 is committed (d427c8b) but untagged; the next tag covers V6.6.9 and V6.6.10 and publishes the example models.
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
Since V6.6.10 a real retrain fits this PC: `aq cycle retrain --host local --procedure stack --memory-profile low`, started detached and resumable (`--resume`, `--list-runs`); g0007 took about two days, with a peak of 1.37 GB (#406). `aq cycle schedule install` is still open; k06 already failed (#315).

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
