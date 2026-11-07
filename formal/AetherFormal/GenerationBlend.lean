import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Algebra.Order.BigOperators.Group.Finset
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/generation_blend.py`

Several generations share one book. A blend is convex, so a per-name cap or a gross cap that every generation keeps holds for the book, whichever generation holds what:
`blend_abs_le_cap`, `blend_gross_le_cap`. For one incumbent and one ramping generation, `update` is `update_generation_shares`: shares stay non-negative, sum to at most one, the gainer
stays under its cap, and a generation under `retire` holds nothing.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.GenerationBlend

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]
variable {ι κ : Type*} [Fintype ι] [Fintype κ]

/-- One name's weight in the book: each generation's weight times its share. -/
def blend (s : ι → α) (w : ι → κ → α) (k : κ) : α := ∑ i, s i * w i k

theorem blend_abs_le_cap (s : ι → α) (w : ι → κ → α) (k : κ) (cap : α) (hs : ∀ i, 0 ≤ s i) (hsum : ∑ i, s i ≤ 1) (hcap0 : 0 ≤ cap) (hw : ∀ i, |w i k| ≤ cap) :
    |blend s w k| ≤ cap := by
  unfold blend
  calc |∑ i, s i * w i k| ≤ ∑ i, |s i * w i k| := Finset.abs_sum_le_sum_abs _ _
    _ = ∑ i, s i * |w i k| := by
        refine Finset.sum_congr rfl fun i _ => ?_
        rw [abs_mul, abs_of_nonneg (hs i)]
    _ ≤ ∑ i, s i * cap := Finset.sum_le_sum fun i _ => mul_le_mul_of_nonneg_left (hw i) (hs i)
    _ = (∑ i, s i) * cap := by rw [Finset.sum_mul]
    _ ≤ 1 * cap := mul_le_mul_of_nonneg_right hsum hcap0
    _ = cap := one_mul cap

theorem blend_gross_le_cap (s : ι → α) (w : ι → κ → α) (cap : α) (hs : ∀ i, 0 ≤ s i) (hsum : ∑ i, s i ≤ 1) (hcap0 : 0 ≤ cap) (hw : ∀ i, ∑ k, |w i k| ≤ cap) :
    ∑ k, |blend s w k| ≤ cap := by
  calc ∑ k, |blend s w k| ≤ ∑ k, ∑ i, s i * |w i k| := by
        refine Finset.sum_le_sum fun k _ => ?_
        unfold blend
        calc |∑ i, s i * w i k| ≤ ∑ i, |s i * w i k| := Finset.abs_sum_le_sum_abs _ _
          _ = ∑ i, s i * |w i k| := by
              refine Finset.sum_congr rfl fun i _ => ?_
              rw [abs_mul, abs_of_nonneg (hs i)]
    _ = ∑ i, s i * ∑ k, |w i k| := by
        rw [Finset.sum_comm]
        exact Finset.sum_congr rfl fun i _ => (Finset.mul_sum _ _ _).symm
    _ ≤ ∑ i, s i * cap := Finset.sum_le_sum fun i _ => mul_le_mul_of_nonneg_left (hw i) (hs i)
    _ = (∑ i, s i) * cap := by rw [Finset.sum_mul]
    _ ≤ 1 * cap := mul_le_mul_of_nonneg_right hsum hcap0
    _ = cap := one_mul cap

/-- What the gainer wants: its entry share the first time, then one step up, never past its cap. -/
def wanted (new cap entry step : α) : α := if new ≤ 0 then min cap entry else min cap (new + step)

def increase (new cap entry step : α) : α := max 0 (wanted new cap entry step - new)

/-- Idle capital goes first. -/
def fromTbills (old new cap entry step : α) : α := min (increase new cap entry step) (max 0 (1 - (old + new)))

/-- The rest comes from the incumbent, up to what it has. -/
def taken (old new cap entry step : α) : α := min (increase new cap entry step - fromTbills old new cap entry step) old

def oldAfter (old new cap entry step : α) : α := old - taken old new cap entry step

def newAfter (old new cap entry step : α) : α := new + fromTbills old new cap entry step + taken old new cap entry step

def retire (old new cap limit : α) : α × α := if 0 < old ∧ old < limit then (0, min cap (new + old)) else (old, new)

/-- One session of `update_generation_shares`, for an incumbent and a ramping generation. -/
def update (old new cap entry step limit : α) : α × α :=
  retire (oldAfter old new cap entry step) (newAfter old new cap entry step) cap limit

theorem increase_nonneg (new cap entry step : α) : 0 ≤ increase new cap entry step := le_max_left _ _

theorem fromTbills_nonneg (old new cap entry step : α) : 0 ≤ fromTbills old new cap entry step :=
  le_min (increase_nonneg _ _ _ _) (le_max_left _ _)

theorem fromTbills_le_increase (old new cap entry step : α) : fromTbills old new cap entry step ≤ increase new cap entry step := min_le_left _ _

theorem taken_nonneg (old new cap entry step : α) (hold : 0 ≤ old) : 0 ≤ taken old new cap entry step :=
  le_min (by linarith [fromTbills_le_increase old new cap entry step]) hold

theorem taken_le_old (old new cap entry step : α) : taken old new cap entry step ≤ old := min_le_right _ _

theorem oldAfter_nonneg (old new cap entry step : α) : 0 ≤ oldAfter old new cap entry step := by
  unfold oldAfter; linarith [taken_le_old old new cap entry step]

theorem newAfter_nonneg (old new cap entry step : α) (hold : 0 ≤ old) (hnew : 0 ≤ new) : 0 ≤ newAfter old new cap entry step := by
  unfold newAfter; linarith [taken_nonneg old new cap entry step hold, fromTbills_nonneg old new cap entry step]

theorem after_sum_le_one (old new cap entry step : α) (hsum : old + new ≤ 1) : oldAfter old new cap entry step + newAfter old new cap entry step ≤ 1 := by
  have h : fromTbills old new cap entry step ≤ max 0 (1 - (old + new)) := min_le_right _ _
  rw [max_eq_right (by linarith)] at h
  unfold oldAfter newAfter; linarith

theorem wanted_le_cap (new cap entry step : α) : wanted new cap entry step ≤ cap := by
  unfold wanted; split_ifs <;> exact min_le_left _ _

theorem newAfter_le_cap (old new cap entry step : α) (hcap : new ≤ cap) : newAfter old new cap entry step ≤ cap := by
  have hinc : increase new cap entry step ≤ cap - new := by
    unfold increase
    exact max_le (by linarith) (by linarith [wanted_le_cap new cap entry step])
  have ht : taken old new cap entry step ≤ increase new cap entry step - fromTbills old new cap entry step := min_le_left _ _
  unfold newAfter; linarith

theorem update_old_nonneg (old new cap entry step limit : α) : 0 ≤ (update old new cap entry step limit).1 := by
  unfold update retire
  split_ifs with h
  · exact le_refl 0
  · exact oldAfter_nonneg _ _ _ _ _

theorem update_new_nonneg (old new cap entry step limit : α) (hold : 0 ≤ old) (hnew : 0 ≤ new) (hcap : 0 ≤ cap) : 0 ≤ (update old new cap entry step limit).2 := by
  unfold update retire
  split_ifs with h
  · exact le_min hcap (by linarith [newAfter_nonneg old new cap entry step hold hnew, h.1])
  · exact newAfter_nonneg _ _ _ _ _ hold hnew

theorem update_sum_le_one (old new cap entry step limit : α) (hsum : old + new ≤ 1) : (update old new cap entry step limit).1 + (update old new cap entry step limit).2 ≤ 1 := by
  have base := after_sum_le_one old new cap entry step hsum
  unfold update retire
  split_ifs with h
  · simp only [zero_add]
    exact le_trans (min_le_right _ _) (by linarith)
  · exact base

theorem update_new_le_cap (old new cap entry step limit : α) (hcap : new ≤ cap) : (update old new cap entry step limit).2 ≤ cap := by
  unfold update retire
  split_ifs with h
  · exact min_le_left _ _
  · exact newAfter_le_cap _ _ _ _ _ hcap

/-- Below `limit` a generation is gone: it never holds a residue the deadband couldn't trade. -/
theorem update_no_residue (old new cap entry step limit : α) : ¬ (0 < (update old new cap entry step limit).1 ∧ (update old new cap entry step limit).1 < limit) := by
  unfold update retire
  split_ifs with h
  · simp
  · exact h

end AetherFormal.GenerationBlend
