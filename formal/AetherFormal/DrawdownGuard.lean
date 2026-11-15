import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `evaluation/generation_ledger.py`

`_max_drawdown` (the largest fall of the compounded session curve from its running peak, the peak starting at 1) and the
latching trip of `generation_state`. A non-finite session return is `none`. V6.6.7 (#369): fail closed. A NaN return
gave a NaN drawdown and `nan >= ceiling` is False, so the guard never tripped; a return at or below -1 now reads as a
drawdown of 1, as does a non-finite one.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.DrawdownGuard

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

/-- The compounded level, its running peak and the worst level-to-peak ratio so far. -/
structure St (α : Type*) where
  level : α
  peak : α
  worst : α

def step (s : St α) (r : α) : St α :=
  let l := s.level * (1 + r)
  let p := max s.peak l
  ⟨l, p, min s.worst (l / p)⟩

def run (rs : List α) (s : St α) : St α := rs.foldl step s

def start : St α := ⟨1, 1, 1⟩

def bad : Option α → Bool
  | none => true
  | some r => decide (r ≤ -1)

def maxDrawdown (rs : List (Option α)) : α :=
  if rs = [] then 0
  else if rs.any bad then 1
  else min 1 (max 0 (1 - (run (rs.filterMap id) start).worst))

def tripped (previous : Bool) (rs : List (Option α)) (ceiling : α) : Bool :=
  previous || decide (ceiling ≤ maxDrawdown rs)

theorem dd_nonneg (rs : List (Option α)) : 0 ≤ maxDrawdown rs := by
  unfold maxDrawdown
  split_ifs
  · exact le_refl _
  · exact zero_le_one
  · exact le_min zero_le_one (le_max_left _ _)

theorem dd_le_one (rs : List (Option α)) : maxDrawdown rs ≤ 1 := by
  unfold maxDrawdown
  split_ifs
  · exact zero_le_one
  · exact le_refl _
  · exact min_le_left _ _

/-- The worst ratio only falls as sessions are added. -/
theorem run_worst_le (rs : List α) (s : St α) : (run rs s).worst ≤ s.worst := by
  induction rs generalizing s with
  | nil => exact le_refl _
  | cons r rs ih =>
    have h := ih (step s r)
    simp only [run, List.foldl_cons] at h ⊢
    exact h.trans (min_le_left _ _)

theorem run_append (xs ys : List α) (s : St α) : run (xs ++ ys) s = run ys (run xs s) := by
  simp [run, List.foldl_append]

/-- A drawdown never shrinks when a session is appended: the guard reads the whole record. -/
theorem dd_mono_append (rs : List (Option α)) (r : Option α) : maxDrawdown rs ≤ maxDrawdown (rs ++ [r]) := by
  by_cases he : rs = []
  · subst he; exact (show maxDrawdown ([] : List (Option α)) = 0 by simp [maxDrawdown]) ▸ dd_nonneg _
  by_cases hb : rs.any bad = true
  · have : (rs ++ [r]).any bad = true := by simp [List.any_append, hb]
    have h1 : maxDrawdown (rs ++ [r]) = 1 := by simp [maxDrawdown, this]
    rw [h1]; exact dd_le_one _
  by_cases hr : bad r = true
  · have : (rs ++ [r]).any bad = true := by simp [List.any_append, hr]
    have h1 : maxDrawdown (rs ++ [r]) = 1 := by simp [maxDrawdown, this]
    rw [h1]; exact dd_le_one _
  have hb' : rs.any bad = false := by simpa using hb
  have hr' : bad r = false := by simpa using hr
  have hany : (rs ++ [r]).any bad = false := by simp [List.any_append, hb', hr']
  have hne : rs ++ [r] ≠ [] := by simp
  simp only [maxDrawdown, if_neg he, if_neg hne, hb', hany, Bool.false_eq_true, if_false]
  cases r with
  | none => simp [bad] at hr'
  | some x =>
    have hw : (run ((rs ++ [some x]).filterMap id) start).worst ≤ (run (rs.filterMap id) start).worst := by
      rw [List.filterMap_append, run_append]
      exact run_worst_le _ _
    apply min_le_min_left
    apply max_le_max_left
    linarith

theorem trip_latches (rs : List (Option α)) (ceiling : α) : tripped true rs ceiling = true := rfl

theorem nonfinite_trips (rs : List (Option α)) (ceiling : α) (hc : ceiling ≤ 1) (hn : none ∈ rs) :
    tripped false rs ceiling = true := by
  have hne : rs ≠ [] := List.ne_nil_of_mem hn
  have hany : rs.any bad = true := List.any_eq_true.mpr ⟨none, hn, rfl⟩
  simp [tripped, maxDrawdown, hne, hany, hc]

end AetherFormal.DrawdownGuard
