import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `risk/kelly.kelly_fraction`

V6.6.10 (W4, batch A): `fraction * mean / variance`, clipped to [-|cap|, |cap|], zero for a non-positive variance or fraction
(non-finite inputs return 0 in Python before this point). The size never leaves its cap, follows the sign of the mean, and grows
with the mean.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.Kelly

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def kelly (mu var share cap : α) : α :=
  if var ≤ 0 ∨ share ≤ 0 then 0 else min (max (share * mu / var) (-|cap|)) |cap|

theorem within_cap (mu var share cap : α) : -|cap| ≤ kelly mu var share cap ∧ kelly mu var share cap ≤ |cap| := by
  unfold kelly
  split_ifs
  · exact ⟨by simp, abs_nonneg _⟩
  · refine ⟨le_min (le_max_right _ _) (by simp), min_le_right _ _⟩

theorem zero_without_variance (mu var share cap : α) (h : var ≤ 0) : kelly mu var share cap = 0 := by
  simp [kelly, h]

theorem zero_without_fraction (mu var share cap : α) (h : share ≤ 0) : kelly mu var share cap = 0 := by
  simp [kelly, h]

/-- A non-negative mean never sizes short. -/
theorem nonneg_of_mean (mu var share cap : α) (hmu : 0 ≤ mu) : 0 ≤ kelly mu var share cap := by
  unfold kelly
  split_ifs with h
  · exact le_refl 0
  · push Not at h
    have hx : 0 ≤ share * mu / var := div_nonneg (mul_nonneg h.2.le hmu) h.1.le
    exact le_min (le_trans hx (le_max_left _ _)) (abs_nonneg _)

/-- A larger mean never sizes smaller. -/
theorem mono_mean (mu mu' var share cap : α) (hm : mu ≤ mu') : kelly mu var share cap ≤ kelly mu' var share cap := by
  unfold kelly
  split_ifs with h
  · exact le_refl 0
  · push Not at h
    have hx : share * mu / var ≤ share * mu' / var := div_le_div_of_nonneg_right (mul_le_mul_of_nonneg_left hm h.2.le) h.1.le
    exact min_le_min_right _ (max_le_max_right _ hx)

end AetherFormal.Kelly
