# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Current objective: next phase (V6.2.0)

_(write the objective here)_

## What V6.1.0 decided (nothing was committed; see `development/Changelog.md` "V6.1.0")
- **Decisions by pre-registered rule** (every variant scored on every rebalance phase, Problems #194, #195): the installed models and the head blend stay (best retrained candidate +0.019 validation IC against a seed spread of 0.071); the 20/40 book stays (the 10/20 book is a near miss, +0.099 against +0.10); net-edge holding period, gates (branch B) and the other legacy budgets change nothing.
- **Gross cap stays 1.0.** BT1 reproduced V6 BT2 order for order (+5.28%, drawdown 5.50% against the 5% limit); R-POSTURE2 then asked for a cap of 0.80, and BT2 with it was worse (+3.80%, drawdown 7.80%, Problems #197), so it was not kept. The 5% drawdown clause is still open.
- **Simulator:** it now replays the daily member pass, the whole-portfolio kill switch, weekend crypto, the position cap, the live analyzer, the legacy signal and the way live counts crypto twice in the rolling-IC gate. R-CAL2 is still branch B but close (daily correlation 0.71 / 0.67 / 0.68, annual gaps +1.2 / -2.5 / -0.5 pp, decision agreement 77 / 94 / 76%); out of sample over the whole span it correlates 0.62 with Lean (Problems #190, #196).
- **Parity:** the forex holiday calendar is fixed (the dataset now matches Lean's), EURUSD / GBPJPY / ETHUSD / BTCUSD / XOM / NVDA / TLT diverge on 0 of 170 dates in BT1.
- **Latency:** environmental (a 2011 two-core laptop, 4 GB, a 1.9 GB Docker VM): the same function costs 1.9 ms native, 5.3 ms in a bare container, 8.9 ms in the engine (Problems #191).
- **Crypto live venue:** QuantConnect's Interactive Brokers brokerage does not support crypto; `aq render-lean-config` warns (Problems #192).

## Starting point
- Shipped `config.json` (sha256 `19d72bc99cffb5766eae918fa0c811253adc6862c70e8e3880edb7d85531fa2f`; `runtime.lean_window_override` is `null`, probes off); installed models unchanged since V5.8.0 (47 files, `ml/evaluation/v610/manifest_start.txt`). Lean over 2023-07..2026-09: V6 BT2 and V6.1 BT1 are the same run (+5.28%, drawdown 5.50%, 1,268 identical order events); V6.1 BT2 with a 0.80 cap +3.80%, drawdown 7.80% (Problems #196, #197).
- `ml/datasets/full_dataset.csv` and the split files are the V6.1 build (Lean's forex holidays, four splits, active scaler). Still on disk and not approved for deletion: `data_v580_staging/` (kept on your answer), `ml/datasets/v580_active_dataset.csv` (755 MB), `ml/datasets/v600_rank60_dataset.csv` (880 MB), the 29 candidate version dirs `ml/versions/v610_*`, and `ml/versions/v600cs20261015_*`.
- Docker Desktop is off (start it, wait ~10 minutes before a Lean run: a cold start made BT2's first attempt hit the 90 s `Initialize()` limit); the Codespace is Shutdown.

## Leads for the next objective
0. **Owner choice, legacy budget L2:** `legacy_sleeve.max_gross_exposure` 0.15 and `max_weight_per_name` 0.03 pay on the backtest (Sharpe 0.89 against 0.74, better on 60-70% of phases) and pass the book margins, but fail R-LEGACY's clause that the legacy component earns on both splits (validation -0.92%, the 2022 bear year; the shipped budget loses -0.43% there too). Config only.
1. **Live counts crypto twice in the rolling-IC gate (owner choice):** `main.py` appends an IC event on a crypto pair's own midnight tick and again on the next equity tick, so crypto weighs double; replicating that offline made the gate value match (correlation 0.977, 92% on the same side of the floor, Problems #196). Deduplicating live is a one-line behaviour change that would make the gate read about +0.012 higher and engage more often; it was not done (it changes Lean results and the Lean budget was spent). What keeps R-CAL2 on branch B now is the kill switch's lock timing (it reads a rolling Sharpe near its -1.0 floor from a return series that tracks Lean's at r 0.7-0.8) and a 0.5 pp gap on the holdout stretch.
2. **Alpha is still unproven out of sample:** every retrained candidate stays inside seed noise; the most regularised one (`v9_reg`, weight decay x16 and dropout 0.5) has the best validation decision IC (+0.027 swapped priority, +0.058 daily t 1.67) and halves the train IC, which is the direction to push (more seeds, label noise, a smaller feature set). The honest test is a paper period.
3. **Phase luck:** the shipped book's ungated validation Sharpe spans -1.02 to +0.57 across rebalance phases; a staggered book (several tranches rebalancing at offsets, or partial adjustment toward the target) would average the timing luck out. Not built.
4. **Latency:** only a faster host moves it (run Lean on a bigger machine); `scripts/profile_main_tick.py` runs inside the Lean image for a reading.
5. **Crypto live venue:** decide the live brokerage for crypto (Coinbase through QuantConnect, a cash account) or switch the crypto classes off before any live deploy; belongs with the IB items.
6. **#104 teardown timeout** is environmental and unchanged (Problems #184).

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 need a live/paper IB connection; `aq paper-readiness` needs the deployed Postgres and the paper broker config, so it belongs here too.

## Resume checklist
- Never push to the Codespace without `-CodeOnly` after a retrain (a full push overwrites the remote `ml/`).
- A Codespace job stops when the Codespace idles out (no ssh session for ~30 minutes): keep a `gh codespace ssh ... 'while pgrep ...'` open for the whole run and resume with `RESUME=1`.
- Files written from Python on Windows get CRLF: a `.sh` with CRLF fails on the Codespace (`set: -: invalid option`); `sed -i 's/\r$//'` before uploading.
- `tests/` is not a package on CI or the Codespace: never `from tests.x import ...`.
- Lean's `code/` folder holds no config.json: a run's config is kept at `ml/evaluation/run_configs/<run folder>.json` (freeze it right after the run).
- Never `git checkout -- <file>` a file with uncommitted work (a README refresh from a failed run cost a re-application of the manual edits).
- Keep the PC light during a Lean run (`Initialize()` has a 90 s limit; ~250 MB free is what a run starts with). Quit Docker Desktop and run `wsl --shutdown` for any heavy offline job; a stuck `WslService` needs an elevated `taskkill /F /PID <its pid>`.
- Git Bash rewrites `/app/...` in `docker run -v`: set `MSYS_NO_PATHCONV=1` and use `pwd -W` paths; the Lean image's entrypoint launches Lean, use `--entrypoint python` for anything else.
- Inline `ssh` commands lose double quotes on Windows: use `grep -e a -e b`, never `grep -E "a|b"`, and never `pkill -f` through ssh.
