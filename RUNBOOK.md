# Runbook — Operational Procedures

What to do when things go wrong. Each section: **Symptoms → Diagnosis → Resolution**.

---

## 1. Kill switch trips repeatedly (>5× per run)

**Symptoms:** `kill_switch_tripped` events in `aq audit-log`, book locked to `reduce_risk` for most decisions, Sharpe degrading.

```powershell
aq audit-log --verify
aq kill-switch --history
```

**Diagnosis:** check whether trips cluster in a known bad era (Apr–Sep 2019, Dec 2019–Mar 2020) or are spread uniformly. Uniform = threshold too sensitive; clustered = genuine regime loss.

**Resolution:**
- If clustered: no action needed — the system correctly disengaged. Review after run completes.
- If uniform: consider raising `phase_v2.risk.kill_switch.min_rolling_sharpe` (currently 0.30). Run `aq evaluate --replay-kill-switch` to test candidate thresholds offline first.

---

## 2. Reconciliation breaches

**Symptoms:** `reconciliation_breach` events; positions diverging from intended weights.

```powershell
aq evaluate --reconcile-book-history --replay-hysteresis
```

**Diagnosis:** compare overlap fraction against historical baseline (~50%). A sudden drop suggests a data or execution bug, not model degradation.

**Resolution:** if drift is small (<10%) and stable, it's within normal slippage tolerance. If large and growing, check for missing factor files (`data/reference/`) or stale scaler stats.

---

## 3. Data gaps / missing bars

**Symptoms:** symbols absent from universe snapshot; prediction provenance counter shows high multitask fallback rate.

**Diagnosis:** check `data/equity/*/daily/*.zip` files exist for affected tickers and cover the expected date range.

**Resolution:** re-fetch via `aq fetch <type> --ticker <ticker> --apply`. For crypto, verify the exchange actually listed the pair (BNBUSD/TRXUSD were never on Coinbase).

---

## 4. Sequence model OOM / silent fallback

**Symptoms:** `prediction-provenance: sequence_served=0 multitask_fallback=N` at shutdown.

**Diagnosis:** sequence model OOM'd during tensor construction or wasn't loaded. Check train.log for `_ArrayMemoryError`.

**Resolution:** close Docker Desktop before training (frees ~2GB RAM). On codespace, use CPU-only PyTorch index. The system degrades safely to multitask rank_20d — no action required unless quality degrades measurably.

---

## 5. System losing money for 5+ consecutive days

**Symptoms:** sustained negative daily returns; drawdown approaching total-drawdown limit.

**Diagnosis:**
1. Check kill-switch history: is it tripping? (If yes, it's working.)
2. Run `aq evaluate --rank-book` offline: does the current model still show positive net Sharpe?
3. Compare current IC vs training metrics: has rank_20d IC decayed below 0.02?

**Resolution:**
- Offline eval still positive → live-vs-offline gap widened; check reconciliation for new divergences.
- Offline eval also negative → model degraded; trigger a retrain via codespace.
- Both positive but live losing → execution-side issue; review fills, slippage, fees in order-events log.
