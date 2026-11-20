import AetherFormal.SleeveGuard

/-!
# `portfolio/book_optimizer.paper_loss_guard`

V6.6.10 (W4, batch A): a guarded class (forex in the model book) is held only when its own sub-book, on paper, has `lookback`
sessions of record and its trailing drawdown over them is within `max_loss`. A short record keeps it out, a non-positive lookback
keeps it out, and a record with no loss in its window lets it in. The drawdown is `SleeveGuard.trailingDrawdown`.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.PaperLossGuard

open AetherFormal.SleeveGuard

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

def guard (xs : List α) (lookback : Int) (maxLoss : α) : Bool :=
  decide (0 < lookback ∧ lookback ≤ xs.length ∧ trailingDrawdown xs lookback ≤ maxLoss)

theorem guard_iff (xs : List α) (lookback : Int) (maxLoss : α) :
    guard xs lookback maxLoss = true ↔ 0 < lookback ∧ lookback ≤ xs.length ∧ trailingDrawdown xs lookback ≤ maxLoss := by
  simp [guard]

/-- Fewer sessions of record than the lookback: the class stays out. -/
theorem short_record_blocks (xs : List α) (lookback : Int) (maxLoss : α) (h : (xs.length : Int) < lookback) :
    guard xs lookback maxLoss = false := by
  simp only [guard, decide_eq_false_iff_not]
  intro ⟨_, h2, _⟩
  omega

/-- A lookback of zero or less never lets a class in (it reads no window). -/
theorem nonpos_lookback_blocks (xs : List α) (lookback : Int) (maxLoss : α) (h : lookback ≤ 0) :
    guard xs lookback maxLoss = false := by
  simp only [guard, decide_eq_false_iff_not]
  intro ⟨h1, _, _⟩
  omega

/-- A looser loss limit never blocks a class a tighter one let in. -/
theorem mono_max_loss (xs : List α) (lookback : Int) (a b : α) (hab : a ≤ b) (h : guard xs lookback a = true) :
    guard xs lookback b = true := by
  rw [guard_iff] at h ⊢
  exact ⟨h.1, h.2.1, le_trans h.2.2 hab⟩

/-- With enough record and no loss anywhere in the window, the class is held. -/
theorem no_loss_passes (xs : List α) (lookback : Int) (maxLoss : α) (h0 : 0 < lookback) (hlen : lookback ≤ xs.length)
    (hm : 0 ≤ maxLoss) (hloss : losses (window xs lookback) = 0) : guard xs lookback maxLoss = true := by
  rw [guard_iff]
  refine ⟨h0, hlen, ?_⟩
  have := trailingDrawdown_le_losses xs lookback
  rw [hloss] at this
  linarith

end AetherFormal.PaperLossGuard
