# To-Do — Objectives Canvas

The owner's live brief for what to do next; rewritten as objectives change (history lives in
`development/Changelog.md` and `development/Problems.md`).

-----
# Current objective: next phase — owner to write

V6.6.2 was a documentation pass (Problems #327-#330) and V6.6.3 repaired CI (#331); neither changed the book, `config.json` or `main.py`'s behaviour.

V6.6.1 (Problems #313-#322) found no verified alpha: zero of ten more pre-registered trials survived on cell S, so nothing was frozen and the holdouts stay unread (#315). It built the research cycle: up to four generations that share a book, each one's share computed from its record and moving smoothly (R-GLIDE2 adopted it, R-BLEND2 passed in Lean with three at once, #319, #323), a library over every subsystem (#322), and retraining anyone can run (#321). The book is still the V6.5.0 long-only crypto sleeve, on paper only: `config.json` and `main.py` are unchanged, and `ml/generations/policy.json` is `enabled: false`.

## Do first: nothing automatic runs until you push
1. Commit and push V6.6.1 (uncommitted, by your decision). GitHub runs a scheduled workflow only from `main`, so the new daily record starts with that push.
2. Then `gh workflow run research-cycle.yml` once, and `aq cycle status`. **The workflow has not yet run on GitHub**: it was proved against real public prices on a scratch ledger, and by actionlint and `tests/test_ci_workflows.py`.
3. Worth a tag? `setuptools_scm` finds no V6 tags, so an install reads 5.4.x.

## Owner calls
1. **The forward ledger's timing (#313).** `forward/ledger.jsonl` credits each crypto decision one bar the real book never earns: at its timing, the daily series correlates 0.04 with the engine. Its chain is left alone. Judge the sleeve at 60 sessions on `forward/generations.jsonl` instead: that file only starts with your push, so 60 sessions end about three months after it.
2. **Handing over still leans on admission (#318, #323).** If most new generations have no alpha, the dynamic glide still spends a quarter of its time mostly on one (a fixed ladder over half), so R-ADMIT1 is what protects you. Is 30% of the paper book after 60 forward sessions still what you want, knowing a zero-alpha candidate passes that test about half the time?
3. **Where to look next (research, your call).** Round 3's near misses are the accrual family: k09 (quarterly accruals) has the strongest signal (IC t 2.60) and k04 the best Sharpe (0.58). The bar and cell S's 46 trials say don't rerun them there. The honest next test is forward: a rule like k09 in shadow needs fundamentals, so a host writes its decisions (`aq cycle decide`). No selection pass means no share of the book under R-ADMIT1.
4. **Crypto venue (unchanged):** the owner assumes Coinbase, and gets its API key together with the Interactive Brokers key. RUNBOOK "When the keys arrive" is the checklist. EOS leaves the universe at that rebuild (#311). Kraken is the fallback.
5. **QuantConnect terms (to accept yourself):** only if a candidate reaches the survivorship check; nothing is blocked now.
6. **Python 3.10 (#326):** `evaluation/lean_statistics.py` needs 3.11 at import, while `requires-python` says `>=3.10`. Change one or the other when convenient; nothing runs 3.10 today.

## Unspent evidence
- **Equity holdouts V1, V2, V3 and P stay unread.** They back one frozen candidate, once: `ml/generations/holdout_ledger.jsonl` refuses a second read. A candidate after that reaches shadow through 252 forward sessions.
- **Crypto side B** has been read once, by the installed rule only.
- **Cell S is now read by 46 trials.** A pass there is weak evidence, and getting weaker.

## Open (needs time or an external account)
- **Forward records:** `aq evaluate --forward-ledger` (older file) and `aq cycle status` (new file). Judge at 60 sessions and 252. GitHub disables a schedule after 60 days without repo activity; `aq cycle status` warns.
- **Paper period** (IB paper account): RUNBOOK "When the keys arrive", then `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-11-04_18-10-49`. The IB items go with it: #58, #59, #60 (IB data), #61, #116 (IB part), #147, #228, `aq paper-readiness` live items.
- **Your laptop:** `aq cycle retrain --host local --smoke`, then `aq cycle schedule install` (RUNBOOK "Local retraining"). The schedule was not installed on this PC, which has 4 GB.

## PC notes (not covered in AGENTS.md / `development/infrastructure.md`)
- Close ChatGPT / WhatsApp / Google Drive before heavy work (the 4 GB PC thrashes otherwise). One heavy job at a time, downloads included.
- Lean runs on a temporary DinD Codespace; the training Codespace `aq-Training-Ground-Fixed` (4-core / 16 GB) is kept **stopped** - push before reusing it (local is the source of truth).
- The system Python's pip is broken: `.venv\Scripts\python.exe -m pip --python "C:\Program Files\Python314\python.exe" install --user --no-deps --no-build-isolation -e .`
- Data refresh without the 8 GB build: `scripts/data_append_refresh.py` (checked by `scripts/data_append_guard.py`), then `scripts/splice_holdout_dataset.py --build` and `--splice --compare-until <a label horizon before the old end>`. Wide roots: `data_wide/`, `data_crypto_wide/` (gitignored; `scripts/build_wide_root.py`, `build_wide_info.py`, `build_crypto_wide_root.py`).
- `gh codespace cp` needs forward-slash paths: from PowerShell a `C:\...` path fails with only "shell closed". Pass several `-Run` configs from PowerShell directly, not through `-File`. `-CodeOnly` pushes skip `ml/`, so copy tracked `ml/` files by hand. In Git Bash set `MSYS_NO_PATHCONV=1`, or `/tmp/...` turns into a Windows path.
- `config.json` is LF; `tests/` is not a package on CI (never `from tests.x import ...`); never `git checkout -- <file>` with uncommitted work.
