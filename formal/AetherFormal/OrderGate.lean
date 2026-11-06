import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.GCongr
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `execution/order_gate.py`

`resolve_runtime_mode`, `resolve_order_permission`, `resolve_cash_sweep_order_permission`,
`resolve_slippage_bps` and `slippage_amount`. A non-finite or unreadable bps estimate is `none`.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.OrderGate

inductive Mode
  | backtest
  | observation
  | paper
  | live
  | other
  deriving DecidableEq, Repr

def Mode.ofString : String → Mode
  | "backtest" => .backtest
  | "observation" => .observation
  | "paper" => .paper
  | "live" => .live
  | _ => .other

def Mode.name : Mode → String
  | .backtest => "backtest"
  | .observation => "observation"
  | .paper => "paper"
  | .live => "live"
  | .other => "other"

/-- `resolve_runtime_mode`: anything that is not one of the four modes fails safe to observation. -/
def resolveRuntimeMode : Option String → Mode
  | none => .observation
  | some s =>
    match Mode.ofString s with
    | .other => .observation
    | m => m

/-- `resolve_order_permission(mode, allow_live_orders, broker_config_present, risk_locks_healthy)`. -/
def permit : Mode → Bool → Bool → Bool → Bool × String
  | .backtest, _, _, _ => (true, "backtest_unrestricted")
  | .observation, _, _, _ => (false, "observation_mode_no_real_orders")
  | .paper, a, b, c =>
    if a && b && c then (true, "paper_orders_enabled")
    else if a && b then (false, "paper_orders_blocked_risk_lock")
    else (false, "paper_orders_blocked_missing_flag_or_broker_config")
  | .live, a, b, c =>
    if a && b && c then (true, "live_orders_enabled")
    else (false, "live_orders_blocked_missing_flag_or_broker_config_or_risk_lock")
  | .other, _, _, _ => (false, "unknown_mode_defaults_to_no_orders")

/-- `resolve_cash_sweep_order_permission`: the strategy's risk locks are not consulted. -/
def permitCashSweep (m : Mode) (a b : Bool) : Bool × String := permit m a b true

/-- `resolve_risk_exit_permission`: an order that takes risk off while a lock is active. The lock isn't consulted. -/
def permitRiskExit (m : Mode) (a b : Bool) : Bool × String :=
  let (allowed, reason) := permit m a b true
  (allowed, "risk_exit:" ++ reason)

/-- The single safety invariant: observation never places a real order. -/
theorem observation_never (a b c : Bool) : (permit .observation a b c).1 = false := rfl

theorem unknown_never (a b c : Bool) : (permit .other a b c).1 = false := rfl

theorem permit_iff (m : Mode) (a b c : Bool) :
    (permit m a b c).1 = true ↔
      m = .backtest ∨ ((m = .paper ∨ m = .live) ∧ a = true ∧ b = true ∧ c = true) := by
  cases m <;> cases a <;> cases b <;> cases c <;> simp [permit]

/-- A tripped risk lock blocks paper and live orders. -/
theorem risk_lock_blocks (m : Mode) (a b : Bool) (hm : m ≠ .backtest) : (permit m a b false).1 = false := by
  cases m <;> cases a <;> cases b <;> simp_all [permit]

theorem cash_sweep_never_in_observation (a b : Bool) : (permitCashSweep .observation a b).1 = false := rfl

theorem risk_exit_never_in_observation (a b : Bool) : (permitRiskExit .observation a b).1 = false := rfl

/-- A lock never freezes a book open: wherever an order would be allowed with no lock, a risk exit still is. -/
theorem risk_exit_ignores_the_lock (m : Mode) (a b : Bool) :
    (permitRiskExit m a b).1 = (permit m a b true).1 := rfl

/-- Anything an order could do, a risk exit can too. -/
theorem permit_implies_risk_exit (m : Mode) (a b c : Bool) (h : (permit m a b c).1 = true) :
    (permitRiskExit m a b).1 = true := by
  cases m <;> cases a <;> cases b <;> cases c <;> simp_all [permit, permitRiskExit]

theorem resolveRuntimeMode_ne_other (s : Option String) : resolveRuntimeMode s ≠ .other := by
  unfold resolveRuntimeMode
  cases s with
  | none => decide
  | some s => cases h : Mode.ofString s <;> simp [h]

section Slippage

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

/-- `resolve_slippage_bps`: a missing or non-finite estimate is 0 bps, otherwise clamped to `[0, max_bps]`
(`min(max(bps, 0), max_bps)`). -/
def resolveBps (raw : Option α) (maxBps : α) : α :=
  match raw with
  | none => 0
  | some b => min (max b 0) maxBps

/-- `slippage_amount`: a non-positive price or bps gives no slippage. -/
def slippageAmount (price bps : α) : α :=
  if price ≤ 0 ∨ bps ≤ 0 then 0 else price * (bps / 10000)

theorem resolveBps_nonneg {maxBps : α} (h : 0 ≤ maxBps) (raw : Option α) : 0 ≤ resolveBps raw maxBps := by
  cases raw with
  | none => simp [resolveBps]
  | some b => exact le_min (le_max_right b 0) h

theorem resolveBps_le (raw : Option α) {maxBps : α} (h : 0 ≤ maxBps) : resolveBps raw maxBps ≤ maxBps := by
  cases raw with
  | none => simpa [resolveBps] using h
  | some b => exact min_le_right _ _

theorem slippageAmount_nonneg (price bps : α) : 0 ≤ slippageAmount price bps := by
  unfold slippageAmount
  split_ifs with h
  · exact le_refl 0
  · push_neg at h
    exact (mul_pos h.1 (div_pos h.2 (by norm_num))).le

/-- Slippage is never negative (never improves the fill) and never exceeds the `max_bps` clamp. -/
theorem fill_slippage_bounded (price : α) (raw : Option α) {maxBps : α} (h : 0 ≤ maxBps) (hp : 0 ≤ price) :
    0 ≤ slippageAmount price (resolveBps raw maxBps) ∧
      slippageAmount price (resolveBps raw maxBps) ≤ price * (maxBps / 10000) := by
  refine ⟨slippageAmount_nonneg _ _, ?_⟩
  unfold slippageAmount
  split_ifs with hc
  · exact mul_nonneg hp (div_nonneg h (by norm_num))
  · have hle := resolveBps_le raw h
    have : resolveBps raw maxBps / 10000 ≤ maxBps / 10000 := by gcongr
    exact mul_le_mul_of_nonneg_left this hp

end Slippage

end AetherFormal.OrderGate
