import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/cash_sweep.py` and `portfolio/class_sleeve.py`

`cash_sweep_target_weight` (the T-bill sweep inside the margin limit, the cash limit and `max_weight`),
`advance_strategy_value` (the value the risk controls read) and `resize_below_minimum`. V6.6.7 (#374): a session that
lost more than the strategy held gave a negative value (now floored at zero, a 100% drawdown), and a NaN minimum trade
(`none`) let a resize through.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.CashSweep

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def byMargin (lev mbuf margin resMargin : α) : α := lev * (1 - mbuf - margin - resMargin)

def byCash (longW shortW resLong resShort cbuf : α) : α := 1 - |longW| + |shortW| - resLong + min resShort resLong - cbuf

def target (longW shortW margin resLong resShort resMargin lev mbuf cbuf maxW : α) : α :=
  max 0 (min maxW (min (byMargin lev mbuf margin resMargin) (byCash longW shortW resLong resShort cbuf)))

theorem target_nonneg (l s m rl rs rm lev mb cb mw : α) : 0 ≤ target l s m rl rs rm lev mb cb mw := le_max_left _ _

theorem target_le_max (l s m rl rs rm lev mb cb mw : α) (h : 0 ≤ mw) : target l s m rl rs rm lev mb cb mw ≤ mw :=
  max_le h (min_le_left _ _)

theorem target_le_margin_limit (l s m rl rs rm lev mb cb mw : α) (h : 0 ≤ byMargin lev mb m rm) :
    target l s m rl rs rm lev mb cb mw ≤ byMargin lev mb m rm :=
  max_le h ((min_le_right _ _).trans (min_le_left _ _))

/-- More margin in use never raises the sweep. -/
theorem anti_mono_margin (l s m m' rl rs rm lev mb cb mw : α) (hlev : 0 ≤ lev) (hm : m ≤ m') :
    target l s m' rl rs rm lev mb cb mw ≤ target l s m rl rs rm lev mb cb mw := by
  have : byMargin lev mb m' rm ≤ byMargin lev mb m rm := by
    unfold byMargin; exact mul_le_mul_of_nonneg_left (by linarith) hlev
  exact max_le_max_left _ (min_le_min_left _ (min_le_min_right _ this))

/-- A larger margin reserve never raises the sweep. -/
theorem anti_mono_reserve_margin (l s m rl rs rm rm' lev mb cb mw : α) (hlev : 0 ≤ lev) (hr : rm ≤ rm') :
    target l s m rl rs rm' lev mb cb mw ≤ target l s m rl rs rm lev mb cb mw := by
  have : byMargin lev mb m rm' ≤ byMargin lev mb m rm := by
    unfold byMargin; exact mul_le_mul_of_nonneg_left (by linarith) hlev
  exact max_le_max_left _ (min_le_min_left _ (min_le_min_right _ this))

/-- `advance_strategy_value` after its first session: a total that is not positive keeps the previous value. -/
def advance (value t0 s0 total sweep : α) : α :=
  if total ≤ 0 ∨ t0 ≤ 0 then value
  else max 0 (value * (1 + ((total - t0) - (sweep - s0)) / t0))

theorem value_nonneg (value t0 s0 total sweep : α) (h : 0 ≤ value) : 0 ≤ advance value t0 s0 total sweep := by
  unfold advance
  split_ifs
  · exact h
  · exact le_max_left _ _

/-- `resize_below_minimum(delta_units, price, min_trade_usd)`; a non-finite minimum is `none`. -/
def resizeBelow (delta price : α) (minUsd : Option α) : Bool :=
  match minUsd with
  | none => true
  | some m => if m ≤ 0 then false else decide (|delta| * price < m)

theorem nonfinite_minimum_blocks (delta price : α) : resizeBelow delta price none = true := rfl

theorem nonpositive_minimum_disables (delta price m : α) (h : m ≤ 0) : resizeBelow delta price (some m) = false := by
  simp [resizeBelow, h]

end AetherFormal.CashSweep
