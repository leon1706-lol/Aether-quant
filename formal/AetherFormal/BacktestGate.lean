import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `retraining/backtest_gate.py`

`compare_backtests`' verdict: a candidate passes when its total return beats the active model's by at least
`min_excess_return_vs_active`. A missing or non-finite value is `none`; a missing active return reads 0 (no edge).
V6.6.7 (#370): a missing candidate return used to read 0.0, which beats a losing active model, and a NaN threshold made
`excess < nan` False, so the gate passed vacuously (the class of #122). Both fail now.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.BacktestGate

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

inductive Reason
  | thresholdInvalid
  | candidateMissing
  | belowThreshold
  | passed
  deriving DecidableEq, Repr

def verdict (candidate active threshold : Option α) : Bool × Reason :=
  match threshold with
  | none => (false, .thresholdInvalid)
  | some t =>
    match candidate with
    | none => (false, .candidateMissing)
    | some c => if c - active.getD 0 < t then (false, .belowThreshold) else (true, .passed)

theorem passes_iff (c t : α) (active : Option α) :
    (verdict (some c) active (some t)).1 = true ↔ t ≤ c - active.getD 0 := by
  simp only [verdict]
  split_ifs with h
  · simp only [Bool.false_eq_true, false_iff, not_le]; exact h
  · simp only [true_iff]; exact not_lt.mp h

theorem missing_candidate_fails (active threshold : Option α) : (verdict none active threshold).1 = false := by
  cases threshold <;> rfl

theorem invalid_threshold_fails (candidate active : Option α) : (verdict candidate active none).1 = false := rfl

/-- A better candidate never fails where a worse one passed. -/
theorem mono_candidate (c c' t : α) (active : Option α) (hc : c ≤ c') (h : (verdict (some c) active (some t)).1 = true) :
    (verdict (some c') active (some t)).1 = true := by
  rw [passes_iff] at h ⊢
  linarith

/-- A stricter threshold never passes what a looser one failed. -/
theorem mono_threshold (c t t' : α) (active : Option α) (ht : t ≤ t') (h : (verdict (some c) active (some t')).1 = true) :
    (verdict (some c) active (some t)).1 = true := by
  rw [passes_iff] at h ⊢
  linarith

end AetherFormal.BacktestGate
