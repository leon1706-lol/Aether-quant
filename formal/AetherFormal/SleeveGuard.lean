import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Data.List.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/sleeve_guard.py`

`trailing_drawdown(pnl_increments, lookback_bars)` (finite increments; non-finite ones count as 0 in Python).
V6.4.3: a non-positive lookback reads no window (Python's `xs[-0:]` used to read the whole history).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.SleeveGuard

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

/-- Running (peak, level) over a window, starting from (0, 0). -/
def scan : List α → α × α → α × α
  | [], s => s
  | x :: xs, (peak, level) => scan xs (max peak (level + x), level + x)

def window (xs : List α) (lookback : Int) : List α :=
  if lookback ≤ 0 then [] else xs.drop (xs.length - lookback.toNat)

def trailingDrawdown (xs : List α) (lookback : Int) : α :=
  let (peak, level) := scan (window xs lookback) (0, 0)
  max 0 (peak - level)

theorem trailingDrawdown_nonneg (xs : List α) (lb : Int) : 0 ≤ trailingDrawdown xs lb := by
  unfold trailingDrawdown; exact le_max_left _ _

theorem trailingDrawdown_nonpos_lookback (xs : List α) (lb : Int) (h : lb ≤ 0) : trailingDrawdown xs lb = 0 := by
  simp [trailingDrawdown, window, h, scan]

/-- The sum of the losses (negative increments) in a list. -/
def losses : List α → α
  | [] => 0
  | x :: xs => max 0 (-x) + losses xs

theorem losses_nonneg (xs : List α) : 0 ≤ losses xs := by
  induction xs with
  | nil => simp [losses]
  | cons x xs ih => simp only [losses]; linarith [le_max_left 0 (-x)]

/-- peak - level grows by at most the losses still to come. -/
theorem scan_bound (xs : List α) (peak level : α) (h : level ≤ peak) :
    (scan xs (peak, level)).1 - (scan xs (peak, level)).2 ≤ peak - level + losses xs ∧
      (scan xs (peak, level)).2 ≤ (scan xs (peak, level)).1 := by
  induction xs generalizing peak level with
  | nil => simp [scan, losses]; exact h
  | cons x xs ih =>
    simp only [scan, losses]
    obtain ⟨h1, h2⟩ := ih (max peak (level + x)) (level + x) (le_max_right _ _)
    refine ⟨?_, h2⟩
    have hm : max peak (level + x) - (level + x) ≤ peak - level + max 0 (-x) := by
      rcases le_total peak (level + x) with hp | hp
      · rw [max_eq_right hp]; linarith [le_max_left 0 (-x), h]
      · rw [max_eq_left hp]; linarith [le_max_right 0 (-x)]
    linarith

/-- The drawdown never exceeds the window's total losses. -/
theorem trailingDrawdown_le_losses (xs : List α) (lb : Int) : trailingDrawdown xs lb ≤ losses (window xs lb) := by
  unfold trailingDrawdown
  obtain ⟨h1, _⟩ := scan_bound (window xs lb) 0 0 (le_refl 0)
  have := losses_nonneg (window xs lb)
  exact max_le this (by simpa using h1)

end AetherFormal.SleeveGuard
