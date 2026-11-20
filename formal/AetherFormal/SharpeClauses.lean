import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith

/-!
# `evaluation/premia_research.passes_sharpe_clauses`

V6.6.10 (W4, batch A): R-SLEEVE2's Sharpe clauses, the first door of every research gate since V6.5.0: the pooled Sharpe at least
`pooled_floor` and both halves at least `half_floor`. A missing Sharpe fails; better numbers never fail a passing trial; tighter
floors never pass a failing one.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.SharpeClauses

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def passes (pooled first second : Option α) (halfFloor pooledFloor : α) : Bool :=
  match pooled, first, second with
  | some p, some a, some b => decide (pooledFloor ≤ p ∧ halfFloor ≤ a ∧ halfFloor ≤ b)
  | _, _, _ => false

theorem missing_fails (first second : Option α) (h p : α) : passes none first second h p = false := by
  simp [passes]

theorem passes_iff (p a b h f : α) : passes (some p) (some a) (some b) h f = true ↔ f ≤ p ∧ h ≤ a ∧ h ≤ b := by
  simp [passes]

/-- Better Sharpes never fail a trial that passed. -/
theorem mono_sharpes (p a b p' a' b' h f : α) (hp : p ≤ p') (ha : a ≤ a') (hb : b ≤ b')
    (hpass : passes (some p) (some a) (some b) h f = true) : passes (some p') (some a') (some b') h f = true := by
  rw [passes_iff] at hpass ⊢
  exact ⟨le_trans hpass.1 hp, le_trans hpass.2.1 ha, le_trans hpass.2.2 hb⟩

/-- Tighter floors never pass a trial looser ones failed. -/
theorem antitone_floors (p a b h h' f f' : α) (hh : h ≤ h') (hf : f ≤ f')
    (hpass : passes (some p) (some a) (some b) h' f' = true) : passes (some p) (some a) (some b) h f = true := by
  rw [passes_iff] at hpass ⊢
  exact ⟨le_trans hf hpass.1, le_trans hh hpass.2.1, le_trans hh hpass.2.2⟩

end AetherFormal.SharpeClauses
