# CONTINUE HERE — V5.4.5 COMPLETE 2026-08-26 (docs + pre-backtest safety audit)

Nothing pending from this round. Two rounds shipped under V5.4.5:

## Round 1 — documentation debt paydown
1. Main README restructured: Quickstart / Current Status / Contributing /
   Continuous Integration sections removed; Runbook moved into RUNBOOK.md;
   Open Source Files at its TOC position (author footer ends the file);
   TOC rebuilt; intro/CLI intros tightened; all six auto-generated result
   sections verified marker-complete and CLI-refreshable.
2. Sub-README coverage complete (.devcontainer/.githooks added);
   development/README.md index completed; SECURITY.md + REPRODUCIBILITY.md
   fixes; project_structure tree extended.

## Round 2 — live-execution structural review (pre-Lean-backtest audit)
Findings + fixes, full detail in development/Problems.md #116-#119:
1. **#116** cost gate charged ONE side's commission against a round-trip
   contract (config is enabled+calibrated -> actively affected decisions);
   paper mode ignored `risk_locks_healthy` (tripped kill switch couldn't
   stop paper broker orders). Both fixed.
2. **#117** NaN-propagation family: kill-switch triggers, fill-slippage
   clamp, reconciliation false-clean, net-edge reason, book rank/spread-veto
   eligibility, HRP covariance inputs, gross-cap erasure, position floor>
   cap - all hardened (`isfinite` normalization, fail-closed where it's a
   safety trigger).
3. **#118** HRP equal-weight fallback broke dollar-neutrality on asymmetric
   two-sided books; fallback now shares the main path's per-leg totals.
4. **#119** V5.4.1 RL asymmetric-penalty reward was dead code at its call
   site; wired through config (`asymmetric_penalty_weight`, default 1.0).
5. Audited-clean: bar_synthesis parity, RL state-vector parity,
   multiplier clamps/direction preservation, kill-switch window math +
   trip stickiness, override precedence, neutrality step ordering.

Verified: python **2858/2858** (+24 new tests pinning every fix), ruff clean.

## For the upcoming Lean backtest
- Backtest-mode order gating is unchanged by design (unrestricted), so the
  audit does not alter what runs - but the cost gate IS more conservative
  now (~2x commission leg), so expect somewhat fewer marginal trades vs the
  August 19 run.
- Default `allocation_method` stays "rank"; when flipping to "hrp", the
  fallback paths are now dollar-neutral-safe.
- After a good backtest run: `aq backtest` refreshes the README sections
  automatically; then rebuild the engine docker image before next compose
  use (it predates V5.4.x code); commit before tagging.
- Optional follow-up NOT scheduled: runtime NaN guard in rl_sizing argmax
  (bounded, default-off overlay) - documented in #117, left as-is.
