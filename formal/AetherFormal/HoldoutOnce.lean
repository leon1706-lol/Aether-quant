import Mathlib.Data.List.Basic

/-!
# `evaluation/research_cells.py`: `record_holdout_read`, and the family check of `stage_freeze`

The once-only ledger of holdout reads. A read of cells succeeds only if none of them is in the ledger, and then the cells are in the ledger. So a cell is read once whatever the freeze file is called,
and reading one family's cells (equity V1-V3, crypto CV) leaves the other family's open.
-/

namespace AetherFormal.HoldoutOnce

abbrev Cell := String

/-- `record_holdout_read(path, cells=...)`: refused if any cell was already read, otherwise the ledger gains the cells. -/
def record (ledger cells : List Cell) : Option (List Cell) :=
  if cells.any (fun c => decide (c ∈ ledger)) then none else some (ledger ++ cells)

/-- Cells a freeze of this family would read that are already spent: `stage_freeze` refuses if any. -/
def spentIn (ledger family : List Cell) : List Cell := ledger.filter (fun c => decide (c ∈ family))

theorem record_refuses_a_cell_already_read (ledger cells : List Cell) (c : Cell) (hc : c ∈ cells) (hl : c ∈ ledger) : record ledger cells = none := by
  unfold record
  have : cells.any (fun c => decide (c ∈ ledger)) = true := by
    rw [List.any_eq_true]
    exact ⟨c, hc, by simp [hl]⟩
  simp [this]

theorem record_adds_the_cells (ledger cells ledger' : List Cell) (h : record ledger cells = some ledger') : ledger' = ledger ++ cells := by
  unfold record at h
  by_cases hany : cells.any (fun c => decide (c ∈ ledger)) = true
  · rw [if_pos hany] at h
    cases h
  · rw [if_neg hany] at h
    exact (Option.some.inj h).symm

/-- After a successful read, reading any one of those cells again is refused: a holdout is read once. -/
theorem second_read_refused (ledger cells ledger' : List Cell) (h : record ledger cells = some ledger') (c : Cell) (hc : c ∈ cells) :
    record ledger' [c] = none := by
  have hl : ledger' = ledger ++ cells := record_adds_the_cells ledger cells ledger' h
  apply record_refuses_a_cell_already_read ledger' [c] c (by simp)
  rw [hl]; simp [hc]

/-- A read of cells disjoint from the ledger succeeds. -/
theorem fresh_cells_are_readable (ledger cells : List Cell) (hd : ∀ c ∈ cells, c ∉ ledger) : record ledger cells = some (ledger ++ cells) := by
  unfold record
  have : cells.any (fun c => decide (c ∈ ledger)) = false := by
    rw [Bool.eq_false_iff]
    intro hany
    rw [List.any_eq_true] at hany
    obtain ⟨c, hc, hd'⟩ := hany
    exact hd c hc (by simpa using hd')
  simp [this]

/-- Families are independent: a ledger holding only crypto cells has spent nothing in the equity family. -/
theorem families_isolated (ledger equity : List Cell) (hd : ∀ c ∈ ledger, c ∉ equity) : spentIn ledger equity = [] := by
  unfold spentIn
  rw [List.filter_eq_nil_iff]
  intro c hc
  simpa using hd c hc

end AetherFormal.HoldoutOnce
