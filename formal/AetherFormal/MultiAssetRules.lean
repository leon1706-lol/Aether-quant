import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum

/-!
# `evaluation/multi_asset_round.py`

V6.6.10's pre-registered verdicts. R-FLIP1 moves 70% of the book to the multi-asset model book only with a gate survivor, a clean
holdout read, a Lean run above both the crypto sleeve's Sharpe and the current pin's, and Lean agreeing with the engine.
R-INSTALL3 installs the retrained models only when their IC and their Lean run both hold. R-LOSS1 keeps a loss variant only
above the control by a margin, so the control can never pass against itself. A missing number fails its clause.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.MultiAssetRules

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

/-- (b): the one holdout read. -/
def holdoutOk : Option α → Option α → Option α → Bool
  | some s, some d, some v => decide (2 / 5 ≤ s ∧ d ≤ 3 / 20 ∧ v ≤ 1 / 10)
  | _, _, _ => false

/-- The Lean Sharpe floor: the crypto sleeve alone (0.65), and the current pin plus 0.05. -/
def floor (pin : α) : α := max (13 / 20) (pin + 1 / 20)

/-- (c): the Lean run of the 70/30 blend. -/
def leanOk (completed clean : Bool) (pin : α) : Option α → Option α → Option α → Bool
  | some s, some v, some d => completed && clean && decide (floor pin ≤ s ∧ v ≤ 1 / 10 ∧ d ≤ 3 / 20)
  | _, _, _ => false

/-- (d): Lean against the engine. -/
def parityOk : Option α → Option α → Bool
  | some c, some g => decide (19 / 20 ≤ c ∧ |g| ≤ 1 / 100)
  | _, _ => false

def flip (survivor : Bool) (hs hd hv : Option α) (completed clean : Bool) (pin : α) (ls lv ld : Option α) (corr gap : Option α) : Bool :=
  survivor && holdoutOk hs hd hv && leanOk completed clean pin ls lv ld && parityOk corr gap

def modelShare (flipped : Bool) : α := if flipped then 7 / 10 else 3 / 10
def cryptoShare (flipped : Bool) : α := if flipped then 3 / 10 else 7 / 10

theorem shares_sum (flipped : Bool) : modelShare flipped + cryptoShare flipped = (1 : α) := by
  cases flipped <;> simp [modelShare, cryptoShare] <;> norm_num

theorem flip_iff (survivor : Bool) (hs hd hv : Option α) (completed clean : Bool) (pin : α) (ls lv ld corr gap : Option α) :
    flip survivor hs hd hv completed clean pin ls lv ld corr gap = true ↔
      survivor = true ∧ holdoutOk hs hd hv = true ∧ leanOk completed clean pin ls lv ld = true ∧ parityOk corr gap = true := by
  simp [flip, Bool.and_eq_true, and_assoc]

/-- No gate survivor, no flip, whatever the other numbers say. -/
theorem no_survivor_no_flip (hs hd hv : Option α) (completed clean : Bool) (pin : α) (ls lv ld corr gap : Option α) :
    flip false hs hd hv completed clean pin ls lv ld corr gap = false := by
  simp [flip]

/-- A run that did not complete, or whose engine log is not clean, never flips the book. -/
theorem unclean_run_no_flip (survivor : Bool) (hs hd hv : Option α) (pin : α) (ls lv ld corr gap : Option α) (completed clean : Bool)
    (h : completed = false ∨ clean = false) : flip survivor hs hd hv completed clean pin ls lv ld corr gap = false := by
  rcases h with h | h <;> cases ls <;> cases lv <;> cases ld <;> simp [flip, leanOk, h]

/-- The Lean floor is at least the crypto sleeve's Sharpe and at least the pin plus 0.05. -/
theorem floor_bounds (pin : α) : 13 / 20 ≤ floor pin ∧ pin + 1 / 20 ≤ floor pin :=
  ⟨le_max_left _ _, le_max_right _ _⟩

/-- A better Lean Sharpe never undoes a flip. -/
theorem lean_mono (completed clean : Bool) (pin s s' : α) (lv ld : Option α) (hs : s ≤ s')
    (h : leanOk completed clean pin (some s) lv ld = true) : leanOk completed clean pin (some s') lv ld = true := by
  cases lv with
  | none => simp [leanOk] at h
  | some v =>
    cases ld with
    | none => simp [leanOk] at h
    | some d =>
      simp only [leanOk, Bool.and_eq_true, decide_eq_true_eq] at h ⊢
      exact ⟨h.1, le_trans h.2.1 hs, h.2.2⟩

/-- R-INSTALL3: the new models' IC at least the installed models', a clean completed Lean run, Sharpe at least 0.57, drawdown at most 15%. -/
def install3 (newIc installedIc : Option α) (completed clean : Bool) (sharpe dd : Option α) : Bool :=
  (match newIc, installedIc with
    | some n, some i => decide (i ≤ n)
    | _, _ => false) &&
  completed && clean &&
  (match sharpe with
    | some s => decide (57 / 100 ≤ s)
    | none => false) &&
  (match dd with
    | some d => decide (d ≤ 3 / 20)
    | none => false)

theorem install3_needs_the_ic (installedIc : Option α) (completed clean : Bool) (sharpe dd : Option α) :
    install3 none installedIc completed clean sharpe dd = false := by
  simp [install3]

theorem install3_needs_a_clean_run (newIc installedIc : Option α) (sharpe dd : Option α) :
    install3 newIc installedIc true false sharpe dd = false := by
  simp [install3]

/-- R-LOSS1's three clauses for one variant against the control's mean class IC. -/
def lossSurvives (mean : Option α) (controlMean : α) (nonNegative : Nat) (t : Option α) : Bool :=
  (match mean with
    | some m => decide (controlMean + 1 / 100 ≤ m)
    | none => false) &&
  decide (3 ≤ nonNegative) &&
  (match t with
    | some x => decide (2 ≤ x)
    | none => false)

/-- The control can never beat itself by the margin: a variant equal to it never survives. -/
theorem control_never_survives (m : α) (n : Nat) (t : Option α) : lossSurvives (some m) m n t = false := by
  simp [lossSurvives]

end AetherFormal.MultiAssetRules
