import Mathlib.Tactic.Ring
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Algebra.Order.Floor.Ring
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/target_weights.py`

One ticker of `rebalance_deltas`: the signed units to trade toward a target weight, truncated toward zero to whole
lots, and whether the order is a reduction (sorted first, because Lean checks buying power at submission and does not
net unfilled sells). A ticker the target omits (weight 0) is closed in full. V6.6.7 (#373): an order through zero
(held +10, delta -30) was tagged a reduction although it opens exposure; a reduction is now at most the position.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.Rebalance

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α] [FloorRing α]

/-- `math.trunc`: toward zero. -/
def trunc (x : α) : α := if 0 ≤ x then (⌊x⌋ : α) else (⌈x⌉ : α)

theorem trunc_nonneg_between (x : α) (h : 0 ≤ x) : 0 ≤ trunc x ∧ trunc x ≤ x := by
  simp only [trunc, if_pos h]
  exact ⟨by exact_mod_cast Int.floor_nonneg.mpr h, Int.floor_le x⟩

theorem trunc_neg_between (x : α) (h : x < 0) : x ≤ trunc x ∧ trunc x ≤ 0 := by
  simp only [trunc, if_neg (not_le.mpr h)]
  refine ⟨Int.le_ceil x, ?_⟩
  have : ⌈x⌉ ≤ 0 := Int.ceil_le.mpr (by exact_mod_cast h.le)
  exact_mod_cast this

def effectiveLot (lot : α) : α := if 0 < lot then lot else 1

theorem effectiveLot_pos (lot : α) : 0 < effectiveLot lot := by
  unfold effectiveLot; split_ifs with h
  · exact h
  · exact zero_lt_one

/-- The truncated order before the minimum-trade checks. -/
def rawDelta (held unit nav wanted lot : α) : α :=
  trunc ((wanted - held * unit / nav) * nav / unit / effectiveLot lot) * effectiveLot lot

/-- The order in units, or `none`. -/
def order (held unit nav wanted lot minW minUsd : α) : Option α :=
  if nav ≤ 0 ∨ unit ≤ 0 then none
  else if wanted = 0 then (if held = 0 then none else some (-held))
  else if |wanted - held * unit / nav| < minW then none
  else if rawDelta held unit nav wanted lot = 0 ∨ |rawDelta held unit nav wanted lot| * unit < minUsd then none
  else some (rawDelta held unit nav wanted lot)

/-- `reduces` in the Python. -/
def isReduction (held d : α) : Prop := held ≠ 0 ∧ (d < 0 ↔ 0 < held) ∧ |d| ≤ |held|

theorem nav_nonpos_no_order (held unit nav wanted lot minW minUsd : α) (h : nav ≤ 0) :
    order held unit nav wanted lot minW minUsd = none := by
  simp [order, h]

/-- A trade toward a target weight never passes it: the weight after lies between the weight now and the target. -/
theorem no_overshoot (held unit nav wanted lot minW minUsd d : α) (hw : wanted ≠ 0)
    (h : order held unit nav wanted lot minW minUsd = some d) :
    min 0 (wanted - held * unit / nav) ≤ d * unit / nav ∧ d * unit / nav ≤ max 0 (wanted - held * unit / nav) := by
  have h1 : ¬ (nav ≤ 0 ∨ unit ≤ 0) := by intro hc; simp [order, hc] at h
  have h3 : ¬ |wanted - held * unit / nav| < minW := by intro hc; simp [order, h1, hw, hc] at h
  have h5 : ¬ (rawDelta held unit nav wanted lot = 0 ∨ |rawDelta held unit nav wanted lot| * unit < minUsd) := by
    intro hc; simp [order, h1, hw, h3, hc] at h
  have hd : rawDelta held unit nav wanted lot = d := by simpa [order, h1, hw, h3, h5] using h
  have hn : 0 < nav := by push_neg at h1; exact h1.1
  have hu : 0 < unit := by push_neg at h1; exact h1.2
  have hl := effectiveLot_pos lot
  subst hd
  simp only [rawDelta]
  set gap := wanted - held * unit / nav
  set x := gap * nav / unit / effectiveLot lot
  have hs : 0 < effectiveLot lot * unit / nav := by positivity
  have hx : x * (effectiveLot lot * unit / nav) = gap := by
    simp only [x]; field_simp
  have key : trunc x * effectiveLot lot * unit / nav = trunc x * (effectiveLot lot * unit / nav) := by ring
  rw [key]
  rcases le_or_gt 0 x with h0 | h0
  · obtain ⟨t0, t1⟩ := trunc_nonneg_between x h0
    constructor
    · exact (min_le_left _ _).trans (mul_nonneg t0 hs.le)
    · exact (mul_le_mul_of_nonneg_right t1 hs.le).trans (by rw [hx]; exact le_max_right _ _)
  · obtain ⟨t0, t1⟩ := trunc_neg_between x h0
    constructor
    · exact (min_le_right _ _).trans (by rw [← hx]; exact mul_le_mul_of_nonneg_right t0 hs.le)
    · exact (mul_nonpos_of_nonpos_of_nonneg t1 hs.le).trans (le_max_left _ _)

/-- A reduction only shrinks the position, never through zero. -/
theorem reduction_shrinks (held d : α) (h : isReduction held d) : |held + d| ≤ |held| ∧ 0 ≤ held * (held + d) := by
  obtain ⟨h0, hs, hle⟩ := h
  rcases lt_or_gt_of_ne h0 with hneg | hpos
  · have hd : 0 ≤ d := by
      by_contra hd; push_neg at hd; exact absurd (hs.mp hd) (not_lt.mpr hneg.le)
    rw [abs_of_nonneg hd, abs_of_neg hneg] at hle
    constructor
    · rw [abs_le, abs_of_neg hneg]; constructor <;> linarith
    · nlinarith
  · have hd : d < 0 := hs.mpr hpos
    rw [abs_of_neg hd, abs_of_pos hpos] at hle
    constructor
    · rw [abs_le, abs_of_pos hpos]; constructor <;> linarith
    · nlinarith

/-- Closing a position in full is a reduction. -/
theorem close_is_reduction (held : α) (h : held ≠ 0) : isReduction held (-held) := by
  refine ⟨h, ?_, by rw [abs_neg]⟩
  constructor
  · intro hn; linarith
  · intro hp; linarith

/-- An order through zero is not a reduction (the fix). -/
theorem through_zero_is_not_a_reduction (held d : α) (h : |held| < |d|) : ¬ isReduction held d :=
  fun hr => absurd hr.2.2 (not_le.mpr h)

end AetherFormal.Rebalance
