# Field test

The field test drives a real `main.py` in Lean's `live-paper` environment: Lean's paper brokerage, a fake data feed, and real Redis and Postgres. It needs no broker account, no key and no money, and it proves plumbing, never edge.

```bash
python scripts/lean_smoke/field_test.py     # writes ml/evaluation/field_test/<date>/report.json
```

It needs Docker, the pinned Lean engine image and about an hour, and it runs three times:

1. **One account** trades two coins by the minute. One target row is ordered at bar 3. Injected drift breaches reconciliation from bar 8, and an injected shock trips the kill switch at bar 14. Redis and then Postgres are stopped under the running engine.
2. **The same project restarts.**
3. **Two accounts run at once**, `paper-a` and `paper-b` from `accounts.example.json`.

`main.py` writes one `FIELD_TEST event=... bar=...` line per event to the engine log, and the report is built from those lines and the audit chain.

| Check | How |
|---|---|
| orders submitted and filled | the target-weights path places orders, and the paper brokerage fills them |
| kill switch trips | an injected drawdown-velocity shock after N bars trips it within 3 bars |
| flat after the trip | the lock liquidates the strategy's positions |
| reconciliation breach | injected drift in the holdings is detected, and an audit event is written |
| restart restores | a second run on the same project starts, and its first reconciliation matches |
| outages survived | Redis, then Postgres, are stopped under the running engine and brought back |
| audit chain valid | `aq audit-log --verify` on the real Postgres |
| accounts isolated | two accounts run at once, with separate `account_id`s and state directories |

The injectors run only when three keys are all turned at once:

- `phase_v2.diagnostics.field_test.enabled` in the run's temporary config
- `AQ_FIELD_TEST=1` in its container
- a run that cannot reach real money: observation mode, or paper mode on Lean's own paper brokerage (`phase_v2.paper_trading.brokerage: lean_paper_brokerage`)

Live mode never qualifies. A property test checks that the injectors can never run where real money could move.

**What it cannot show** is a real broker: IB combo routing and fills, margin, assignment notices (#338), and the Coinbase venue (#192). Those wait for a key.
