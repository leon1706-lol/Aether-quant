import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `risk_controls.py`

`cap_target_weight`, `assess_drawdown_lock`, `projected_signed_quantity`, `compute_incremental_order_quantity`.
A non-finite target is `none` (V6.4.3: it used to come out as a full short of the remaining capacity).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.RiskControls

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

/-- `cap_target_weight(target, current_exposure, exposure_cap) -> (weight, blocked)`. -/
def capTargetWeight (target : Option α) (cur cap : α) : α × Bool :=
  match target with
  | none => (0, true)
  | some w =>
    let rem := max 0 (cap - cur)
    if |w| ≤ rem then (w, false)
    else if rem ≤ 0 then (0, true)
    else ((if 0 ≤ w then 1 else -1) * rem, false)

theorem capTargetWeight_within (w cur cap : α) : |(capTargetWeight (some w) cur cap).1| ≤ max 0 (cap - cur) := by
  unfold capTargetWeight
  simp only
  split_ifs with h1 h2 h3
  · exact h1
  · simp
  · rw [one_mul, abs_of_nonneg (le_max_left _ _)]
  · rw [abs_mul, abs_neg, abs_one, one_mul, abs_of_nonneg (le_max_left _ _)]

theorem capTargetWeight_no_flip (w cur cap : α) : 0 ≤ w * (capTargetWeight (some w) cur cap).1 := by
  unfold capTargetWeight
  simp only
  have hr : 0 ≤ max 0 (cap - cur) := le_max_left _ _
  split_ifs with h1 h2 h3
  · exact mul_self_nonneg w
  · simp
  · rw [one_mul]; exact mul_nonneg h3 hr
  · push_neg at h3
    nlinarith

theorem capTargetWeight_shrinks (w cur cap : α) : |(capTargetWeight (some w) cur cap).1| ≤ |w| := by
  unfold capTargetWeight
  simp only
  split_ifs with h1 h2 h3
  · exact le_refl _
  · simp
  · push_neg at h1
    rw [one_mul, abs_of_nonneg (le_max_left _ _)]; exact h1.le
  · push_neg at h1
    rw [abs_mul, abs_neg, abs_one, one_mul, abs_of_nonneg (le_max_left _ _)]; exact h1.le

theorem capTargetWeight_blocked_iff (w cur cap : α) :
    (capTargetWeight (some w) cur cap).2 = true ↔ (max 0 (cap - cur) < |w| ∧ max 0 (cap - cur) = 0) := by
  unfold capTargetWeight
  simp only
  have hr : 0 ≤ max 0 (cap - cur) := le_max_left _ _
  split_ifs with h1 h2
  · simp only [Bool.false_eq_true, false_iff, not_and]; intro h; exact absurd h (not_lt.mpr h1)
  · simp only [true_iff]; exact ⟨not_le.mp h1, le_antisymm h2 hr⟩
  · simp only [Bool.false_eq_true, false_iff, not_and]; intro _ h; exact h2 (le_of_eq h)

/-- A non-finite target never trades. -/
theorem capTargetWeight_nonfinite (cur cap : α) : capTargetWeight (none : Option α) cur cap = (0, true) := rfl

/-- `assess_drawdown_lock(daily, total, max_daily, max_total)`: total breach first, then daily. -/
def drawdownLock (daily total maxDaily maxTotal : α) : Bool × Option String :=
  if total ≤ -maxTotal then (true, some "total_drawdown_limit_breached")
  else if daily ≤ -maxDaily then (true, some "daily_drawdown_limit_breached")
  else (false, none)

/-- A deeper drawdown never unlocks. -/
theorem drawdownLock_monotone (d t d' t' mD mT : α) (hd : d' ≤ d) (ht : t' ≤ t)
    (h : (drawdownLock d t mD mT).1 = true) : (drawdownLock d' t' mD mT).1 = true := by
  unfold drawdownLock at h ⊢
  by_cases h1 : t ≤ -mT
  · rw [if_pos (le_trans ht h1)]
  · rw [if_neg h1] at h
    by_cases h2 : d ≤ -mD
    · by_cases h3 : t' ≤ -mT
      · rw [if_pos h3]
      · rw [if_neg h3, if_pos (le_trans hd h2)]
    · rw [if_neg h2] at h
      exact absurd h (by simp)

theorem drawdownLock_total_first (d t mD mT : α) (ht : t ≤ -mT) :
    drawdownLock d t mD mT = (true, some "total_drawdown_limit_breached") := by
  simp [drawdownLock, ht]

/-- `compute_incremental_order_quantity`: the delta lands exactly on the target (never overshoots). -/
theorem incremental_lands_on_target (target held : α) : held + (target - held) = target := by ring

/-- `projected_signed_quantity` (finite inputs): held plus the open order. -/
def projected (held openQ : Option α) : α := held.getD 0 + openQ.getD 0

end AetherFormal.RiskControls
