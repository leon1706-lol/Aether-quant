import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Data.List.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `execution/reconciliation.py`

`reconcile_positions` with finite weights: each symbol of `keys(expected) ∪ keys(actual)` is classified once, and the
drift maximum is over the non-matched symbols. A symbol absent from a dict is `none` (weight 0).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.Reconciliation

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

inductive Cls
  | matched
  | drifted
  | orphan
  | missing
  deriving DecidableEq, Repr

def delta (exp act : Option α) : α := act.getD 0 - exp.getD 0

/-- Tolerance before presence: a dust position is matched, never an orphan. -/
def classify (wTol vTol pv : α) (exp act : Option α) : Cls :=
  let d := delta exp act
  if |d| ≤ wTol ∧ |d * pv| ≤ vTol then .matched
  else if exp.isNone then .orphan
  else if act.isNone then .missing
  else .drifted

structure Row (α : Type*) where
  sym : Nat
  exp : Option α
  act : Option α

def report (wTol vTol pv : α) (rows : List (Row α)) (c : Cls) : List Nat :=
  (rows.filter fun r => classify wTol vTol pv r.exp r.act = c).map Row.sym

def maxDrift (wTol vTol pv : α) (rows : List (Row α)) : α :=
  (rows.filter fun r => classify wTol vTol pv r.exp r.act ≠ .matched).foldr (fun r m => max |delta r.exp r.act| m) 0

/-- A symbol in a list really has that class. -/
theorem report_sound (wTol vTol pv : α) (rows : List (Row α)) (c : Cls) (s : Nat)
    (hs : s ∈ report wTol vTol pv rows c) : ∃ r ∈ rows, r.sym = s ∧ classify wTol vTol pv r.exp r.act = c := by
  obtain ⟨r, hr, rfl⟩ := List.mem_map.mp hs
  obtain ⟨hr1, hr2⟩ := List.mem_filter.mp hr
  exact ⟨r, hr1, rfl, by simpa using hr2⟩

theorem inj_of_nodup_map {β γ : Type*} (f : β → γ) :
    ∀ (l : List β), (l.map f).Nodup → ∀ x ∈ l, ∀ y ∈ l, f x = f y → x = y
  | [], _, x, hx, _, _, _ => absurd hx (by simp)
  | a :: l, h, x, hx, y, hy, hxy => by
    rw [List.map_cons, List.nodup_cons] at h
    obtain ⟨ha, hl⟩ := h
    rcases List.mem_cons.mp hx with rfl | hx'
    · rcases List.mem_cons.mp hy with rfl | hy'
      · rfl
      · exact absurd (List.mem_map.mpr ⟨y, hy', hxy.symm⟩) ha
    · rcases List.mem_cons.mp hy with rfl | hy'
      · exact absurd (List.mem_map.mpr ⟨x, hx', hxy⟩) ha
      · exact inj_of_nodup_map f l hl x hx' y hy' hxy

/-- No symbol is in two lists (symbols are distinct, as dict keys are). -/
theorem report_disjoint (wTol vTol pv : α) (rows : List (Row α)) (hnd : (rows.map Row.sym).Nodup) (c c' : Cls)
    (s : Nat) (h1 : s ∈ report wTol vTol pv rows c) (h2 : s ∈ report wTol vTol pv rows c') : c = c' := by
  obtain ⟨r, hr, hrs, hrc⟩ := report_sound wTol vTol pv rows c s h1
  obtain ⟨r', hr', hrs', hrc'⟩ := report_sound wTol vTol pv rows c' s h2
  have : r = r' := inj_of_nodup_map Row.sym rows hnd r hr r' hr' (hrs.trans hrs'.symm)
  subst this
  exact hrc.symm.trans hrc'

/-- The four lists cover every symbol: their total length is the number of rows. -/
theorem report_partition (wTol vTol pv : α) (rows : List (Row α)) :
    (report wTol vTol pv rows .matched).length + (report wTol vTol pv rows .drifted).length +
      (report wTol vTol pv rows .orphan).length + (report wTol vTol pv rows .missing).length = rows.length := by
  induction rows with
  | nil => simp [report]
  | cons r rs ih =>
    simp only [report, List.filter_cons, List.length_map] at ih ⊢
    cases h : classify wTol vTol pv r.exp r.act <;> simp [h] <;> omega

theorem foldr_max_ge (l : List (Row α)) (f : Row α → α) (r : Row α) (hr : r ∈ l) :
    f r ≤ l.foldr (fun r m => max (f r) m) 0 := by
  induction l with
  | nil => simp at hr
  | cons x xs ih =>
    simp only [List.foldr_cons]
    rcases List.mem_cons.mp hr with h | h
    · subst h; exact le_max_left _ _
    · exact le_trans (ih h) (le_max_right _ _)

/-- `max_abs_weight_drift` bounds every non-matched symbol's drift. -/
theorem maxDrift_bounds (wTol vTol pv : α) (rows : List (Row α)) (r : Row α) (hr : r ∈ rows)
    (hc : classify wTol vTol pv r.exp r.act ≠ .matched) : |delta r.exp r.act| ≤ maxDrift wTol vTol pv rows :=
  foldr_max_ge _ (fun r => |delta r.exp r.act|) r (List.mem_filter.mpr ⟨hr, by simpa using hc⟩)

/-- A matched symbol is within both tolerances, so leaving it out of the maximum never hides a real drift. -/
theorem matched_within_tolerance (wTol vTol pv : α) (e a : Option α) (h : classify wTol vTol pv e a = .matched) :
    |delta e a| ≤ wTol := by
  unfold classify at h
  simp only at h
  split_ifs at h with h1
  · exact h1.1

end AetherFormal.Reconciliation
