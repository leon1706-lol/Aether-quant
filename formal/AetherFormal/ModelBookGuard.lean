import Mathlib.Order.Basic

/-!
# `portfolio/model_book.py`: `permit_model_book_row`

The in-Lean model book (V6.6.9, `phase_v2.target_weights.source = "model_book"`) sends a row to the order path only when all
three things hold: the model files are the pinned ones, every weight of the row is finite, and the models are inside their
age limit. Anything else holds the current book: no order is sent, none is closed. The theorems say the gate is exactly the
conjunction, so a row never reaches an order past a failed check, and a single failed check is enough to hold the book.
-/

namespace AetherFormal.ModelBookGuard

/-- `permit_model_book_row(pins_ok, row_finite, model_age_ok)`. -/
def permit (pinsOk rowFinite ageOk : Bool) : Bool := pinsOk && rowFinite && ageOk

theorem permit_iff (a b c : Bool) : permit a b c = true ↔ a = true ∧ b = true ∧ c = true := by
  simp [permit, and_assoc]

theorem pins_required (b c : Bool) : permit false b c = false := by simp [permit]

theorem finite_required (a c : Bool) : permit a false c = false := by simp [permit]

theorem age_required (a b : Bool) : permit a b false = false := by simp [permit]

theorem all_checks_permit : permit true true true = true := by simp [permit]

end AetherFormal.ModelBookGuard
