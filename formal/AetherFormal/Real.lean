import Mathlib.Data.Real.Basic
import AetherFormal.BookNeutrality
import AetherFormal.BookConstruction
import AetherFormal.RiskControls
import AetherFormal.PositionSizing
import AetherFormal.OrderGate

/-!
# The headline theorems at `α := ℝ`

Every model is generic over an ordered field; these restate the main invariants for the real numbers (the proofs are
the generic ones). `GenCases` runs the same models at `ℚ`.
-/

namespace AetherFormal.RealCorollaries

open BookNeutrality in
theorem book_shrinks (cfg : Config ℝ) : ShrinkStep (neutralize cfg) := neutralize_shrinks cfg

open BookNeutrality in
theorem book_gross (cfg : Config ℝ) (hc : 0 < cfg.grossCap) (b : List (Entry ℝ)) :
    gross (neutralize cfg b) ≤ cfg.grossCap := neutralize_gross cfg hc b

open BookNeutrality in
theorem book_name_cap (cfg : Config ℝ) (hc : 0 < cfg.nameCap) (b : List (Entry ℝ)) :
    ∀ e ∈ neutralize cfg b, |e.w| ≤ cfg.nameCap := name_cap cfg hc b

open BookConstruction in
theorem blend_within_cap {n : Nat} (f minW cap : ℝ) (hf : 0 ≤ f) (cur tgt : Fin n → ℝ)
    (hc : gross cur ≤ cap) (ht : gross tgt ≤ cap) : gross (partialAdjust f minW cur tgt) ≤ cap :=
  partialAdjust_within_cap f minW cap hf cur tgt hc ht

open RiskControls in
theorem cap_target_within (w cur cap : ℝ) : |(capTargetWeight (some w) cur cap).1| ≤ max 0 (cap - cur) :=
  capTargetWeight_within w cur cap

open PositionSizing in
theorem sizing_within_cap (base : Option ℝ) (c mp mn m : ℝ) : |size base c mp mn m| ≤ max mp 0 :=
  size_le_cap base c mp mn m

open OrderGate in
theorem slippage_bounded (p : ℝ) (raw : Option ℝ) {m : ℝ} (hm : 0 ≤ m) (hp : 0 ≤ p) :
    0 ≤ slippageAmount p (resolveBps raw m) ∧ slippageAmount p (resolveBps raw m) ≤ p * (m / 10000) :=
  fill_slippage_bounded p raw hm hp

end AetherFormal.RealCorollaries
