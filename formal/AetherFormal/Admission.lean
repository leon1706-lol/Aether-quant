import Mathlib.Data.Rat.Defs
import Mathlib.Tactic.SplitIfs

/-!
# `evaluation/generation_registry.py`: R-ADMIT1

`next_stage` and `share_cap`, branch for branch (Problems #335). A float in the Python (a score, a mean difference, an alpha t) enters here as the class of it the rule reads: a finite number
above zero, at or below zero, absent, or `nan`; a non-finite figure never satisfies a threshold. Real money is outside this file: nothing here touches a broker setting.

The headline results: a generation with no tier (observed only) never holds capital and never ramps, under any evidence; a retired or rejected generation never moves; a generation that has
not reached the book holds nothing; a guard trip takes a generation off the book at once.
-/

namespace AetherFormal.Admission

inductive Stage
  | candidate
  | frozen
  | shadow
  | ramping
  | active
  | fading
  | windingDown
  | retired
  | rejected
  deriving DecidableEq, Repr, Inhabited

inductive Tier
  | installed
  | tier1
  | tier2
  | none
  deriving DecidableEq, Repr, Inhabited

inductive Decay
  | healthy
  | watch
  | decaying
  | dead
  deriving DecidableEq, Repr, Inhabited

/-- The score as the rule reads it: absent (`None`), a finite number above zero, a finite number at or below zero, or `nan`. -/
inductive Score
  | absent
  | positive
  | nonpositive
  | nan
  deriving DecidableEq, Repr, Inhabited

structure Ev where
  selectionPass : Bool
  holdPass : Bool
  edgePass : Bool
  holdoutsSpent : Bool
  forwardOk : Nat
  noDataOk : Bool
  diffOk : Bool
  guardTripped : Bool
  decay : Decay
  alphaLifted : Bool
  score : Score

def sixty : Nat := 60
def twoFiftyTwo : Nat := 252

/-- `AdmissionEvidence`'s `earning`: no score yet, or a finite positive one. -/
def earning (e : Ev) : Bool := e.score == .absent || e.score == .positive

def behind (e : Ev) : Bool := e.decay == .watch || e.decay == .decaying

/-- `_tier2_forward_passes`. -/
def tier2Passes (e : Ev) : Bool := decide (sixty ≤ e.forwardOk) && e.diffOk && !e.guardTripped && e.noDataOk

/-- `admitted_to_shadow`. -/
def admitted (e : Ev) : Bool := e.selectionPass && (e.holdPass || (e.holdoutsSpent && decide (twoFiftyTwo ≤ e.forwardOk)))

/-- `cap_lifted`. -/
def capLifted (e : Ev) : Bool := e.alphaLifted && decide (twoFiftyTwo ≤ e.forwardOk) && e.noDataOk && !e.guardTripped

/-- `_book_stage`. -/
def bookStage : Stage → Ev → Stage
  | .ramping, e => if decide (twoFiftyTwo ≤ e.forwardOk) && e.decay == .healthy then .active else .ramping
  | .active, e => if behind e || !earning e then .fading else .active
  | .fading, e =>
    if !earning e || (e.decay == .decaying && e.score == .nonpositive) then .windingDown
    else if !behind e then .active else .fading
  | _, e => if earning e && e.decay == .healthy && e.score != .absent then .fading else .windingDown

def isBook : Stage → Bool
  | .ramping => true
  | .active => true
  | .fading => true
  | .windingDown => true
  | _ => false

def dying (e : Ev) : Bool := e.guardTripped || e.decay == .dead

/-- `next_stage`. -/
def nextStage (tier : Tier) (s : Stage) (e : Ev) : Stage :=
  if s == .retired || s == .rejected then s
  else if isBook s then (if dying e then .retired else bookStage s e)
  else if dying e && s == .shadow then .rejected
  else if tier == .none then s
  else if s == .candidate || s == .frozen then
    (if e.edgePass then .ramping else if admitted e then .shadow else s)
  else if s == .shadow then
    (if e.edgePass || (e.selectionPass && tier2Passes e) then .ramping else s)
  else s

/-- `share_cap`, with the tier-2 cap as a parameter. -/
def shareCap (tier : Tier) (s : Stage) (e : Ev) (cap : ℚ) : ℚ :=
  if s == .retired || s == .rejected || s == .candidate || s == .frozen || s == .shadow || tier == .none then 0
  else if tier == .tier1 || tier == .installed || e.edgePass then 1
  else if tier == .tier2 then (if capLifted e then 1 else cap)
  else 0

/-- Observed only: a generation with no tier holds nothing, under any stage and any evidence. -/
theorem tier_none_never_capital (s : Stage) (e : Ev) (cap : ℚ) : shareCap .none s e cap = 0 := by
  cases s <;> simp [shareCap]

/-- A generation that is not on the book holds nothing. -/
theorem off_book_holds_nothing (t : Tier) (e : Ev) (cap : ℚ) (s : Stage)
    (h : s = .candidate ∨ s = .frozen ∨ s = .shadow ∨ s = .retired ∨ s = .rejected) : shareCap t s e cap = 0 := by
  rcases h with rfl | rfl | rfl | rfl | rfl <;> simp [shareCap]

/-- A retired generation never moves. -/
theorem retired_absorbing (t : Tier) (e : Ev) : nextStage t .retired e = .retired := by
  simp [nextStage]

/-- A rejected generation never moves. -/
theorem rejected_absorbing (t : Tier) (e : Ev) : nextStage t .rejected e = .rejected := by
  simp [nextStage]

/-- A guard trip or a dead state takes a generation off the book at once. -/
theorem dying_leaves_the_book (t : Tier) (e : Ev) (s : Stage) (hs : s = .ramping ∨ s = .active ∨ s = .fading ∨ s = .windingDown)
    (hd : dying e = true) : nextStage t s e = .retired := by
  rcases hs with rfl | rfl | rfl | rfl <;> simp [nextStage, isBook, hd]

/-- An observer (tier none) in shadow, candidate or frozen never ramps, whatever the evidence. -/
theorem tier_none_never_ramps (s : Stage) (e : Ev) (h : s = .candidate ∨ s = .frozen ∨ s = .shadow) :
    nextStage .none s e ≠ .ramping := by
  rcases h with rfl | rfl | rfl <;> by_cases hd : dying e = true <;> simp [nextStage, isBook, hd]

/-- Without a selection pass and without a full edge pass, a shadow generation does not ramp. -/
theorem no_selection_no_ramp (t : Tier) (e : Ev) (hs : e.selectionPass = false) (he : e.edgePass = false) :
    nextStage t .shadow e ≠ .ramping := by
  cases t <;> by_cases hd : dying e = true <;> simp [nextStage, isBook, hd, hs, he]

/-- A lifted cap is a tier-2 privilege: tier 1 and the installed book already hold everything, and no other tier is lifted. -/
theorem lifted_cap_only_for_tier2 (s : Stage) (e : Ev) (cap : ℚ) (hs : isBook s = true) (hl : capLifted e = true) (he : e.edgePass = false) :
    shareCap .tier2 s e cap = 1 := by
  cases s <;> simp [shareCap, isBook] at hs ⊢ <;> simp [hl, he]

end AetherFormal.Admission
