# Paper to live

Live capital needs every check below measured and passed. **A check without evidence is unknown, and unknown fails.** `aq live-readiness` measures the checks from what the project already writes:

- the forward ledger
- the Lean alpha proof
- the research rounds
- the paper check
- the field test
- the config
- the secrets
- the audit chain
- the backups
- the verification and mutation reports
- the account registry

It prints the scorecard and writes `visualization/grafana/live_readiness.json` for the dashboard's Readiness page. It exits 1 unless the scorecard is ready.

```bash
aq live-readiness                       # the default account
aq live-readiness --account live-1      # one account from accounts.json
aq live-readiness --paper-check report.json --markdown
```

## The scorecard today

<!-- AQ:READINESS_START -->
**NOT READY** for live capital (account `default`, 2026-11-12T09:53:16Z): 7 pass, 6 fail, 8 unknown. Unknown counts as fail.

| Group | Check | Measured | Needs | Status |
|---|---|---|---|---|
| edge | Forward record sessions | 1 | >= 60 | **fail** |
| edge | Forward alpha t (HAC) | - | >= 2.0 | **unknown** |
| edge | Deflated Sharpe of the book | 0.0512 | >= 0.95 | **fail** |
| edge | PBO of the latest research round | 0.26 | < 0.50 | pass |
| paper | Paper trading days | - | >= 120 | **unknown** |
| paper | Paper rebalances | - | >= 6 | **unknown** |
| paper | Every paper metric inside its reference band | - | all inside | **unknown** |
| safety | Field test (orders, trip, flatten, breach, restart, outages, accounts) | 9/9 | all, <= 90 days old | pass |
| safety | Kill switch enabled | True | true | pass |
| safety | A reconciliation breach trips the kill switch | False | true | **fail** |
| safety | Live total-drawdown limit | 0.15 | <= 0.15 | pass |
| operations | Broker secrets resolve from a file, Docker secret or keyring | no broker secrets: a paper account | all, stored safely | **fail** |
| operations | Postgres password is not the published default | - | true | **unknown** |
| operations | Audit chain verifies | - | true | **unknown** |
| operations | Telegram alerts configured | False | true | **fail** |
| operations | Postgres backup | - | <= 7 days old | **unknown** |
| operations | Deployed image digest recorded | - | recorded | **unknown** |
| code | Last full verification green | 22/22 surfaces pass | all pass, <= 30 days old | pass |
| code | Mutation kill rate of the safety modules | 0.963 | >= 0.90 | pass |
| accounts | Account registry valid (overrides only tighten) | True | true | pass |
| accounts | The account is a real brokerage with capital set | default: paper, capital None | broker != paper, capital_usd set | **fail** |
<!-- AQ:READINESS_END -->

## The steps, in order

1. **Edge.**
    - The forward record runs at least 60 sessions (`aq cycle status`), and its alpha t (HAC) reaches 2.
    - The book's deflated Sharpe reaches 0.95.
    - The latest research round's PBO stays below 0.5.
2. **Paper.**
    - At least 120 trading days and 6 rebalances on a fixed config.
    - Every metric stays inside the 5-95% band of the reference Lean run (`aq evaluate --paper-check`, RUNBOOK "Paper period protocol").
3. **Safety.**
    - A field test no older than 90 days passed every check ([Field test](field-test.md)).
    - The kill switch is enabled.
    - A reconciliation breach trips the kill switch (`phase_v2.reconciliation.trips_kill_switch`).
    - The live total-drawdown limit is at most 15%.
4. **Operations.**
    - The broker secrets resolve from a file, a Docker secret or the keyring, never a plain variable ([Secrets](secrets.md)).
    - The Postgres password is not the published default.
    - The audit chain verifies.
    - Telegram alerts are configured.
    - A Postgres backup is at most 7 days old (`scripts/backup_postgres.py`).
    - The deployed image digest is recorded in `state/deploy/image_digest.txt`.
5. **Code.**
    - The last full verification is green and at most 30 days old.
    - The safety modules' mutation kill rate is at least 0.9.
6. **Accounts.**
    - The registry is valid, so every override tightens ([Accounts](accounts.md)).
    - The account is on a real brokerage, with its capital set.

Thresholds live in `config.json` under `phase_v2.live_readiness.thresholds` and can only be made stricter by an owner decision. With `enforce_before_live: true` (off by default), `main.py` holds a `live` run in observation unless the last scorecard is ready.
