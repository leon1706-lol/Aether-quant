import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `risk/forex_risk.py`

`cap_forex_target_to_book_weight(target_weight, book_weight)`: the margin-driven forex size is capped at the weight the
book gave the pair, keeping its sign; a non-finite input (`none`) is no trade (V6.6.7, #376).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.ForexCap

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def capForex (target book : Option α) : α :=
  match target, book with
  | some t, some b => if |t| ≤ |b| then t else if 0 < t then |b| else -|b|
  | _, _ => 0

theorem abs_le_book (t b : α) : |capForex (some t) (some b)| ≤ |b| := by
  simp only [capForex]
  split_ifs with h1 h2
  · exact h1
  · rw [abs_abs]
  · rw [abs_neg, abs_abs]

theorem sign_kept (t b : α) : 0 ≤ t * capForex (some t) (some b) := by
  simp only [capForex]
  have hb : 0 ≤ |b| := abs_nonneg b
  split_ifs with h1 h2
  · exact mul_self_nonneg t
  · exact mul_nonneg h2.le hb
  · push_neg at h2
    nlinarith

theorem shrinks (t b : α) : |capForex (some t) (some b)| ≤ |t| := by
  simp only [capForex]
  split_ifs with h1 h2
  · exact le_refl _
  · push_neg at h1; rw [abs_abs]; exact h1.le
  · push_neg at h1; rw [abs_neg, abs_abs]; exact h1.le

theorem idempotent (t b : α) : capForex (some (capForex (some t) (some b))) (some b) = capForex (some t) (some b) := by
  have h := abs_le_book t b
  generalize capForex (some t) (some b) = c at h ⊢
  simp only [capForex, if_pos h]

theorem nonfinite_zero (b : Option α) : capForex none b = 0 := by
  cases b <;> rfl

theorem nonfinite_book_zero (t : Option α) : capForex t none = 0 := by
  cases t <;> rfl

end AetherFormal.ForexCap
