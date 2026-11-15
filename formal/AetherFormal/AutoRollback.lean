import Mathlib.Data.List.Basic
import Mathlib.Tactic.SplitIfs

/-!
# `retraining/auto_rollback.py`

`select_rollback_target`: an automatic weight swap, the most consequential action in the system, happens only when
it is enabled, a configured trigger fired, the active version has had its runway and no rollback is in cooldown; the
target is the newest candidate that cleared the validation gate. Flags are `is True` (V6.6.7, #371): `bool("false")`
is True, so a hand-edited string used to enable it. Candidates are `(version id, gate passed)`, newest first.
-/

namespace AetherFormal.AutoRollback

structure Input where
  enabled : Bool
  fired : Bool
  runwayOk : Bool
  cooldownOk : Bool
  requireGate : Bool
  candidates : List (Nat × Bool)

/-- The first candidate that may be rolled back to. -/
def target (requireGate : Bool) : List (Nat × Bool) → Option Nat
  | [] => none
  | (i, gate) :: rest => if !requireGate || gate then some i else target requireGate rest

inductive Reason
  | disabled
  | noTrigger
  | blocked
  | triggered
  deriving DecidableEq, Repr

def choose (x : Input) : Option Nat × Reason :=
  if !x.enabled then (none, .disabled)
  else if !x.fired then (none, .noTrigger)
  else if !x.runwayOk || !x.cooldownOk then (none, .blocked)
  else
    match target x.requireGate x.candidates with
    | none => (none, .blocked)
    | some i => (some i, .triggered)

/-- Every guard holds when a rollback is chosen. -/
theorem rollback_needs_all (x : Input) (i : Nat) (h : (choose x).1 = some i) :
    x.enabled = true ∧ x.fired = true ∧ x.runwayOk = true ∧ x.cooldownOk = true := by
  unfold choose at h
  cases he : x.enabled <;> cases hf : x.fired <;> cases hr : x.runwayOk <;> cases hc : x.cooldownOk <;>
    simp [he, hf, hr, hc] at h ⊢

theorem disabled_never_rolls_back (x : Input) (h : x.enabled = false) : (choose x).1 = none := by
  simp [choose, h]

/-- The target is a candidate, and with the gate required it cleared the gate. -/
theorem target_sound (g : Bool) (cs : List (Nat × Bool)) (i : Nat) (h : target g cs = some i) :
    ∃ p, (i, p) ∈ cs ∧ (g = true → p = true) := by
  induction cs with
  | nil => simp [target] at h
  | cons c rest ih =>
    obtain ⟨j, p⟩ := c
    simp only [target] at h
    split_ifs at h with hg
    · cases h
      refine ⟨p, List.mem_cons_self .., fun hg' => ?_⟩
      simp [hg'] at hg
      exact hg
    · obtain ⟨q, hq, hq'⟩ := ih h
      exact ⟨q, List.mem_cons_of_mem _ hq, hq'⟩

/-- The newest eligible candidate is chosen, never an older one. -/
theorem target_is_first (g : Bool) (cs : List (Nat × Bool)) :
    target g cs = (cs.find? (fun c => !g || c.2)).map Prod.fst := by
  induction cs with
  | nil => rfl
  | cons c rest ih =>
    obtain ⟨j, p⟩ := c
    by_cases hg : (!g || p) = true
    · simp [target, List.find?_cons, hg]
    · have hf : (!g || p) = false := by simpa using hg
      simp [target, List.find?_cons, hf, ih]

end AetherFormal.AutoRollback
