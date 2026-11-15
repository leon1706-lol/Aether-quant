import Mathlib.Algebra.BigOperators.Ring.List
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Algebra.BigOperators.Group.List.Basic
import Mathlib.Algebra.Order.BigOperators.Group.List
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/generation_blend.py`

`dynamic_targets`' water-filling: each open generation's share is proportional to its score above the floor; a
generation whose share would exceed its cap gets the cap, and the rest is filled again among the others; what none may
hold stays in T-bills. And `repair_shares`: V6.6.7 (#375) an invalid incoming allocation (a NaN or negative share, or a
total above one) is repaired; it used to be returned as it was, so a tripped generation kept its share. The loop runs
on fuel (the number of open generations: every round with a capped name removes at least one).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.DynamicTargets

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

structure O (α : Type*) where
  name : String
  v : α
  cap : α

def isOver (tol rem total : α) (o : O α) : Bool := decide (o.cap + tol < rem * o.v / total)

def fill (tol : α) : Nat → List (O α) → α → List (String × α)
  | 0, _, _ => []
  | n + 1, opens, rem =>
    if opens = [] ∨ rem ≤ tol then []
    else
      let total := (opens.map (·.v)).sum
      let over := opens.filter (isOver tol rem total)
      if over = [] then opens.map (fun o => (o.name, rem * o.v / total))
      else over.map (fun o => (o.name, o.cap)) ++ fill tol n (opens.filter (fun o => !isOver tol rem total o)) (rem - (over.map (·.cap)).sum)

/-- No generation is given more than its cap (up to the tolerance the Python allows). -/
theorem fill_le_cap (tol : α) (htol : 0 ≤ tol) (n : Nat) (opens : List (O α)) (rem : α) :
    ∀ p ∈ fill tol n opens rem, ∃ o ∈ opens, o.name = p.1 ∧ p.2 ≤ o.cap + tol := by
  induction n generalizing opens rem with
  | zero => simp [fill]
  | succ n ih =>
    intro p hp
    simp only [fill] at hp
    split_ifs at hp with h1 h2
    · simp at hp
    · obtain ⟨o, ho, rfl⟩ := List.mem_map.mp hp
      refine ⟨o, ho, rfl, ?_⟩
      have hno : isOver tol rem (opens.map (·.v)).sum o = false := by
        by_contra hc
        simp only [Bool.not_eq_false] at hc
        have : o ∈ opens.filter (isOver tol rem (opens.map (·.v)).sum) := List.mem_filter.mpr ⟨ho, hc⟩
        rw [h2] at this; simp at this
      simp only [isOver, decide_eq_false_iff_not, not_lt] at hno
      exact hno
    · rcases List.mem_append.mp hp with hp | hp
      · obtain ⟨o, ho, rfl⟩ := List.mem_map.mp hp
        exact ⟨o, (List.mem_filter.mp ho).1, rfl, le_add_of_nonneg_right htol⟩
      · obtain ⟨o, ho, hn, hle⟩ := ih _ _ p hp
        exact ⟨o, (List.mem_filter.mp ho).1, hn, hle⟩

/-- Shares go only to open generations, at most one each round. -/
theorem fill_names (tol : α) (htol : 0 ≤ tol) (n : Nat) (opens : List (O α)) (rem : α) :
    ∀ p ∈ fill tol n opens rem, ∃ o ∈ opens, o.name = p.1 := by
  intro p hp
  obtain ⟨o, ho, hn, -⟩ := fill_le_cap tol htol n opens rem p hp
  exact ⟨o, ho, hn⟩

def repair (tol : α) (xs : List (Option α)) : List α :=
  let ys := xs.map (fun o => match o with | none => 0 | some x => max 0 x)
  if 1 + tol < ys.sum then ys.map (· / ys.sum) else ys

theorem repair_nonneg (tol : α) (xs : List (Option α)) : ∀ y ∈ repair tol xs, 0 ≤ y := by
  have base : ∀ y ∈ xs.map (fun o => match o with | none => 0 | some x => max 0 x), (0 : α) ≤ y := by
    intro y hy
    obtain ⟨o, -, rfl⟩ := List.mem_map.mp hy
    cases o
    · exact le_refl _
    · exact le_max_left _ _
  have hs : (0 : α) ≤ (xs.map (fun o => match o with | none => 0 | some x => max 0 x)).sum := List.sum_nonneg base
  intro y hy
  simp only [repair] at hy
  split_ifs at hy
  · obtain ⟨z, hz, rfl⟩ := List.mem_map.mp hy
    exact div_nonneg (base z hz) hs
  · exact base y hy

/-- A repaired allocation never sums above one (plus the tolerance). -/
theorem repair_sum_le (tol : α) (htol : 0 ≤ tol) (xs : List (Option α)) : (repair tol xs).sum ≤ 1 + tol := by
  simp only [repair]
  generalize xs.map (fun o => match o with | none => 0 | some x => max 0 x) = ys
  split_ifs with h
  · have hpos : 0 < ys.sum := by linarith
    have hdiv : ∀ zs : List α, (zs.map (· / ys.sum)).sum = zs.sum / ys.sum := by
      intro zs
      induction zs with
      | nil => simp
      | cons z zs ih => simp [List.sum_cons, ih, add_div]
    rw [hdiv, div_self hpos.ne']
    linarith
  · exact not_lt.mp h

end AetherFormal.DynamicTargets
