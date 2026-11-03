import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `risk/position_sizing.py`

The bounded multipliers and the core of `build_dynamic_position_sizing`. The topology, rank and RL multipliers enter
`size` as inputs; their own bounds are separate theorems. A non-finite base target is `none` (V6.4.3).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.PositionSizing

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def clamp01 (x : α) : α := max 0 (min x 1)

theorem clamp01_mem (x : α) : 0 ≤ clamp01 x ∧ clamp01 x ≤ 1 :=
  ⟨le_max_left _ _, max_le zero_le_one (min_le_right _ _)⟩

/-- `topology_sizing_multiplier` when the source is "learned" (otherwise 1). -/
def topologyMult (conf disagreement lo hi : α) : α := lo + (hi - lo) * (clamp01 conf * (1 - clamp01 disagreement))

/-- `rank_sizing_multiplier` when enabled (otherwise 1). -/
def rankMult (rank lo hi : α) : α := lo + (hi - lo) * clamp01 rank

/-- `cost_sizing_multiplier` when enabled and the edge is nonzero (otherwise 1). -/
def costMult (edge cost minC : α) : α := max minC (min ((edge - cost) / max |edge| (1 / 1000000000)) 1)

theorem lerp_mem {lo hi t : α} (h : lo ≤ hi) (ht0 : 0 ≤ t) (ht1 : t ≤ 1) : lo ≤ lo + (hi - lo) * t ∧ lo + (hi - lo) * t ≤ hi := by
  constructor <;> nlinarith

theorem topologyMult_mem (conf d lo hi : α) (h : lo ≤ hi) : lo ≤ topologyMult conf d lo hi ∧ topologyMult conf d lo hi ≤ hi := by
  obtain ⟨a0, a1⟩ := clamp01_mem conf
  obtain ⟨b0, b1⟩ := clamp01_mem d
  exact lerp_mem h (mul_nonneg a0 (by linarith)) (by nlinarith)

theorem rankMult_mem (rank lo hi : α) (h : lo ≤ hi) : lo ≤ rankMult rank lo hi ∧ rankMult rank lo hi ≤ hi := by
  obtain ⟨a0, a1⟩ := clamp01_mem rank
  exact lerp_mem h a0 a1

/-- Shrink-only when `min_cost_multiplier ≤ 1`. -/
theorem costMult_mem (edge cost minC : α) (h : minC ≤ 1) : minC ≤ costMult edge cost minC ∧ costMult edge cost minC ≤ 1 :=
  ⟨le_max_left _ _, max_le h (min_le_right _ _)⟩

/-- FINDING: a `min_cost_multiplier` above 1 amplifies the position instead of shrinking it. -/
theorem costMult_amplifies_when_misconfigured : costMult (1 : ℚ) 0 2 = 2 := by
  unfold costMult; norm_num

/-- The core of `build_dynamic_position_sizing`: `mult` is the product of the volatility, confidence, topology, rank
and RL multipliers. Returns the signed target weight. V6.4.3: a negative product (a misconfigured multiplier bound)
sizes to 0 instead of flipping the trade and escaping the cap. -/
def size (base : Option α) (confidence maxPos minPos mult : α) : α :=
  match base with
  | none => 0
  | some b =>
    let conf := max 0 (min confidence 1)
    let cap := max maxPos 0
    if b = 0 ∨ conf = 0 ∨ cap = 0 then 0
    else
      let s0 := max 0 (min (|b| * mult) cap)
      let s := if 0 < s0 ∧ 0 < minPos then min (max s0 minPos) cap else s0
      (if 0 ≤ b then 1 else -1) * s

def sgn (b : α) : α := if 0 ≤ b then 1 else -1

theorem abs_sgn_mul (b s : α) : |sgn b * s| = |s| := by
  unfold sgn; split_ifs <;> simp [abs_mul]

theorem sgn_mul_nonneg (b s : α) (hs : 0 ≤ s) : 0 ≤ b * (sgn b * s) := by
  unfold sgn
  split_ifs with h
  · rw [one_mul]; exact mul_nonneg h hs
  · push_neg at h; nlinarith

/-- The sized magnitude before the sign: always in `[0, cap]`. -/
def magnitude (b maxPos minPos mult : α) : α :=
  let cap := max maxPos 0
  let s0 := max 0 (min (|b| * mult) cap)
  if 0 < s0 ∧ 0 < minPos then min (max s0 minPos) cap else s0

theorem magnitude_mem (b maxPos minPos mult : α) :
    0 ≤ magnitude b maxPos minPos mult ∧ magnitude b maxPos minPos mult ≤ max maxPos 0 := by
  unfold magnitude
  simp only
  have hc : 0 ≤ max maxPos 0 := le_max_right _ _
  have h0 : 0 ≤ max 0 (min (|b| * mult) (max maxPos 0)) := le_max_left _ _
  have h1 : max 0 (min (|b| * mult) (max maxPos 0)) ≤ max maxPos 0 := max_le hc (min_le_right _ _)
  split_ifs
  · exact ⟨le_min (le_trans h0 (le_max_left _ _)) hc, min_le_right _ _⟩
  · exact ⟨h0, h1⟩

theorem size_eq (b confidence maxPos minPos mult : α) :
    size (some b) confidence maxPos minPos mult =
      if b = 0 ∨ max 0 (min confidence 1) = 0 ∨ max maxPos 0 = 0 then 0
      else sgn b * magnitude b maxPos minPos mult := by
  rfl

/-- The sized weight never exceeds `max_position_weight`, for any multiplier values. -/
theorem size_le_cap (base : Option α) (confidence maxPos minPos mult : α) :
    |size base confidence maxPos minPos mult| ≤ max maxPos 0 := by
  cases base with
  | none => simp [size]
  | some b =>
    rw [size_eq]
    split_ifs
    · simp
    · rw [abs_sgn_mul, abs_of_nonneg (magnitude_mem b maxPos minPos mult).1]
      exact (magnitude_mem b maxPos minPos mult).2

/-- ... and never takes the opposite side of the base target. -/
theorem size_no_flip (b confidence maxPos minPos mult : α) : 0 ≤ b * size (some b) confidence maxPos minPos mult := by
  rw [size_eq]
  split_ifs
  · simp
  · exact sgn_mul_nonneg b _ (magnitude_mem b maxPos minPos mult).1

theorem size_nonfinite (confidence maxPos minPos mult : α) : size none confidence maxPos minPos mult = 0 := rfl

/-- FINDING: before V6.4.3 a negative multiplier product came out of `min(sized, cap)` unclamped: here a 0.1 base with
product -50 sized to -5, 50x the 0.1 cap and on the wrong side. -/
theorem old_negative_product_escapes_cap : min ((1 / 10 : ℚ) * (-50)) (1 / 10) = -5 := by norm_num

end AetherFormal.PositionSizing
