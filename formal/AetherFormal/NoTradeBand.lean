import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Data.List.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/book_optimizer.no_trade_band`

V6.6.10 (W4, batch A): a held weight is kept while the new target is within `band` of it, relative to the larger of the two;
otherwise the target is taken. A name the target drops goes, a zero is never written, and applying the band to its own result
changes nothing (the docstring's promise, now a theorem). `current` is a lookup that is 0 for a name not held; Python's
`max(0, band)` is the model's `max 0 band`.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.NoTradeBand

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

/-- One name: the held weight while the target is within the band of it, else the target. -/
def value (held wanted band : α) : α :=
  if held ≠ 0 ∧ |wanted - held| ≤ band * max |wanted| |held| then held else wanted

def step (current : String → α) (band : α) (p : String × α) : String × α :=
  (p.1, value (current p.1) p.2 (max 0 band))

/-- The row: every target name's value, zeros dropped. -/
def bandRow (current : String → α) (target : List (String × α)) (band : α) : List (String × α) :=
  (target.map (step current band)).filter (fun p => p.2 ≠ 0)

/-- A name ends at its held weight or at its target, never anywhere else. -/
theorem value_mem (held wanted band : α) : value held wanted band = held ∨ value held wanted band = wanted := by
  unfold value
  split_ifs
  · exact Or.inl rfl
  · exact Or.inr rfl

/-- Banding a banded weight changes nothing. -/
theorem value_idem (held wanted band : α) : value held (value held wanted band) band = value held wanted band := by
  unfold value
  by_cases h : held ≠ 0 ∧ |wanted - held| ≤ band * max |wanted| |held|
  · rw [if_pos h, ite_self]
  · rw [if_neg h, if_neg h]

theorem step_idem (current : String → α) (band : α) (p : String × α) : step current band (step current band p) = step current band p := by
  simp only [step, value_idem]

/-- Applying the band twice is applying it once. -/
theorem bandRow_idem (current : String → α) (target : List (String × α)) (band : α) :
    bandRow current (bandRow current target band) band = bandRow current target band := by
  unfold bandRow
  have hfix : ∀ x ∈ (target.map (step current band)).filter (fun p => p.2 ≠ 0), step current band x = x := by
    intro x hx
    obtain ⟨y, -, rfl⟩ := List.mem_map.mp (List.mem_filter.mp hx).1
    exact step_idem current band y
  have hmap : ((target.map (step current band)).filter (fun p => p.2 ≠ 0)).map (step current band)
      = (target.map (step current band)).filter (fun p => p.2 ≠ 0) := by
    conv_rhs => rw [← List.map_id ((target.map (step current band)).filter (fun p => p.2 ≠ 0))]
    exact List.map_congr_left hfix
  rw [hmap]
  exact List.filter_eq_self.mpr (fun a ha => (List.mem_filter.mp ha).2)

/-- No zero weight is ever written. -/
theorem no_zero (current : String → α) (target : List (String × α)) (band : α) : ∀ p ∈ bandRow current target band, p.2 ≠ 0 := by
  intro p hp
  simpa using (List.mem_filter.mp hp).2

/-- A name the target does not list is not in the row: a dropped name always goes. -/
theorem dropped_goes (current : String → α) (target : List (String × α)) (band : α) (name : String)
    (h : ∀ p ∈ target, p.1 ≠ name) : ∀ p ∈ bandRow current target band, p.1 ≠ name := by
  intro p hp
  obtain ⟨q, hq, rfl⟩ := List.mem_map.mp (List.mem_filter.mp hp).1
  exact h q hq

end AetherFormal.NoTradeBand
