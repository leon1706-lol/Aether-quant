# formal/ — Lean 4 proofs of the safety-critical pure functions (V6.4.3)

A Lake project (`AetherFormal`, Lean 4 + Mathlib) that models the pure Python functions the live order path and the
offline simulator share, proves their invariants, and computes differential test cases from the same models. The
folder is called `formal/` because "lean" already means the QuantConnect engine everywhere else in this repo.

## Setup (dev PC)

```powershell
cd formal
lake exe cache get          # Mathlib's prebuilt .olean files (~5 GB under formal/.lake/, never compiled here)
cd ..
aq prove                    # lake build AetherFormal
aq prove --regen-cases      # also rewrite aether_quant/_formal_cases/*.json (after any spec edit)
aq prove --check-sorry      # no Lean needed: fails on any sorry / admit
```

`lean-toolchain` pins Lean `v4.35.0`, the toolchain of the Mathlib release in `lakefile.toml` (`v4.35.0`). Close Docker
and other large apps first: elaborating a file that imports Mathlib takes 1-2 GB. If the cache unpack is interrupted,
`lake build` starts compiling Mathlib instead (hours); stop it and run `lake exe cache get` again until the
`.lake/packages/mathlib/.lake/build/lib/lean/Mathlib` olean count matches the `.lean` count.

## Method

Each model is generic over an ordered field (`[Field α] [LinearOrder α] [IsStrictOrderedRing α]`), so one proof covers
`ℚ` and `ℝ` (`Real.lean` restates the headline theorems at `ℝ`). `GenCases.lean` runs the models at `ℚ` (exact
arithmetic) on seeded pseudo-random inputs plus fixed edge cases and writes `aether_quant/_formal_cases/<target>.json`;
`tests/test_formal_differential_<target>.py` runs the Python function on the same inputs and compares (tolerance
1e-12 / 1e-9 relative, exact for strings and booleans). `tests/test_formal_cases_drift.py` fails when a spec changed
after its cases were generated. CI runs the differential tests (no Lean needed); `aq prove` runs locally.

**Scope.** The proofs cover the algorithm over ordered fields. IEEE rounding is covered by the differential tolerance,
NaN / inf by `tests/test_v643_formal_findings.py` (the Python guards). No NaN guard is ever removed on the strength of a
proof over ℝ. Out of scope: HRP (scipy linkage) and the rank-book simulator as a whole (it reuses the verified
book-construction and neutrality functions).

## Theorem index

| Spec | Python | Theorems |
|---|---|---|
| `OrderGate.lean` | `execution/order_gate.py` | `observation_never`, `unknown_never`, `permit_iff`, `risk_lock_blocks`, `cash_sweep_never_in_observation`, `resolveRuntimeMode_ne_other`, `resolveBps_nonneg`, `resolveBps_le`, `slippageAmount_nonneg`, `fill_slippage_bounded` |
| `HashChain.lean` | `audit/hash_chain.py` | `verify_ok_iff`, `verifyFrom_shape`, `verifyFrom_index_minimal`, `valid_append_one`, `valid_mem`, `payload_tamper_detected`, `delete_detected`, `truncation_undetected` (finding) |
| `BookNeutrality.lean` | `portfolio/book_neutrality.py` | `neutralize_shrinks` (shrink-only, sign-preserving, symbols kept), `name_cap`, `neutralize_gross`, `sector_cap_after_capSectors`, `sector_cap_with_reapply`, `dollarNeutral_balanced`, `grossCap_balanced`, `sector_cap_counterexample` (finding), `old_clip_flips_shorts` (finding) |
| `BookConstruction.lean` | `portfolio/book_construction.py` | `ceilDiv_bounds`, `tranche_gross_sum`, `partialAdjust_gross`, `partialAdjust_within_cap`, `combine_gross`, `classCap_outside`, `classCap_per_name`, `classCap_gross`, `selectBook_lengths`, `selectBook_long_only`, `selectBook_members`, `selectBook_disjoint` |
| `RiskControls.lean` | `risk_controls.py` | `capTargetWeight_within`, `capTargetWeight_no_flip`, `capTargetWeight_shrinks`, `capTargetWeight_blocked_iff`, `capTargetWeight_nonfinite`, `drawdownLock_monotone`, `drawdownLock_total_first`, `incremental_lands_on_target` |
| `KillSwitch.lean` | `risk/kill_switch.py` | `disabled_never_trips`, `tripped_iff`, `critical_iff`, `triggers_monotone`, `confirm_bars` |
| `PositionSizing.lean` | `risk/position_sizing.py` | `topologyMult_mem`, `rankMult_mem`, `costMult_mem`, `costMult_amplifies_when_misconfigured` (finding), `size_le_cap`, `size_no_flip`, `size_nonfinite`, `old_negative_product_escapes_cap` (finding) |
| `CostModel.lean` | `execution/cost_model.py` | `fillFee_between`, `roundTripCost_mono_commission`, `roundTripCost_mono_floor`, `edge_median_zero`, `edge_antisymmetric`, `passes_fail_open`, `passes_mono_cost` |
| `Reconciliation.lean` | `execution/reconciliation.py` | `report_sound`, `report_disjoint`, `report_partition`, `maxDrift_bounds`, `matched_within_tolerance` |
| `SleeveGuard.lean` | `portfolio/sleeve_guard.py` | `trailingDrawdown_nonneg`, `trailingDrawdown_nonpos_lookback`, `trailingDrawdown_le_losses` |
| `JsonSafety.lean` | `json_safety.sanitize_json_finite` | `sanitize_finite`, `sanitize_idem`, `sanitizeObj_keys` |

## Findings (Problems.md, V6.4.3)

- **Sector cap after the dollar step:** a sector holding a long and a short can end above `sector_max_net_weight`
  (`sector_cap_counterexample`). New option `phase_v2.portfolio_book.neutrality.reapply_sector_cap_after_dollar_neutral`
  (default `false`) makes the cap hold at the end (`sector_cap_with_reapply`).
- **Non-positive per-name cap:** zeroed the book (0) or made every weight a long of |cap| (< 0); now skipped like the
  other caps.
- **`cap_target_weight(NaN)`** came out as a full short of the remaining capacity; **a NaN base target** sized to NaN; **a
  negative multiplier product** escaped `max_position_weight` on the wrong side; **`trailing_drawdown(lookback=0)`** read
  the whole history. All fixed fail-safe.
- **Hash-chain truncation** is invisible to `verify_chain`; `expected_tail_hash` anchors it.

## Adding a target

1. `AetherFormal/<Name>.lean`: the model, branch for branch like the Python, and its theorems (no `sorry`).
2. Import it in `AetherFormal.lean` and add a generator to `GenCases.lean` (`all`).
3. `tests/test_formal_differential_<target>.py`, registered in the `formal` bucket of `aq_cli.py`, and the target in
   `tests/test_formal_cases_drift.py`.
4. `aq prove --regen-cases`, then `aq test --formal`.
