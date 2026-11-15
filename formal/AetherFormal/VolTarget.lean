import Mathlib.Algebra.BigOperators.Ring.List
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Algebra.BigOperators.Group.List.Basic
import Mathlib.Algebra.Order.BigOperators.Group.List
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `risk/vol_target.py`

`volatility_target_weights` after the risk is known: the book scaled to the volatility target, then its gross capped
at `max_leverage`. `risk` is `sqrt(w' Σ w * annualization)`, `none` when it is not finite (the square root stays
outside the model). V6.6.7 (#376): a zero target is a flat book (it returned the weights unscaled), and a negative
target or leverage is refused before this point, so both are `0 ≤` here.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.VolTarget

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def gross (ws : List α) : α := (ws.map abs).sum

def scaleOf (risk : Option α) (target : α) : α :=
  match risk with
  | some r => if 0 < r ∧ 0 < target then target / r else 1
  | none => 1

def volTarget (ws : List α) (risk : Option α) (target maxLev : α) : List α :=
  if target = 0 then ws.map (fun _ => 0)
  else
    let scaled := ws.map (· * scaleOf risk target)
    if maxLev < gross scaled ∧ 0 < gross scaled then scaled.map (· * (maxLev / gross scaled)) else scaled

theorem gross_nonneg (ws : List α) : 0 ≤ gross ws :=
  List.sum_nonneg (fun x hx => by obtain ⟨w, -, rfl⟩ := List.mem_map.mp hx; exact abs_nonneg w)

theorem gross_map_mul (ws : List α) (k : α) (hk : 0 ≤ k) : gross (ws.map (· * k)) = gross ws * k := by
  simp only [gross, List.map_map, Function.comp_def, abs_mul, abs_of_nonneg hk]
  rw [List.sum_map_mul_right]

theorem scaleOf_nonneg (risk : Option α) (target : α) : 0 ≤ scaleOf risk target := by
  cases risk with
  | none => exact zero_le_one
  | some r =>
    simp only [scaleOf]
    split_ifs with h
    · exact div_nonneg h.2.le h.1.le
    · exact zero_le_one

/-- The book is only ever scaled, by one factor that is not negative: no name flips, and the proportions hold. -/
theorem uniform_scale (ws : List α) (risk : Option α) (target maxLev : α) (hL : 0 ≤ maxLev) :
    ∃ c, 0 ≤ c ∧ volTarget ws risk target maxLev = ws.map (· * c) := by
  unfold volTarget
  dsimp only
  split_ifs with h0 h1
  · exact ⟨0, le_refl _, by simp⟩
  · refine ⟨scaleOf risk target * (maxLev / gross (ws.map (· * scaleOf risk target))), ?_, ?_⟩
    · exact mul_nonneg (scaleOf_nonneg _ _) (div_nonneg hL h1.2.le)
    · simp [List.map_map, Function.comp_def, mul_assoc]
  · exact ⟨scaleOf risk target, scaleOf_nonneg _ _, rfl⟩

/-- The gross never ends above `max_leverage`. -/
theorem gross_le_leverage (ws : List α) (risk : Option α) (target maxLev : α) (hL : 0 ≤ maxLev) :
    gross (volTarget ws risk target maxLev) ≤ maxLev := by
  unfold volTarget
  dsimp only
  split_ifs with h0 h1
  · simp [gross, hL]
  · rw [gross_map_mul _ _ (div_nonneg hL h1.2.le), mul_div_cancel₀ _ h1.2.ne']
  · push_neg at h1
    by_contra hc
    push_neg at hc
    have h2 := h1 hc
    have h3 := gross_nonneg (ws.map (· * scaleOf risk target))
    linarith

theorem target_zero_flat (ws : List α) (risk : Option α) (maxLev : α) : volTarget ws risk 0 maxLev = ws.map (fun _ => 0) := by
  simp [volTarget]

end AetherFormal.VolTarget
