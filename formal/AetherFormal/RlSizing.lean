import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Algebra.BigOperators.Group.List.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `risk/rl_sizing.py`

The tail of `rl_sizing_multiplier` (the clamp of the argmax action into `[min_rl_multiplier, max_rl_multiplier]`) and
`rl_shadow_guard_allows`. A bound that is not finite is `none`. V6.6.7 (#368): a band with `min > max` used to return
`min` (`max(1.2, min(raw, 1.0)) = 1.2`, an amplified size from a shrink-only control); it is now a no-op, and a window
below one bar reads one bar (`xs[-0:]` was the whole history).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.RlSizing

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

/-- (multiplier, scaled): `scaled = false` is the `(1.0, "rl_sizing_invalid_bounds")` no-op. -/
def clampMult (lo hi : Option α) (raw : α) : α × Bool :=
  match lo, hi with
  | some l, some h => if l ≤ h then (max l (min raw h), true) else (1, false)
  | _, _ => (1, false)

theorem clamp_within (l h raw : α) (hlh : l ≤ h) :
    l ≤ (clampMult (some l) (some h) raw).1 ∧ (clampMult (some l) (some h) raw).1 ≤ h := by
  simp only [clampMult, if_pos hlh]
  exact ⟨le_max_left _ _, max_le hlh (min_le_right _ _)⟩

theorem invalid_bounds_noop (l h raw : α) (hlh : h < l) : clampMult (some l) (some h) raw = (1, false) := by
  simp only [clampMult, if_neg (not_le.mpr hlh)]

theorem nonfinite_low_noop (hi : Option α) (raw : α) : clampMult none hi raw = (1, false) := by
  cases hi <;> rfl

theorem nonfinite_high_noop (lo : Option α) (raw : α) : clampMult lo none raw = (1, false) := by
  cases lo <;> rfl

/-- With `max_rl_multiplier ≤ 1` the control only ever shrinks a size, whatever the bounds and the action. -/
theorem shrink_only (lo hi : Option α) (raw : α) (h1 : ∀ h, hi = some h → h ≤ 1) : (clampMult lo hi raw).1 ≤ 1 := by
  cases lo with
  | none => cases hi <;> simp [clampMult]
  | some l =>
    cases hi with
    | none => simp [clampMult]
    | some h =>
      simp only [clampMult]
      split_ifs with hlh
      · exact max_le (hlh.trans (h1 h rfl)) ((min_le_right _ _).trans (h1 h rfl))
      · exact le_refl _

/-- The last `max 1 w` bars (all of them when fewer exist). -/
def recentWindow (xs : List α) (w : Int) : List α := xs.drop (xs.length - (max 1 w).toNat)

def guardAllows (enabled : Bool) (xs : List α) (w : Int) (tol : α) : Bool :=
  if enabled then decide (-tol ≤ (recentWindow xs w).sum) else true

theorem guard_off_allows (xs : List α) (w : Int) (tol : α) : guardAllows false xs w tol = true := rfl

theorem nonpos_window_reads_one_bar (xs : List α) (w : Int) (hw : w ≤ 0) : recentWindow xs w = recentWindow xs 1 := by
  simp only [recentWindow, max_eq_left (show w ≤ 1 by omega), max_self]

theorem window_length_le (xs : List α) (w : Int) : (recentWindow xs w).length ≤ (max 1 w).toNat := by
  simp only [recentWindow, List.length_drop]
  omega

/-- The window is the newest bars: it is a suffix of the history. -/
theorem window_is_suffix (xs : List α) (w : Int) : recentWindow xs w <:+ xs := by
  simp only [recentWindow]
  exact List.drop_suffix _ _

end AetherFormal.RlSizing
