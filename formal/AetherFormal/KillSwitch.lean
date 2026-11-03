import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `risk/kill_switch.py`

`evaluate_kill_switch`'s trigger logic. The rolling Sharpe is an input (its float arithmetic, `_rolling_sharpe`, is
covered by the differential cases); an unavailable or non-finite metric is `none`.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.KillSwitch

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

inductive Trigger
  | rollingSharpe
  | drawdownVelocity
  | liveRankIc
  | consecutiveLosses
  | slippage
  | modelAge
  | reconciliation
  deriving DecidableEq, Repr

structure Obs (α : Type*) where
  sharpe : Option α
  belowRunLast : Nat
  trippedLast : Bool
  ddVelocity : Option α
  liveIc : Option α
  losses : Option α
  slippage : Option α
  modelAge : Option α
  reconBreach : Bool

structure Thr (α : Type*) where
  minSharpe : α
  release : Option α
  confirm : Nat
  maxDdVelocity : α
  minLiveIc : α
  maxLosses : α
  maxSlippage : α
  maxModelAge : α

def belowFloor (o : Obs α) (t : Thr α) : Bool :=
  match o.sharpe with
  | some s => decide (s < t.minSharpe)
  | none => false

def belowRun (o : Obs α) (t : Thr α) : Nat := if belowFloor o t then o.belowRunLast + 1 else 0

def heldByBand (o : Obs α) (t : Thr α) : Bool :=
  match t.release, o.sharpe with
  | some r, some s => o.trippedLast && decide (s < r)
  | _, _ => false

def above (x : Option α) (cap : α) : Bool := match x with | some v => decide (cap < v) | none => false
def below (x : Option α) (floor : α) : Bool := match x with | some v => decide (v < floor) | none => false

def triggers (o : Obs α) (t : Thr α) : List Trigger :=
  (if o.sharpe.isSome && ((belowFloor o t && decide (max 1 t.confirm ≤ belowRun o t)) || heldByBand o t)
    then [.rollingSharpe] else []) ++
  (if above o.ddVelocity t.maxDdVelocity then [.drawdownVelocity] else []) ++
  (if below o.liveIc t.minLiveIc then [.liveRankIc] else []) ++
  (if above o.losses t.maxLosses then [.consecutiveLosses] else []) ++
  (if above o.slippage t.maxSlippage then [.slippage] else []) ++
  (if above o.modelAge t.maxModelAge then [.modelAge] else []) ++
  (if o.reconBreach then [.reconciliation] else [])

/-- `evaluate_kill_switch(...)` -> (tripped, severity is "critical"). -/
def evaluate (enabled : Bool) (o : Obs α) (t : Thr α) : Bool × Bool :=
  if enabled then
    let ts := triggers o t
    (!ts.isEmpty, decide (1 < ts.length))
  else (false, false)

theorem disabled_never_trips (o : Obs α) (t : Thr α) : (evaluate false o t).1 = false := rfl

theorem tripped_iff (o : Obs α) (t : Thr α) : (evaluate true o t).1 = true ↔ triggers o t ≠ [] := by
  simp [evaluate, List.isEmpty_iff]

theorem critical_iff (o : Obs α) (t : Thr α) : (evaluate true o t).2 = true ↔ 1 < (triggers o t).length := by
  simp [evaluate]

/-- `t'` is at least as strict as `t` on every threshold (same release band). -/
structure Tighter (t t' : Thr α) : Prop where
  sharpe : t.minSharpe ≤ t'.minSharpe
  release : t'.release = t.release
  confirm : t'.confirm ≤ t.confirm
  dd : t'.maxDdVelocity ≤ t.maxDdVelocity
  ic : t.minLiveIc ≤ t'.minLiveIc
  losses : t'.maxLosses ≤ t.maxLosses
  slip : t'.maxSlippage ≤ t.maxSlippage
  age : t'.maxModelAge ≤ t.maxModelAge

theorem above_mono {x : Option α} {c c' : α} (h : c' ≤ c) (hx : above x c = true) : above x c' = true := by
  cases x <;> simp_all [above]; linarith

theorem below_mono {x : Option α} {f f' : α} (h : f ≤ f') (hx : below x f = true) : below x f' = true := by
  cases x <;> simp_all [below]; linarith

theorem belowFloor_mono (o : Obs α) {t t' : Thr α} (h : Tighter t t') (hx : belowFloor o t = true) :
    belowFloor o t' = true := by
  unfold belowFloor at *
  cases hs : o.sharpe <;> simp_all; linarith [h.sharpe]

/-- Tightening any threshold can only add triggers, never remove one. -/
theorem triggers_monotone (o : Obs α) {t t' : Thr α} (h : Tighter t t') (x : Trigger) (hx : x ∈ triggers o t) :
    x ∈ triggers o t' := by
  have hb := belowFloor_mono o h
  have hband : heldByBand o t' = heldByBand o t := by simp [heldByBand, h.release]
  simp only [triggers, List.mem_append] at hx ⊢
  rcases hx with ((((((hx | hx) | hx) | hx) | hx) | hx) | hx)
  · left; left; left; left; left; left
    split_ifs at hx with hc
    · simp only [List.mem_singleton] at hx
      subst hx
      simp only [Bool.and_eq_true, Bool.or_eq_true, decide_eq_true_eq] at hc
      obtain ⟨hsome, hc⟩ := hc
      rw [if_pos]
      · simp
      · simp only [Bool.and_eq_true, Bool.or_eq_true, decide_eq_true_eq, hband]
        refine ⟨hsome, ?_⟩
        rcases hc with ⟨hf, hr⟩ | hband'
        · left
          refine ⟨hb hf, ?_⟩
          have : belowRun o t' = o.belowRunLast + 1 := by simp [belowRun, hb hf]
          have h2 : belowRun o t = o.belowRunLast + 1 := by simp [belowRun, hf]
          rw [this]; rw [h2] at hr
          exact le_trans (max_le_max (le_refl 1) h.confirm) hr
        · right; exact hband'
    · simp at hx
  · left; left; left; left; left; right
    split_ifs at hx with hc
    · rw [if_pos (above_mono h.dd hc)]; exact hx
    · simp at hx
  · left; left; left; left; right
    split_ifs at hx with hc
    · rw [if_pos (below_mono h.ic hc)]; exact hx
    · simp at hx
  · left; left; left; right
    split_ifs at hx with hc
    · rw [if_pos (above_mono h.losses hc)]; exact hx
    · simp at hx
  · left; left; right
    split_ifs at hx with hc
    · rw [if_pos (above_mono h.slip hc)]; exact hx
    · simp at hx
  · left; right
    split_ifs at hx with hc
    · rw [if_pos (above_mono h.age hc)]; exact hx
    · simp at hx
  · right; exact hx

/-- With a confirmation count of k, the floor alone (no latched band) trips only after k bars below it. -/
theorem confirm_bars (o : Obs α) (t : Thr α) (hband : heldByBand o t = false)
    (h : Trigger.rollingSharpe ∈ triggers o t) : max 1 t.confirm ≤ belowRun o t := by
  simp only [triggers, List.mem_append] at h
  rcases h with ((((((h | h) | h) | h) | h) | h) | h)
  · split_ifs at h with hc
    · simp only [hband, Bool.or_false, Bool.and_eq_true, decide_eq_true_eq] at hc
      exact hc.2.2
    · simp at h
  all_goals (split_ifs at h <;> simp at h)

end AetherFormal.KillSwitch
