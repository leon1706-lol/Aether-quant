import Mathlib.Order.Basic

/-!
# `execution/accounts.py`: `apply_risk_overrides` never loosens a limit

An account's risk override is applied only if it is at least as strict as the base config: a "lower is tighter" limit
(a drawdown cap, leverage, a kill-switch maximum) may only go down, a "higher is tighter" one (the kill switch's minimum
rolling Sharpe) only up, the live-orders flag only off, and the runtime mode only down (observation < paper < live).
Anything looser is refused, so a registry can never widen what the base config allows.
-/

namespace AetherFormal.AccountOverrides

inductive Direction where
  | lower
  | higher
  deriving DecidableEq, Repr

variable {α : Type*} [LinearOrder α]

/-- `_check_tighter` then `_set` for a numeric key: the value applied, or `none` when refused. A key the base config
does not set takes any value (there is nothing to loosen). -/
def applyOverride (d : Direction) (base : Option α) (value : α) : Option α :=
  match d, base with
  | _, none => some value
  | .lower, some b => if value ≤ b then some value else none
  | .higher, some b => if b ≤ value then some value else none

/-- The live-orders flag: an account may only switch it off. -/
def applyFlag (value : Bool) : Option Bool := if value = false then some false else none

/-- The runtime mode as a rank (1 observation, 2 paper, 3 live): an account may only lower it. -/
def applyMode (current account : Nat) : Option Nat := if account ≤ current then some account else none

theorem lower_never_loosens (b v r : α) (h : applyOverride .lower (some b) v = some r) : r ≤ b := by
  by_cases hv : v ≤ b
  · have e : applyOverride .lower (some b) v = some v := by simp [applyOverride, hv]
    rw [e] at h
    rw [← Option.some.inj h]
    exact hv
  · have e : applyOverride .lower (some b) v = none := by simp [applyOverride, hv]
    rw [e] at h
    exact absurd h (by simp)

theorem higher_never_loosens (b v r : α) (h : applyOverride .higher (some b) v = some r) : b ≤ r := by
  by_cases hv : b ≤ v
  · have e : applyOverride .higher (some b) v = some v := by simp [applyOverride, hv]
    rw [e] at h
    rw [← Option.some.inj h]
    exact hv
  · have e : applyOverride .higher (some b) v = none := by simp [applyOverride, hv]
    rw [e] at h
    exact absurd h (by simp)

theorem looser_lower_refused (b v : α) (h : b < v) : applyOverride .lower (some b) v = none := by
  have hv : ¬ v ≤ b := not_le.mpr h
  simp [applyOverride, hv]

theorem looser_higher_refused (b v : α) (h : v < b) : applyOverride .higher (some b) v = none := by
  have hv : ¬ b ≤ v := not_le.mpr h
  simp [applyOverride, hv]

theorem unset_base_accepts (d : Direction) (v : α) : applyOverride d none v = some v := by
  cases d <;> rfl

theorem flag_only_off (v r : Bool) (h : applyFlag v = some r) : r = false := by
  cases v
  · have e : applyFlag false = some false := by simp [applyFlag]
    rw [e] at h
    exact (Option.some.inj h).symm
  · have e : applyFlag true = none := by simp [applyFlag]
    rw [e] at h
    exact absurd h (by simp)

theorem mode_never_raised (c a r : Nat) (h : applyMode c a = some r) : r ≤ c := by
  by_cases ha : a ≤ c
  · have e : applyMode c a = some a := by simp [applyMode, ha]
    rw [e] at h
    rw [← Option.some.inj h]
    exact ha
  · have e : applyMode c a = none := by simp [applyMode, ha]
    rw [e] at h
    exact absurd h (by simp)

end AetherFormal.AccountOverrides
