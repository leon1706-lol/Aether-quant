import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Ring

/-!
# `evaluation/model_book_round.inverse_vol_share`

V6.6.10 (W4, batch A): a gate survivor's share of the book beside the crypto sleeve, in proportion to one over each volatility.
For positive volatilities the share is strictly between 0 and 1, the two shares sum to one, and a more volatile model book never
gets more of the book.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.InverseVolShare

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def share (model crypto : α) : α := (1 / model) / (1 / model + 1 / crypto)

theorem share_eq (model crypto : α) (hm : 0 < model) (hc : 0 < crypto) : share model crypto = crypto / (model + crypto) := by
  unfold share
  field_simp
  ring

theorem share_pos (model crypto : α) (hm : 0 < model) (hc : 0 < crypto) : 0 < share model crypto := by
  rw [share_eq _ _ hm hc]
  positivity

theorem share_lt_one (model crypto : α) (hm : 0 < model) (hc : 0 < crypto) : share model crypto < 1 := by
  rw [share_eq _ _ hm hc, div_lt_one (by linarith)]
  linarith

theorem shares_sum (model crypto : α) (hm : 0 < model) (hc : 0 < crypto) : share model crypto + share crypto model = 1 := by
  rw [share_eq _ _ hm hc, share_eq _ _ hc hm, add_comm crypto model, ← add_div, add_comm, div_self (by linarith)]

/-- A more volatile model book never gets a larger share. -/
theorem antitone_model (model model' crypto : α) (hm : 0 < model) (hmm : model ≤ model') (hc : 0 < crypto) :
    share model' crypto ≤ share model crypto := by
  rw [share_eq _ _ (lt_of_lt_of_le hm hmm) hc, share_eq _ _ hm hc]
  exact div_le_div_of_nonneg_left hc.le (by linarith) (by linarith)

end AetherFormal.InverseVolShare
