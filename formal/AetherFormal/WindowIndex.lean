import Mathlib.Data.List.Basic
import Mathlib.Data.List.Range
import Mathlib.Tactic.Linarith

/-!
# `retraining/slicing.sequence_window_index`

V6.6.10 (W4, batch B): the low memory profile gathers each row's sequence window from an index instead of a dense array. Row `i`'s
window is the last `w` rows of its own ticker up to and including `i`, in frame order, left-padded with -1. The theorems are the
ones a sequence model's training depends on: every window has length `w`, never reads a row after its own (no look-ahead), never
reads another ticker's row, and ends at its own row.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.WindowIndex

/-- Row `i`'s ticker's rows up to and including `i`, in frame order. -/
def history (tickers : List Nat) (i : Nat) : List Nat :=
  (List.range (i + 1)).filter (fun j => tickers.getD j 0 == tickers.getD i 0)

/-- The last `w` of them. -/
def recent (tickers : List Nat) (w i : Nat) : List Nat :=
  (history tickers i).drop ((history tickers i).length - w)

def window (tickers : List Nat) (w i : Nat) : List Int :=
  List.replicate (w - (recent tickers w i).length) (-1) ++ (recent tickers w i).map Int.ofNat

theorem window_length (tickers : List Nat) (w i : Nat) : (window tickers w i).length = w := by
  simp only [window, recent, List.length_append, List.length_replicate, List.length_map, List.length_drop]
  omega

theorem mem_recent (tickers : List Nat) (w i j : Nat) (h : j ∈ recent tickers w i) :
    j < i + 1 ∧ tickers.getD j 0 = tickers.getD i 0 := by
  have hf := List.mem_filter.mp (List.mem_of_mem_drop h)
  exact ⟨List.mem_range.mp hf.1, by simpa using hf.2⟩

/-- No look-ahead: every position a window reads is at or before its own row (or the -1 pad). -/
theorem window_causal (tickers : List Nat) (w i : Nat) : ∀ x ∈ window tickers w i, x ≤ (i : Int) := by
  intro x hx
  simp only [window, List.mem_append, List.mem_replicate, List.mem_map] at hx
  rcases hx with ⟨-, rfl⟩ | ⟨j, hj, rfl⟩
  · omega
  · have := (mem_recent tickers w i j hj).1
    simp only [Int.ofNat_eq_natCast]
    omega

/-- A window reads only its own ticker's rows. -/
theorem window_same_ticker (tickers : List Nat) (w i j : Nat) (hj : (j : Int) ∈ window tickers w i) :
    tickers.getD j 0 = tickers.getD i 0 := by
  simp only [window, List.mem_append, List.mem_replicate, List.mem_map] at hj
  rcases hj with ⟨-, h⟩ | ⟨k, hk, hkj⟩
  · omega
  · simp only [Int.ofNat_eq_natCast, Nat.cast_inj] at hkj
    subst hkj
    exact (mem_recent tickers w i k hk).2

theorem history_snoc (tickers : List Nat) (i : Nat) :
    history tickers i = (List.range i).filter (fun j => tickers.getD j 0 == tickers.getD i 0) ++ [i] := by
  simp [history, List.range_succ, List.filter_append]

/-- A window of at least one row ends at its own row. -/
theorem self_mem (tickers : List Nat) (w i : Nat) (hw : 1 ≤ w) : (i : Int) ∈ window tickers w i := by
  simp only [window, List.mem_append, List.mem_map]
  right
  refine ⟨i, ?_, by simp⟩
  simp only [recent]
  rw [history_snoc, List.drop_append_of_le_length (by simp; omega)]
  simp

end AetherFormal.WindowIndex
