# CONTINUE HERE — V5.3.6 session break 2026-08-23

## State snapshot
- Committed through `c0389bd` + this commit (sweeps + docs).
- **Codespace `aq-Training-Ground-Fixed`**: STOPPED after this commit. Code extracted at `~/aq` (torch 2.13.0+cpu OK) and full `ml/` synced (806MB incl datasets). Disk persists while stopped — no re-sync needed tomorrow except pulling back RESULTS.
- SSH access recipe that works:
  `gh cs ssh --config -c aq-sshd-only-test-7v49pjgx6jg43r7g6 | Out-File -Encoding ascii $env:TEMP\cs_ssh_config`
  then `ssh -F $env:TEMP\cs_ssh_config cs.aq-sshd-only-test-7v49pjgx6jg43r7g6.main "<cmd>"`
  (plain `gh cs cp` is BROKEN in this gh version; use scp -F instead)

## Tomorrow's queue (in order)
1. **Training run** on codespace:
   `cd ~/aq && nohup python3 train.py > train.log 2>&1 &` then poll `tail -5 train.log`
   (~15-30 min expected). Then also `python3 train_multitask.py`, `train_sequence.py`,
   `train_gating.py` if time permits.
2. **Pull results back**: tar `ml/versions/*` + refreshed active `ml/*.json` → scp to local
   `ml/versions/codespace_v536_YYYYMMDD/` (NOT promoted to active ml — promotion is user's call).
3. **Stop codespace**: `gh cs stop -c aq-sshd-only-test-7v49pjgx6jg43r7g6`
4. **Docs**: fold today's sweep/null-calibration numbers into Problems.md (#106 entry:
   gate sweep table + kill-switch offline-zero-trips finding + promotion-gate null
   calibration 66%-finding) and Changelog V5.3.6 completion entry.
5. **WS-C finisher**: fix overlap↔sharpe join (parse each backtest log's
   `Dates: Start/End` line — regex exists in scripts/overlap_vs_sharpe_analysis.py,
   needs debug against real log format) → Spearman rho → close #95's metric question.
6. Closeout: full `aq test`, vault regen + HANDOFF, final commit(s).

## Results already banked today (ml/evaluation/)
- `feature_parity_report.json` — NO live-path drift; scaler artifact exact (#105)
- `gate_sweep_results.json` — IC floor 0.02 spares era_0 (0%) w/ bad-era 33-37%;
  aggressive 0.05 doubles bad-era coverage still era_0=0%; base sim net Sharpe
  **+1.497** (multitask rank_5d mirror); spread floors bite era_0 even at p50;
  **kill-switch ZERO trips on offline returns at all 9 combos** → live 26-trip
  sensitivity is live-path only, not offline-calibratable
- `promotion_gate_null_calibration.json` — **P(null t≥2)=2.75%** (t-bar genuine);
  **null runs show ≥2 negative eras 66% of time (mode=2)** → era_sign_instability
  criterion statistically uncalibrated/too strict; recommend null-comparison gating
