import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Algebra.Order.BigOperators.Group.Finset
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/generation_blend.py`, the dynamic glide

`step_toward` moves each generation's share a fixed fraction of the way to its target. It is a blend of two allocations, so whatever the targets are and however many generations
there are, shares stay non-negative, sum to at most one and stay under any cap both respect. `shrunk` is `shrunk_sharpe`: a generation's score always lies between its record and its claim.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.GenerationGlide

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]
variable {ι : Type*} [Fintype ι]

/-- One generation's share after a step of `f`, before a retirement. -/
def step (s t f : α) : α := s + f * (t - s)

theorem step_eq_blend (s t f : α) : step s t f = (1 - f) * s + f * t := by unfold step; ring

theorem step_nonneg (s t f : α) (hs : 0 ≤ s) (ht : 0 ≤ t) (h0 : 0 ≤ f) (h1 : f ≤ 1) : 0 ≤ step s t f := by
  rw [step_eq_blend]
  exact add_nonneg (mul_nonneg (by linarith) hs) (mul_nonneg h0 ht)

theorem step_le_cap (s t f cap : α) (hs : s ≤ cap) (ht : t ≤ cap) (h0 : 0 ≤ f) (h1 : f ≤ 1) : step s t f ≤ cap := by
  rw [step_eq_blend]
  have h2 : (1 - f) * s ≤ (1 - f) * cap := mul_le_mul_of_nonneg_left hs (by linarith)
  have h3 : f * t ≤ f * cap := mul_le_mul_of_nonneg_left ht h0
  linarith [h2, h3, show (1 - f) * cap + f * cap = cap by ring]

/-- However many generations hold capital, a step keeps the total at or under one. -/
theorem step_sum_le_one (s t : ι → α) (f : α) (h0 : 0 ≤ f) (h1 : f ≤ 1) (hs : ∑ i, s i ≤ 1) (ht : ∑ i, t i ≤ 1) : ∑ i, step (s i) (t i) f ≤ 1 := by
  have h : ∑ i, step (s i) (t i) f = (1 - f) * ∑ i, s i + f * ∑ i, t i := by
    rw [Finset.mul_sum, Finset.mul_sum, ← Finset.sum_add_distrib]
    exact Finset.sum_congr rfl fun i _ => step_eq_blend _ _ _
  rw [h]
  have h2 : (1 - f) * ∑ i, s i ≤ (1 - f) * 1 := mul_le_mul_of_nonneg_left hs (by linarith)
  have h3 : f * ∑ i, t i ≤ f * 1 := mul_le_mul_of_nonneg_left ht h0
  linarith

/-- A share with nowhere to go doesn't move, so a generation at its target holds still. -/
theorem step_at_target (s f : α) : step s s f = s := by unfold step; ring

/-- `step_toward`, for one generation: below `limit` and headed to nothing, it is gone. -/
def retireIfHeadedOut (value target limit : α) : α := if target ≤ 0 ∧ value < limit then 0 else value

theorem retire_le (value target limit : α) (h : 0 ≤ value) : retireIfHeadedOut value target limit ≤ value := by
  unfold retireIfHeadedOut; split_ifs <;> linarith

theorem retire_nonneg (value target limit : α) (h : 0 ≤ value) : 0 ≤ retireIfHeadedOut value target limit := by
  unfold retireIfHeadedOut; split_ifs <;> linarith

/-- A retirement only ever frees capital, so the total stays at or under one. -/
theorem retire_sum_le_one (v t : ι → α) (limit : α) (hv : ∀ i, 0 ≤ v i) (hsum : ∑ i, v i ≤ 1) : ∑ i, retireIfHeadedOut (v i) (t i) limit ≤ 1 :=
  le_trans (Finset.sum_le_sum fun i _ => retire_le _ _ _ (hv i)) hsum

/-- `shrunk_sharpe`. -/
def shrunk (count obs prior priorCount : α) : α := (count * obs + priorCount * prior) / (count + priorCount)

/-- A score never leaves the range between a generation's record and its claim. -/
theorem shrunk_between (count obs prior priorCount : α) (hc : 0 ≤ count) (hp : 0 ≤ priorCount) (hsum : 0 < count + priorCount) :
    min obs prior ≤ shrunk count obs prior priorCount ∧ shrunk count obs prior priorCount ≤ max obs prior := by
  unfold shrunk
  constructor
  · rw [le_div_iff₀ hsum]
    have h1 : min obs prior ≤ obs := min_le_left _ _
    have h2 : min obs prior ≤ prior := min_le_right _ _
    nlinarith [mul_le_mul_of_nonneg_left h1 hc, mul_le_mul_of_nonneg_left h2 hp]
  · rw [div_le_iff₀ hsum]
    have h1 : obs ≤ max obs prior := le_max_left _ _
    have h2 : prior ≤ max obs prior := le_max_right _ _
    nlinarith [mul_le_mul_of_nonneg_left h1 hc, mul_le_mul_of_nonneg_left h2 hp]

end AetherFormal.GenerationGlide
