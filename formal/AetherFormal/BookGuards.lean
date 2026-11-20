import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Algebra.BigOperators.Ring.List
import Mathlib.Algebra.BigOperators.Group.List.Basic
import Mathlib.Algebra.Order.BigOperators.Group.List
import Mathlib.Data.List.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/book_optimizer.drop_classes`, `class_gross`, `stress_scaler`

V6.6.10 (W4, batch A): the guards a model-book row passes through. A suspended class holds nothing and every other name keeps its
weight; a class's gross is never negative; the stress scaler multiplies the whole row by one factor on a stressed session, so with a
factor in [0, 1] it never raises the book's gross, and a missing ratio leaves the row alone.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.BookGuards

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def dropClasses (row : List (String × α)) (cls : String → String) (blocked : List String) : List (String × α) :=
  row.filter (fun p => !(blocked.contains (cls p.1)))

/-- No name of a suspended class is left. -/
theorem dropped_class_holds_nothing (row : List (String × α)) (cls : String → String) (blocked : List String) :
    ∀ p ∈ dropClasses row cls blocked, cls p.1 ∉ blocked := by
  intro p hp
  have := (List.mem_filter.mp hp).2
  simpa using this

/-- Every name that stays keeps its weight: the result is a sub-list of the row. -/
theorem kept_unchanged (row : List (String × α)) (cls : String → String) (blocked : List String) :
    (dropClasses row cls blocked).Sublist row :=
  List.filter_sublist

def gross (row : List (String × α)) : α := (row.map (fun p => |p.2|)).sum

theorem gross_nonneg (row : List (String × α)) : 0 ≤ gross row :=
  List.sum_nonneg (fun x hx => by obtain ⟨p, -, rfl⟩ := List.mem_map.mp hx; exact abs_nonneg _)

/-- The gross of one class (`class_gross` per name): never negative. -/
theorem class_gross_nonneg (row : List (String × α)) (cls : String → String) (name : String) :
    0 ≤ gross (row.filter (fun p => cls p.1 == name)) :=
  gross_nonneg _

def stressScale (row : List (String × α)) (level : Option α) (threshold factor : α) : List (String × α) :=
  match level with
  | some l => if threshold < l then row.map (fun p => (p.1, p.2 * factor)) else row
  | none => row

theorem gross_scale (row : List (String × α)) (factor : α) (hf : 0 ≤ factor) :
    gross (row.map (fun p => (p.1, p.2 * factor))) = gross row * factor := by
  simp only [gross, List.map_map, Function.comp_def, abs_mul, abs_of_nonneg hf]
  rw [List.sum_map_mul_right]

/-- A stress factor in [0, 1] never raises the gross. -/
theorem stress_never_raises (row : List (String × α)) (level : Option α) (threshold factor : α) (h0 : 0 ≤ factor) (h1 : factor ≤ 1) :
    gross (stressScale row level threshold factor) ≤ gross row := by
  cases level with
  | none => exact le_refl _
  | some l =>
    simp only [stressScale]
    split_ifs
    · rw [gross_scale _ _ h0]
      have := gross_nonneg row
      nlinarith
    · exact le_refl _

/-- No ratio, no change. -/
theorem missing_ratio_unchanged (row : List (String × α)) (threshold factor : α) : stressScale row none threshold factor = row := rfl

end AetherFormal.BookGuards
