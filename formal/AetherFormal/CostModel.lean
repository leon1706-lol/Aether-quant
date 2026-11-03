import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `execution/cost_model.py`

`expected_fill_fee_bps`, `estimate_round_trip_cost_bps`, `expected_edge_bps`, and the pass/fail core of
`build_net_edge_decision` (finite inputs; its non-finite branches fail closed and are covered by the Python tests).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.CostModel

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def fillFee (isLimit : Bool) (fillRate maker taker : α) : α :=
  if isLimit then
    let r := min 1 (max 0 fillRate)
    r * maker + (1 - r) * taker
  else taker

/-- A limit order's expected fee is a blend of the maker and taker rates. -/
theorem fillFee_between (isLimit : Bool) (fillRate maker taker : α) :
    min maker taker ≤ fillFee isLimit fillRate maker taker ∧ fillFee isLimit fillRate maker taker ≤ max maker taker := by
  unfold fillFee
  cases isLimit
  · exact ⟨min_le_right _ _, le_max_right _ _⟩
  · simp only [if_true]
    have r0 : 0 ≤ min 1 (max 0 fillRate) := le_min zero_le_one (le_max_left _ _)
    have r1 : min 1 (max 0 fillRate) ≤ 1 := min_le_left _ _
    have hm1 := min_le_left maker taker
    have hm2 := min_le_right maker taker
    have hM1 := le_max_left maker taker
    have hM2 := le_max_right maker taker
    constructor <;> nlinarith

/-- `estimate_round_trip_cost_bps`: liquidity round trip + both sides' commission (with the dollar floor) + buffer. -/
def roundTripCost (liquidityFraction commissionBps minUsd orderValue extraBps : α) : α :=
  liquidityFraction * 10000 +
    (if 0 < orderValue then 2 * max (orderValue * commissionBps / 10000) minUsd / orderValue * 10000 else 0) + extraBps

theorem roundTripCost_mono_commission (lf c c' m v x : α) (h : c ≤ c') (hv : 0 < v) :
    roundTripCost lf c m v x ≤ roundTripCost lf c' m v x := by
  unfold roundTripCost
  simp only [hv, if_true]
  have : max (v * c / 10000) m ≤ max (v * c' / 10000) m :=
    max_le_max (div_le_div_of_nonneg_right (mul_le_mul_of_nonneg_left h hv.le) (by norm_num)) (le_refl m)
  have h2 : 2 * max (v * c / 10000) m / v ≤ 2 * max (v * c' / 10000) m / v :=
    div_le_div_of_nonneg_right (by linarith) hv.le
  nlinarith

theorem roundTripCost_mono_floor (lf c m m' v x : α) (h : m ≤ m') (hv : 0 < v) :
    roundTripCost lf c m v x ≤ roundTripCost lf c m' v x := by
  unfold roundTripCost
  simp only [hv, if_true]
  have : max (v * c / 10000) m ≤ max (v * c / 10000) m' := max_le_max (le_refl _) h
  have h2 : 2 * max (v * c / 10000) m / v ≤ 2 * max (v * c / 10000) m' / v :=
    div_le_div_of_nonneg_right (by linarith) hv.le
  nlinarith

/-- `expected_edge_bps` (finite rank). -/
def edge (rank perUnit : α) (holding horizon : Nat) (direction : Int) : α :=
  if horizon = 0 then 0
  else perUnit * ((rank - 1 / 2) * 2) * min 1 ((holding : α) / horizon) * (if 0 ≤ direction then 1 else -1)

theorem edge_median_zero (perUnit : α) (h t : Nat) (d : Int) : edge (1 / 2) perUnit h t d = 0 := by
  unfold edge; split_ifs <;> ring

/-- The short side's edge is the long side's, negated. -/
theorem edge_antisymmetric (rank perUnit : α) (h t : Nat) : edge rank perUnit h t (-1) = -edge rank perUnit h t 1 := by
  unfold edge
  by_cases ht : t = 0
  · simp [ht]
  · rw [if_neg ht, if_neg ht, if_neg (by decide : ¬ (0 : Int) ≤ -1), if_pos (by decide : (0 : Int) ≤ 1)]
    ring

/-- The pass/fail core: trade iff edge - cost clears the minimum. -/
def passes (enabled : Bool) (perUnit : α) (rank : Option α) (edgeBps costBps minNet : α) : Bool :=
  if !enabled || perUnit = 0 || rank.isNone then true else decide (minNet ≤ edgeBps - costBps)

/-- Fail-open: a disabled or uncalibrated gate never blocks a trade. -/
theorem passes_fail_open (perUnit : α) (rank : Option α) (e c m : α) : passes false perUnit rank e c m = true := by
  simp [passes]

/-- Monotone in cost: a trade that passes at cost c passes at every lower cost. -/
theorem passes_mono_cost (enabled : Bool) (perUnit : α) (rank : Option α) (e c c' m : α) (h : c' ≤ c)
    (hp : passes enabled perUnit rank e c m = true) : passes enabled perUnit rank e c' m = true := by
  unfold passes at *
  split_ifs at hp ⊢
  · rfl
  · simp only [decide_eq_true_eq] at hp ⊢; linarith

end AetherFormal.CostModel
