# Research cycle

Research here is pre-registered. A round's rules are hashed before any score is computed. Every trial counts in the deflated Sharpe's N, whether it ran or not. A survivor is frozen once, and then reads its holdout once. Generations of models share the book: a newcomer starts small and earns capital on a fixed glide, while a decaying or tripped generation loses it.

```python
from aether_quant import cycle

policy = cycle.GlidePolicy(glide_sessions=252, entry_share=0.30, retire_share=0.05)
shares = {"old": 1.0, "new": 0.0}
for _ in range(126):
    shares = cycle.update_generation_shares(shares, {"old": "active", "new": "ramping"}, {}, {}, policy)
print(shares)
book = cycle.blend_generation_rows({"old": {"BTCUSD": 0.02}, "new": {"ETHUSD": 0.02}}, shares)
```

| Piece | Where |
|---|---|
| A round: score, placebo, gate, PBO, freeze, hold, report | `cycle.RoundSpec` and the `stage_*` functions; `aq cycle research <stage>` |
| What is due today | `cycle.due_actions`; `aq cycle status` |
| Decay of a generation's record | `cycle.decay_state` (CUSUM against its expected Sharpe) |
| Admission: who may hold capital | `cycle.next_stage`, `cycle.share_cap` (R-ADMIT1, proved in `Admission.lean`) |
| The forward record | `cycle.resolve_session`; the scheduled `forward-ledger.yml` workflow |

The ledger rows are hash-chained, and the chain is checked before any figure is read.
