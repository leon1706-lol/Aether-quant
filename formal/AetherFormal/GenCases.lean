import AetherFormal.OrderGate
import AetherFormal.HashChain
import AetherFormal.BookNeutrality
import AetherFormal.BookConstruction
import AetherFormal.RiskControls
import AetherFormal.KillSwitch
import AetherFormal.PositionSizing
import AetherFormal.CostModel
import AetherFormal.Reconciliation
import AetherFormal.SleeveGuard
import AetherFormal.JsonSafety
import AetherFormal.GenerationBlend
import AetherFormal.GenerationGlide
import AetherFormal.Admission
import AetherFormal.SessionResolve
import AetherFormal.HoldoutOnce
import AetherFormal.AccountOverrides
import AetherFormal.Authorize
import AetherFormal.RlSizing
import AetherFormal.DrawdownGuard
import AetherFormal.BacktestGate
import AetherFormal.AutoRollback
import AetherFormal.PremiaCaps
import AetherFormal.Rebalance
import AetherFormal.CashSweep
import AetherFormal.DynamicTargets
import AetherFormal.ForexCap
import AetherFormal.VolTarget
import Mathlib.Algebra.Order.Field.Rat
import Mathlib.Data.Rat.Floor
import Lean.Data.Json

/-!
# Differential cases

`lake env lean --run AetherFormal/GenCases.lean <out-dir>` (what `aq prove --regen-cases` runs) runs every model at `ℚ` on seeded pseudo-random inputs (plus fixed edge cases) and writes
`<out-dir>/<target>.json`; `tests/test_formal_differential_*.py` feed the same inputs to the Python functions.
A rational is `{"num": n, "den": d}`. `aq prove --regen-cases` adds each file's `spec_sha256`.
-/

open Lean

namespace AetherFormal.GenCases

abbrev Gen := StateM Nat

def nextNat (bound : Nat) : Gen Nat := do
  let s ← get
  let s' := (s * 6364136223846793005 + 1442695040888963407) % 18446744073709551616
  set s'
  return (s' / 8589934592) % (max bound 1)

def randBool : Gen Bool := do return (← nextNat 2) == 1

/-- Uniform on the grid `{lo, lo + 1/den, ..., hi}`. -/
def randQ (lo hi : Int) (den : Nat := 100) : Gen ℚ := do
  let span := ((hi - lo) * den).toNat + 1
  let k ← nextNat span
  return ((lo * den + (k : Int) : Int) : ℚ) / (den : ℚ)

def pick {β : Type} [Inhabited β] (xs : List β) : Gen β := do
  return xs.getD (← nextNat xs.length) default

def qj (q : ℚ) : Json := Json.mkObj [("num", toJson q.num), ("den", toJson q.den)]
def oqj : Option ℚ → Json
  | some q => qj q
  | none => Json.null

def genList {β : Type} (n : Nat) (g : Gen β) : Gen (List β) := do
  let mut out := []
  for _ in [0:n] do
    out := out ++ [← g]
  return out

def file (target : String) (specs : List String) (cases : List Json) : Json :=
  Json.mkObj [("target", target), ("spec_files", toJson specs), ("cases", Json.arr cases.toArray)]

/-! ### order_gate -/

open OrderGate in
def orderGate : Gen Json := do
  let modes : List (String × Mode) :=
    [("backtest", .backtest), ("observation", .observation), ("paper", .paper), ("live", .live), ("bogus", .other)]
  let bools := [false, true]
  let mut cases : List Json := []
  for (name, m) in modes do
    for a in bools do
      for b in bools do
        for c in bools do
          let (ok, reason) := permit m a b c
          let (cok, creason) := permitCashSweep m a b
          let (xok, xreason) := permitRiskExit m a b
          cases := cases ++ [Json.mkObj [("kind", "permission"),
            ("input", Json.mkObj [("mode", name), ("allow_live_orders", a), ("broker_config_present", b),
              ("risk_locks_healthy", c)]),
            ("expected", Json.mkObj [("permitted", ok), ("reason", reason), ("cash_sweep_permitted", cok),
              ("cash_sweep_reason", creason), ("risk_exit_permitted", xok), ("risk_exit_reason", xreason)])]]
  for raw in [some "backtest", some "observation", some "paper", some "live", some "LIVE", some "", none] do
    cases := cases ++ [Json.mkObj [("kind", "runtime_mode"), ("input", Json.mkObj [("raw", toJson raw)]),
      ("expected", Json.mkObj [("mode", (resolveRuntimeMode raw).name)])]]
  for _ in [0:200] do
    let present ← randBool
    let raw : Option ℚ ← if present then some <$> randQ (-50) 800 else pure none
    let maxBps ← pick [(500 : ℚ), 100, 25, 0]
    let price ← randQ (-5) 300
    let bps := resolveBps raw maxBps
    cases := cases ++ [Json.mkObj [("kind", "slippage"),
      ("input", Json.mkObj [("raw_bps", oqj raw), ("max_bps", qj maxBps), ("price", qj price)]),
      ("expected", Json.mkObj [("bps", qj bps), ("amount", qj (slippageAmount price bps))])]]
  return file "order_gate" ["AetherFormal/OrderGate.lean"] cases

/-! ### hash_chain -/

open HashChain in
def toyH (p e c x : String) : String := p ++ "|" ++ e ++ "|" ++ c ++ "|" ++ x

open HashChain in
def buildChain (n : Nat) : List Row := Id.run do
  let mut rows : List Row := []
  let mut prev := "GENESIS"
  for i in [0:n] do
    let r : Row := ⟨prev, toyH prev "e" (s!"t{i}") (s!"p{i}"), "e", (s!"t{i}"), (s!"p{i}")⟩
    rows := rows ++ [r]
    prev := r.hash
  return rows

open HashChain in
def hashChain : Gen Json := do
  let mut cases : List Json := []
  for n in [0:9] do
    for kind in ["none", "payload", "prev", "hash", "delete", "truncate"] do
      let idx ← nextNat (max n 1)
      let rows := buildChain n
      let tampered : List Row :=
        if n = 0 then rows
        else
          let edit (f : Row → Row) : List Row := match rows[idx]? with
            | some r => rows.set idx (f r)
            | none => rows
          match kind with
          | "payload" => edit fun r => { r with payload := r.payload ++ "x" }
          | "prev" => edit fun r => { r with prev := "BAD" }
          | "hash" => edit fun r => { r with hash := "BAD" }
          | "delete" => rows.eraseIdx idx
          | "truncate" => rows.take idx
          | _ => rows
      let (ok, at_) := verify toyH "GENESIS" tampered
      cases := cases ++ [Json.mkObj [
        ("input", Json.mkObj [("length", n), ("tamper", kind), ("index", idx)]),
        ("expected", Json.mkObj [("valid", ok), ("first_broken_index", toJson at_)])]]
  return file "hash_chain" ["AetherFormal/HashChain.lean"] cases

/-! ### book_neutrality -/

open BookNeutrality in
def bookNeutrality : Gen Json := do
  let mut cases : List Json := []
  -- the counterexample book first
  let fixed : List (List (Entry ℚ) × Config ℚ) :=
    [(counterBook, counterConfig), (counterBook, { counterConfig with reapply := true }), ([], counterConfig)]
  let mut inputs := fixed
  for _ in [0:250] do
    let n ← nextNat 9
    let mut book : List (Entry ℚ) := []
    for i in [0:n] do
      let sector ← nextNat 4
      let w ← randQ (-1) 1
      book := book ++ [⟨i, sector, w / 2⟩]
    let cfg : Config ℚ := {
      nameCap := ← pick [(12 / 100 : ℚ), 3 / 10, 1, 0, -1 / 10]
      sectorOn := ← randBool
      sectorCap := ← pick [(5 / 100 : ℚ), 15 / 100, 0]
      dollarOn := ← randBool
      grossCap := ← pick [(1 : ℚ), 1 / 2, 0, 10]
      reapply := ← randBool }
    inputs := inputs ++ [(book, cfg)]
  for (book, cfg) in inputs do
    let out := neutralize cfg book
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [
        ("weights", Json.arr (book.map fun e => Json.mkObj [("sym", e.sym), ("sector", e.sector), ("w", qj e.w)]).toArray),
        ("max_weight_per_name", qj cfg.nameCap), ("sector_neutral", cfg.sectorOn),
        ("sector_max_net_weight", qj cfg.sectorCap), ("dollar_neutral", cfg.dollarOn),
        ("gross_exposure_cap", qj cfg.grossCap), ("reapply_sector_cap_after_dollar_neutral", cfg.reapply)]),
      ("expected", Json.mkObj [("weights", Json.arr (out.map fun e => Json.mkObj [("sym", e.sym), ("w", qj e.w)]).toArray)])]]
  return file "book_neutrality" ["AetherFormal/BookNeutrality.lean"] cases

/-! ### book_construction -/

def funOfList {n : Nat} (xs : List ℚ) : Fin n → ℚ := fun i => xs.getD i.val 0
def listOfFun {n : Nat} (f : Fin n → ℚ) : List ℚ := (List.finRange n).map f

open BookConstruction in
def bookConstruction : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:120] do
    let top ← nextNat 13
    let bottom ← nextNat 13
    let k := (← nextNat 4) + 1
    let cap ← randQ 0 2
    cases := cases ++ [Json.mkObj [("kind", "tranche_params"),
      ("input", Json.mkObj [("top_n", top), ("bottom_n", bottom), ("gross_exposure_cap", qj cap), ("tranches", k)]),
      ("expected", Json.mkObj [("top_n", if top = 0 then 0 else ceilDiv top k),
        ("bottom_n", if bottom = 0 then 0 else ceilDiv bottom k), ("gross_exposure_cap", qj (cap / k))])]]
  for _ in [0:150] do
    let n := (← nextNat 6) + 1
    let cur ← genList n (do if ← randBool then randQ (-1) 1 (den := 50) else pure 0)
    let tgt ← genList n (do if ← randBool then randQ (-1) 1 (den := 50) else pure 0)
    let f ← pick [(0 : ℚ), 1 / 4, 1 / 2, 1, 3 / 2]
    let out := partialAdjust (n := n) f (1 / 1000) (funOfList cur) (funOfList tgt)
    cases := cases ++ [Json.mkObj [("kind", "partial_adjust"),
      ("input", Json.mkObj [("current", toJson (cur.map qj)), ("target", toJson (tgt.map qj)), ("fraction", qj f),
        ("min_weight", qj (1 / 1000))]),
      ("expected", Json.mkObj [("weights", toJson ((listOfFun out).map qj))])]]
  for _ in [0:100] do
    let n := (← nextNat 6) + 1
    let m := (← nextNat 3) + 1
    let ts ← genList m (genList n (do if ← randBool then randQ (-1) 1 (den := 20) else pure 0))
    let out := combine (n := n) (ts.map funOfList)
    cases := cases ++ [Json.mkObj [("kind", "combine"),
      ("input", Json.mkObj [("tranches", toJson (ts.map fun t => t.map qj))]),
      ("expected", Json.mkObj [("weights", toJson ((listOfFun out).map qj))])]]
  for _ in [0:150] do
    let n := (← nextNat 7) + 1
    let w ← genList n (randQ (-1) 1 (den := 50))
    let crypto ← genList n randBool
    let exempt ← genList n randBool
    let perName ← pick [none, some (5 / 100 : ℚ), some (1 / 5)]
    let classGross ← pick [none, some (1 / 10 : ℚ), some (1 / 2)]
    let inClass : Fin n → Bool := fun i => crypto.getD i.val false && !exempt.getD i.val false
    let out := classCap inClass perName classGross (funOfList w)
    cases := cases ++ [Json.mkObj [("kind", "class_caps"),
      ("input", Json.mkObj [("weights", toJson (w.map qj)), ("crypto", toJson crypto), ("exempt", toJson exempt),
        ("per_name_cap", oqj perName), ("class_gross_cap", oqj classGross)]),
      ("expected", Json.mkObj [("weights", toJson ((listOfFun out).map qj))])]]
  for _ in [0:200] do
    let n ← nextNat 11
    let mut pool : List (Nat × ℚ) := []
    for i in [0:n] do
      pool := pool ++ [(i, ← randQ 0 1 (den := 20))]
    let top ← nextNat 5
    let bottom ← nextNat 5
    let (longs, shorts) := selectBook pool top bottom
    cases := cases ++ [Json.mkObj [("kind", "select"),
      ("input", Json.mkObj [("ranks", toJson (pool.map fun p => qj p.2)), ("top_n", top), ("bottom_n", bottom)]),
      ("expected", Json.mkObj [("longs", toJson longs), ("shorts", toJson shorts)])]]
  return file "book_construction" ["AetherFormal/BookConstruction.lean"] cases

/-! ### risk_controls -/

open RiskControls in
def riskControls : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:200] do
    let w ← randQ (-1) 1
    let cur ← randQ 0 2 (den := 20)
    let cap ← randQ 0 2 (den := 20)
    let (out, blocked) := capTargetWeight (some w) cur cap
    cases := cases ++ [Json.mkObj [("kind", "cap_target_weight"),
      ("input", Json.mkObj [("target", qj w), ("current", qj cur), ("cap", qj cap)]),
      ("expected", Json.mkObj [("weight", qj out), ("blocked", blocked)])]]
  for _ in [0:150] do
    let d ← randQ (-1) 0 (den := 50)
    let t ← randQ (-1) 0 (den := 50)
    let md ← randQ 0 1 (den := 50)
    let mt ← randQ 0 1 (den := 50)
    let (locked, reason) := drawdownLock d t md mt
    cases := cases ++ [Json.mkObj [("kind", "drawdown_lock"),
      ("input", Json.mkObj [("daily", qj d), ("total", qj t), ("max_daily", qj md), ("max_total", qj mt)]),
      ("expected", Json.mkObj [("locked", locked), ("reason", toJson reason)])]]
  return file "risk_controls" ["AetherFormal/RiskControls.lean"] cases

/-! ### kill_switch -/

def optQ (lo hi : Int) : Gen (Option ℚ) := do if ← randBool then some <$> randQ lo hi else pure none

open KillSwitch in
def triggerName : Trigger → String
  | .rollingSharpe => "rolling_sharpe_below_floor"
  | .drawdownVelocity => "drawdown_velocity_above_cap"
  | .liveRankIc => "live_rank_ic_below_floor"
  | .consecutiveLosses => "consecutive_losses_above_cap"
  | .slippage => "slippage_divergence_above_cap"
  | .modelAge => "model_age_above_cap"
  | .reconciliation => "reconciliation_breach"

open KillSwitch in
def killSwitch : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:300] do
    let o : Obs ℚ := {
      sharpe := ← optQ (-3) 3, belowRunLast := ← nextNat 4, trippedLast := ← randBool, ddVelocity := ← optQ (-1) 1,
      liveIc := ← optQ (-1) 1, losses := ← optQ 0 10, slippage := ← optQ 0 100, modelAge := ← optQ 0 200,
      reconBreach := (← nextNat 5) == 0 }
    let t : Thr ℚ := {
      minSharpe := ← randQ (-2) 1, release := ← optQ (-1) 1, confirm := ← nextNat 4, maxDdVelocity := ← randQ 0 1,
      minLiveIc := ← randQ (-1) 1, maxLosses := ← randQ 1 8, maxSlippage := ← randQ 5 80, maxModelAge := ← randQ 10 180 }
    let enabled := (← nextNat 6) != 0
    let (tripped, critical) := evaluate enabled o t
    let ts := if enabled then (triggers o t).map triggerName else []
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("enabled", enabled), ("rolling_sharpe", oqj o.sharpe),
        ("rolling_sharpe_below_run_last_bar", o.belowRunLast), ("rolling_sharpe_tripped_last_bar", o.trippedLast),
        ("drawdown_velocity_pct_per_bar", oqj o.ddVelocity), ("live_rank_ic", oqj o.liveIc),
        ("consecutive_losses", oqj o.losses), ("slippage_divergence_bps", oqj o.slippage),
        ("model_age_days", oqj o.modelAge), ("reconciliation_breach", o.reconBreach),
        ("min_rolling_sharpe", qj t.minSharpe), ("release_rolling_sharpe", oqj t.release),
        ("trip_confirm_bars", t.confirm), ("max_drawdown_velocity_pct_per_bar", qj t.maxDdVelocity),
        ("min_live_rank_ic", qj t.minLiveIc), ("max_consecutive_losses", qj t.maxLosses),
        ("max_slippage_divergence_bps", qj t.maxSlippage), ("max_model_age_days", qj t.maxModelAge)]),
      ("expected", Json.mkObj [("tripped", tripped), ("critical", critical), ("triggers", toJson ts)])]]
  return file "kill_switch" ["AetherFormal/KillSwitch.lean"] cases

/-! ### position_sizing -/

open PositionSizing in
def positionSizing : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:250] do
    let base ← randQ (-1) 1 (den := 20)
    let conf ← randQ (-1) 2 (den := 10)
    let maxPos ← pick [(1 / 10 : ℚ), 1 / 5, 0]
    let minPos ← pick [(0 : ℚ), 1 / 50, 1 / 2]
    let rank ← randQ 0 1 (den := 20)
    let lo ← pick [(3 / 4 : ℚ), -2, 0]
    let hi ← pick [(5 / 4 : ℚ), 1]
    let c := max 0 (min conf 1)
    let mult := (1 / 2 + c / 2) * rankMult rank lo hi
    let out := size (some base) conf maxPos minPos mult
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("base_target_weight", qj base), ("confidence", qj conf), ("max_position_weight", qj maxPos),
        ("min_position_weight", qj minPos), ("predicted_rank_20d", qj rank), ("min_rank_multiplier", qj lo),
        ("max_rank_multiplier", qj hi)]),
      ("expected", Json.mkObj [("target_weight", qj out), ("rank_multiplier", qj (rankMult rank lo hi))])]]
  return file "position_sizing" ["AetherFormal/PositionSizing.lean"] cases

/-! ### cost_model -/

open CostModel in
def costModel : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:120] do
    let isLimit ← randBool
    let r ← randQ (-1) 2 (den := 10)
    let maker ← randQ 0 10 (den := 10)
    let taker ← randQ 0 10 (den := 10)
    cases := cases ++ [Json.mkObj [("kind", "fill_fee"),
      ("input", Json.mkObj [("is_limit_route", isLimit), ("fill_rate", qj r), ("maker_bps", qj maker), ("taker_bps", qj taker)]),
      ("expected", Json.mkObj [("fee_bps", qj (fillFee isLimit r maker taker))])]]
  for _ in [0:120] do
    let lf ← randQ 0 1 (den := 1000)
    let c ← randQ 0 10 (den := 10)
    let m ← randQ 0 3 (den := 10)
    let v ← randQ (-100) 5000 (den := 1)
    let x ← randQ 0 5 (den := 10)
    cases := cases ++ [Json.mkObj [("kind", "round_trip"),
      ("input", Json.mkObj [("liquidity_fraction", qj lf), ("commission_bps_per_side", qj c), ("min_commission_usd", qj m),
        ("order_value", qj v), ("extra_slippage_bps", qj x)]),
      ("expected", Json.mkObj [("cost_bps", qj (roundTripCost lf c m v x))])]]
  for _ in [0:120] do
    let rank ← randQ 0 1 (den := 20)
    let pu ← randQ 0 50 (den := 2)
    let h ← nextNat 40
    let t ← nextNat 30
    let d : Int ← pick [1, -1]
    cases := cases ++ [Json.mkObj [("kind", "edge"),
      ("input", Json.mkObj [("rank", qj rank), ("edge_bps_per_rank_unit", qj pu), ("holding_bars", h), ("horizon_days", t),
        ("trade_direction", d)]),
      ("expected", Json.mkObj [("edge_bps", qj (edge rank pu h t d))])]]
  return file "cost_model" ["AetherFormal/CostModel.lean"] cases

/-! ### reconciliation -/

open Reconciliation in
def clsName : Cls → String
  | .matched => "matched"
  | .drifted => "drifted"
  | .orphan => "orphan_broker"
  | .missing => "missing_broker"

open Reconciliation in
def reconciliation : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:200] do
    let n ← nextNat 7
    let mut rows : List (Row ℚ) := []
    for i in [0:n] do
      let k ← nextNat 4
      let e ← randQ (-1) 1 (den := 200)
      let a ← randQ (-1) 1 (den := 200)
      let near ← randQ (-1) 1 (den := 2000)
      let row : Row ℚ := match k with
        | 0 => ⟨i, some e, none⟩
        | 1 => ⟨i, none, some a⟩
        | 2 => ⟨i, some e, some (e + near / 10)⟩
        | _ => ⟨i, some e, some a⟩
      rows := rows ++ [row]
    let wt ← pick [(1 / 100 : ℚ), 1 / 20]
    let vt ← pick [(10 : ℚ), 100]
    let pv ← pick [(1000 : ℚ), 100000]
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("rows", Json.arr (rows.map fun r => Json.mkObj [("sym", r.sym), ("expected", oqj r.exp),
          ("actual", oqj r.act)]).toArray),
        ("weight_tolerance", qj wt), ("value_tolerance_usd", qj vt), ("portfolio_value", qj pv)]),
      ("expected", Json.mkObj [
        ("classes", Json.arr (rows.map fun r => Json.str (clsName (classify wt vt pv r.exp r.act))).toArray),
        ("max_abs_weight_drift", qj (maxDrift wt vt pv rows))])]]
  return file "reconciliation" ["AetherFormal/Reconciliation.lean"] cases

/-! ### sleeve_guard -/

open SleeveGuard in
def sleeveGuard : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:200] do
    let n ← nextNat 12
    let xs ← genList n (randQ (-5) 5 (den := 10))
    let lb : Int := ((← nextNat 15 : Nat) : Int) - 2
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("pnl_increments", toJson (xs.map qj)), ("lookback_bars", lb)]),
      ("expected", Json.mkObj [("drawdown", qj (trailingDrawdown xs lb))])]]
  return file "sleeve_guard" ["AetherFormal/SleeveGuard.lean"] cases

/-! ### generation_blend -/

open GenerationBlend in
def generationBlend : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:300] do
    let total ← randQ 2 100 100
    let split ← randQ 0 100 100
    let new : ℚ := if (← randBool) then 0 else total * split / 100 / 100
    let old : ℚ := max 0 (total / 100 - new)
    let cap : ℚ := if (← randBool) then 1 else 3 / 10
    let entry ← randQ 0 1 20
    let glide := (← nextNat 500) + 1
    let limitPercent ← nextNat 11
    let limit : ℚ := (limitPercent : ℚ) / 100
    let step : ℚ := (1 - entry) / (glide : ℚ)
    let newBelowCap : ℚ := min new cap
    let result := update old newBelowCap cap entry step limit
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("old", qj old), ("new", qj newBelowCap), ("cap", qj cap), ("entry_share", qj entry), ("glide_sessions", glide), ("retire_share", qj limit)]),
      ("expected", Json.mkObj [("old", qj result.1), ("new", qj result.2)])]]
  return file "generation_blend" ["AetherFormal/GenerationBlend.lean"] cases

/-! ### generation_glide -/

open GenerationGlide in
def generationGlide : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:300] do
    let s ← randQ 0 1 100
    let t ← randQ 0 1 100
    let fraction ← randQ 0 1 100
    let limitPercent ← nextNat 11
    let limit : ℚ := (limitPercent : ℚ) / 100
    let target : ℚ := if (← randBool) then 0 else t
    let count ← nextNat 2000
    let priorCount := (← nextNat 1000) + 1
    let obs ← randQ (-3) 3 100
    let prior ← randQ (-1) 2 100
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("share", qj s), ("target", qj target), ("fraction", qj fraction), ("retire_share", qj limit), ("sessions", count), ("prior_sessions", priorCount), ("observed", qj obs), ("prior", qj prior)]),
      ("expected", Json.mkObj [("share", qj (retireIfHeadedOut (step s target fraction) target limit)), ("score", qj (shrunk (count : ℚ) obs prior (priorCount : ℚ)))])]]
  return file "generation_glide" ["AetherFormal/GenerationGlide.lean"] cases

/-! ### json_safety -/

open JsonSafety in
mutual
  partial def jToJson : J ℚ → Json
    | .null => Json.mkObj [("t", "null")]
    | .bool b => Json.mkObj [("t", "bool"), ("v", b)]
    | .int i => Json.mkObj [("t", "int"), ("v", i)]
    | .num x true => Json.mkObj [("t", "num"), ("v", qj x)]
    | .num x false => Json.mkObj [("t", "nonfinite"), ("v", Json.str (if x < 0 then "-inf" else if x = 0 then "nan" else "inf"))]
    | .str s => Json.mkObj [("t", "str"), ("v", s)]
    | .arr xs => Json.mkObj [("t", "arr"), ("v", Json.arr (jListToJson xs).toArray)]
    | .obj kvs => Json.mkObj [("t", "obj"), ("v", Json.arr (jObjToJson kvs).toArray)]
  partial def jListToJson : JList ℚ → List Json
    | .nil => []
    | .cons j rest => jToJson j :: jListToJson rest
  partial def jObjToJson : JObj ℚ → List Json
    | .nil => []
    | .cons k j rest => Json.arr #[Json.str k, jToJson j] :: jObjToJson rest
end

instance : Inhabited (JsonSafety.J ℚ) := ⟨.null⟩

open JsonSafety in
partial def genJ (depth : Nat) : Gen (J ℚ) := do
  let k ← nextNat (if depth = 0 then 6 else 8)
  match k with
  | 0 => return .null
  | 1 => return .bool (← randBool)
  | 2 => return .int (((← nextNat 200 : Nat) : Int) - 100)
  | 3 => return .num (← randQ (-10) 10) true
  | 4 => return .num (((← nextNat 3 : Nat) : ℚ) - 1) false
  | 5 => return .str (s!"s{← nextNat 50}")
  | 6 => do
    let n ← nextNat 4
    let mut xs : JList ℚ := .nil
    for _ in [0:n] do
      xs := .cons (← genJ (depth - 1)) xs
    return .arr xs
  | _ => do
    let n ← nextNat 4
    let mut kvs : JObj ℚ := .nil
    for i in [0:n] do
      kvs := .cons (s!"k{i}") (← genJ (depth - 1)) kvs
    return .obj kvs

open JsonSafety in
def jsonSafety : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:200] do
    let j ← genJ 3
    cases := cases ++ [Json.mkObj [("input", jToJson j), ("expected", jToJson (sanitize j))]]
  return file "json_safety" ["AetherFormal/JsonSafety.lean"] cases

/-! ### admission -/

open Admission in
def stageName : Stage → String
  | .candidate => "candidate"
  | .frozen => "frozen"
  | .shadow => "shadow"
  | .ramping => "ramping"
  | .active => "active"
  | .fading => "fading"
  | .windingDown => "winding_down"
  | .retired => "retired"
  | .rejected => "rejected"

open Admission in
def tierName : Tier → String
  | .installed => "installed"
  | .tier1 => "tier1"
  | .tier2 => "tier2"
  | .none => "none"

open Admission in
def decayName : Decay → String
  | .healthy => "healthy"
  | .watch => "watch"
  | .decaying => "decaying"
  | .dead => "dead"

open Admission in
def scoreName : Score → String
  | .absent => "absent"
  | .positive => "positive"
  | .nonpositive => "nonpositive"
  | .nan => "nan"

open Admission in
def admission : Gen Json := do
  let stages : List Stage := [.candidate, .frozen, .shadow, .ramping, .active, .fading, .windingDown, .retired, .rejected]
  let tiers : List Tier := [.installed, .tier1, .tier2, .none]
  let decays : List Decay := [.healthy, .watch, .decaying, .dead]
  let scores : List Score := [.absent, .positive, .nonpositive, .nan]
  let counts : List Nat := [0, 1, 59, 60, 61, 100, 251, 252, 253, 504, 1000]
  let caps : List ℚ := [3 / 10, 15 / 100, 1 / 2]
  let mut cases : List Json := []
  for _ in [0:800] do
    let tier ← pick tiers
    let stage ← pick stages
    let e : Ev := {
      selectionPass := ← randBool, holdPass := ← randBool, edgePass := (← nextNat 4) == 0, holdoutsSpent := ← randBool, forwardOk := ← pick counts, noDataOk := ← randBool,
      diffOk := ← randBool, guardTripped := (← nextNat 5) == 0, decay := ← pick decays, alphaLifted := ← randBool, score := ← pick scores }
    let cap ← pick caps
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [
        ("tier", tierName tier), ("stage", stageName stage), ("selection_pass", e.selectionPass), ("hold_pass", e.holdPass), ("edge_pass", e.edgePass), ("holdouts_spent", e.holdoutsSpent),
        ("forward_ok", e.forwardOk), ("no_data_ok", e.noDataOk), ("diff_ok", e.diffOk), ("guard_tripped", e.guardTripped), ("decay", decayName e.decay), ("alpha_lifted", e.alphaLifted),
        ("score", scoreName e.score), ("cap", qj cap)]),
      ("expected", Json.mkObj [("stage", stageName (nextStage tier stage e)), ("cap", qj (shareCap tier stage e cap))])]]
  return file "admission" ["AetherFormal/Admission.lean"] cases

/-! ### session_resolve -/

open SessionResolve in
def sessionResolve : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:400] do
    let count ← nextNat 12
    let mut sessions : List Nat := []
    for _ in [0:count] do
      sessions := sessions ++ [← nextNat 60]
    let now ← nextNat 70
    let overridden ← randBool
    let o ← nextNat 70
    let ov : Option Nat := if overridden then some o else none
    let out := resolve sessions now ov
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("sessions", toJson sessions), ("now", now), ("override", match ov with | some v => toJson v | none => Json.null)]),
      ("expected", Json.mkObj [("session", match out with | some v => toJson v | none => Json.null)])]]
  return file "session_resolve" ["AetherFormal/SessionResolve.lean"] cases

/-! ### holdout_once -/

open HoldoutOnce in
def holdoutOnce : Gen Json := do
  let names : List String := ["V1", "V2", "V3", "P", "CV", "CS"]
  let mut cases : List Json := []
  for _ in [0:300] do
    let ledgerSize ← nextNat 4
    let mut ledger : List String := []
    for _ in [0:ledgerSize] do
      let c ← pick names
      if !(ledger.contains c) then ledger := ledger ++ [c]
    let readSize := (← nextNat 3) + 1
    let mut cells : List String := []
    for _ in [0:readSize] do
      let c ← pick names
      if !(cells.contains c) then cells := cells ++ [c]
    let out := record ledger cells
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("ledger", toJson ledger), ("cells", toJson cells)]),
      ("expected", Json.mkObj [("refused", out.isNone), ("ledger", toJson (out.getD ledger))])]]
  return file "holdout_once" ["AetherFormal/HoldoutOnce.lean"] cases

/-! ### account_overrides -/

open AccountOverrides in
def accountOverrides : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:320] do
    let kind ← nextNat 4
    if kind < 2 then
      let d := if kind == 0 then Direction.lower else Direction.higher
      let b ← randQ (-5) 5
      let v ← randQ (-5) 5
      let unset ← nextNat 4
      let base : Option ℚ := if unset == 0 then none else some b
      let out := applyOverride d base v
      cases := cases ++ [Json.mkObj [
        ("input", Json.mkObj [("kind", toJson (if kind == 0 then "lower" else "higher")), ("base", oqj base), ("value", qj v)]),
        ("expected", Json.mkObj [("refused", toJson out.isNone), ("value", oqj out)])]]
    else if kind == 2 then
      let v ← randBool
      let out := applyFlag v
      cases := cases ++ [Json.mkObj [
        ("input", Json.mkObj [("kind", toJson "flag"), ("value", toJson v)]),
        ("expected", Json.mkObj [("refused", toJson out.isNone)])]]
    else
      let c := (← nextNat 3) + 1
      let a := (← nextNat 3) + 1
      let out := applyMode c a
      cases := cases ++ [Json.mkObj [
        ("input", Json.mkObj [("kind", toJson "mode"), ("current", toJson c), ("account", toJson a)]),
        ("expected", Json.mkObj [("refused", toJson out.isNone), ("mode", match out with | some m => toJson m | none => Json.null)])]]
  return file "account_overrides" ["AetherFormal/AccountOverrides.lean"] cases

/-! ### authorize -/

open Authorize in
def authorizeCases : Gen Json := do
  let names : List String := ["a", "b", "c"]
  let mut cases : List Json := []
  for _ in [0:400] do
    let anonymous := (← nextNat 5) == 0
    let role := (← nextNat 3) + 1
    let everyAccount ← randBool
    let size ← nextNat 3
    let mut accounts : List String := []
    for _ in [0:size] do
      let name ← pick names
      if !(accounts.contains name) then accounts := accounts ++ [name]
    let required := (← nextNat 3) + 1
    let named := (← nextNat 4) != 0
    let target ← pick names
    let account : Option String := if named then some target else none
    let authRequired ← randBool
    let user : Option User := if anonymous then none else some { role := role, all := everyAccount, accounts := accounts }
    let out := authorize user required account authRequired
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("anonymous", toJson anonymous), ("role", toJson role), ("all", toJson everyAccount), ("accounts", toJson accounts),
        ("required", toJson required), ("account", match account with | some s => toJson s | none => Json.null), ("auth_required", toJson authRequired)]),
      ("expected", Json.mkObj [("granted", toJson out)])]]
  return file "authorize" ["AetherFormal/Authorize.lean"] cases

/-! ### V6.6.7 targets. Grids are dyadic (den 8 or 16), so the Python's floats are exact at every comparison. -/

def optQ8 (lo hi : Int) (noneOneIn : Nat) : Gen (Option ℚ) := do
  if (← nextNat noneOneIn) == 0 then return none
  return some (← randQ lo hi 8)

open RlSizing in
def rlSizing : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:240] do
    let lo ← optQ8 0 2 10
    let hi ← optQ8 0 2 10
    let raw ← randQ (-1) 3 8
    let (m, ok) := clampMult lo hi raw
    cases := cases ++ [Json.mkObj [("kind", "clamp"), ("input", Json.mkObj [("min", oqj lo), ("max", oqj hi), ("raw", qj raw)]),
      ("expected", Json.mkObj [("multiplier", qj m), ("scaled", toJson ok)])]]
  for _ in [0:240] do
    let n ← nextNat 12
    let xs ← genList n (randQ (-2) 2 8)
    let k ← nextNat 16
    let w : Int := (k : Int) - 3
    let tol ← randQ 0 1 8
    let enabled ← randBool
    cases := cases ++ [Json.mkObj [("kind", "guard"),
      ("input", Json.mkObj [("enabled", toJson enabled), ("history", toJson (xs.map qj)), ("window_bars", toJson w), ("tolerance", qj tol)]),
      ("expected", Json.mkObj [("allows", toJson (guardAllows enabled xs w tol))])]]
  return file "rl_sizing" ["AetherFormal/RlSizing.lean"] cases

open DrawdownGuard in
def drawdownGuard : Gen Json := do
  let mut cases : List Json := [Json.mkObj [("input", Json.mkObj [("returns", Json.arr #[])]), ("expected", Json.mkObj [("drawdown", qj 0)])]]
  for _ in [0:300] do
    let n := (← nextNat 10) + 1
    let rs ← genList n (do
      let k ← nextNat 30
      if k == 0 then return (none : Option ℚ)
      if k == 1 then return some (-1 : ℚ)
      return some (← randQ (-1) 1 16))
    cases := cases ++ [Json.mkObj [("input", Json.mkObj [("returns", toJson (rs.map oqj))]),
      ("expected", Json.mkObj [("drawdown", qj (maxDrawdown rs))])]]
  return file "drawdown_guard" ["AetherFormal/DrawdownGuard.lean"] cases

open BacktestGate in
def reasonName : Reason → String
  | .thresholdInvalid => "threshold_invalid"
  | .candidateMissing => "candidate_missing"
  | .belowThreshold => "below_threshold"
  | .passed => "passed"

open BacktestGate in
def backtestGate : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:300] do
    let c ← optQ8 (-1) 2 6
    let a ← optQ8 (-1) 2 6
    let t ← optQ8 (-1) 1 8
    let (ok, why) := verdict c a t
    cases := cases ++ [Json.mkObj [("input", Json.mkObj [("candidate", oqj c), ("active", oqj a), ("threshold", oqj t)]),
      ("expected", Json.mkObj [("passed", toJson ok), ("reason", toJson (reasonName why))])]]
  return file "backtest_gate" ["AetherFormal/BacktestGate.lean"] cases

open AutoRollback in
def rollbackReasonName : AutoRollback.Reason → String
  | .disabled => "disabled"
  | .noTrigger => "no_trigger"
  | .blocked => "blocked"
  | .triggered => "triggered"

open AutoRollback in
def autoRollback : Gen Json := do
  let flagKinds : List String := ["true", "false", "string_true", "one", "missing"]
  let mut cases : List Json := []
  for _ in [0:400] do
    let enabledKind ← pick flagKinds
    let triggerKinds ← genList 3 (pick flagKinds)
    let promotion : Option Nat ← do if (← nextNat 6) == 0 then pure none else some <$> nextNat 80
    let lastRollback : Option Nat ← do if (← nextNat 2) == 0 then pure none else some <$> nextNat 240
    let requireGate ← randBool
    let size ← nextNat 4
    let gateKinds ← genList size (pick ["true", "false", "string_true"])
    let x : Input := {
      enabled := enabledKind == "true", fired := triggerKinds.any (· == "true"),
      runwayOk := (match promotion with | some p => decide (40 ≤ p) | none => false),
      cooldownOk := (match lastRollback with | some b => decide (120 ≤ b) | none => true),
      requireGate := requireGate,
      candidates := (List.range size).zip (gateKinds.map (· == "true")) }
    let (chosen, why) := choose x
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("enabled", toJson enabledKind), ("triggers", toJson triggerKinds),
        ("bars_since_promotion", match promotion with | some p => toJson p | none => Json.null),
        ("bars_since_last_rollback", match lastRollback with | some b => toJson b | none => Json.null),
        ("require_gate", toJson requireGate), ("gates", toJson gateKinds)]),
      ("expected", Json.mkObj [("target", match chosen with | some i => toJson i | none => Json.null), ("reason", toJson (rollbackReasonName why))])]]
  return file "auto_rollback" ["AetherFormal/AutoRollback.lean"] cases

open PremiaCaps in
def premiaCaps : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:250] do
    let n := (← nextNat 6) + 1
    let defaultCap ← randQ 0 1 8
    let cap0 ← randQ 0 1 8
    let cap1 ← randQ 0 1 8
    let classCapOf ← genList 3 (do if (← randBool) then some <$> randQ 0 1 8 else pure (none : Option ℚ))
    let grossCap ← randQ 0 2 8
    let mut es : List (E ℚ) := []
    for _ in [0:n] do
      let w ← randQ (-1) 1 16
      let cls ← nextNat 3
      let cap := if cls == 0 then cap0 else if cls == 1 then cap1 else defaultCap
      es := es ++ [⟨w, w, cls, cap⟩]
    let classCaps : List (Nat × ℚ) := (List.range 3).filterMap (fun c => (classCapOf.getD c none).map (fun cap => (c, cap)))
    let out := capAll classCaps grossCap es
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("weights", toJson (es.map (fun e => qj e.w))), ("classes", toJson (es.map (·.cls))),
        ("default_name_cap", qj defaultCap), ("name_cap_by_class", toJson [qj cap0, qj cap1]),
        ("class_caps", toJson (classCaps.map (fun p => Json.mkObj [("class", toJson p.1), ("cap", qj p.2)]))), ("gross_cap", qj grossCap)]),
      ("expected", Json.mkObj [("weights", toJson (out.map (fun e => qj e.w)))])]]
  return file "premia_caps" ["AetherFormal/PremiaCaps.lean"] cases

open Rebalance in
def rebalance : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:400] do
    let k ← nextNat 101
    let held : ℚ := (((k : Int) - 50 : Int) : ℚ)
    let unit ← pick [(1 : ℚ) / 4, 1 / 2, 1, 2, 4, 8, 16, 64]
    let nav ← pick [(1024 : ℚ), 2048, 4096, 65536]
    let wanted ← do if (← nextNat 6) == 0 then pure (0 : ℚ) else randQ (-1) 1 16
    let lot ← pick [(1 : ℚ), 1 / 4, 1 / 2, 2, 0]
    let minW ← pick [(0 : ℚ), 1 / 512, 1 / 64]
    let minUsd ← pick [(0 : ℚ), 4, 16, 128]
    let out := order held unit nav wanted lot minW minUsd
    let reduces : Bool := match out with
      | some d => decide (held ≠ 0) && (decide (d < 0) == decide (0 < held)) && decide (|d| ≤ |held|)
      | none => false
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("held", qj held), ("unit", qj unit), ("nav", qj nav), ("wanted", qj wanted), ("lot", qj lot),
        ("min_weight_change", qj minW), ("min_trade_usd", qj minUsd)]),
      ("expected", Json.mkObj [("delta", oqj out), ("reduces", toJson reduces)])]]
  return file "rebalance" ["AetherFormal/Rebalance.lean"] cases

open CashSweep in
def cashSweep : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:250] do
    let l ← randQ (-1) 1 16
    let s ← randQ (-1) 1 16
    let m ← randQ 0 1 16
    let rl ← randQ 0 1 16
    let rs ← randQ 0 1 16
    let rm ← randQ 0 1 16
    let lev ← pick [(1 : ℚ), 2, 4]
    let mb ← pick [(0 : ℚ), 1 / 8, 1 / 4]
    let cb ← pick [(0 : ℚ), 1 / 16, 1 / 8]
    let mw ← randQ 0 1 8
    cases := cases ++ [Json.mkObj [("kind", "target"),
      ("input", Json.mkObj [("long", qj l), ("short", qj s), ("margin", qj m), ("reserve_long", qj rl), ("reserve_short", qj rs),
        ("reserve_margin", qj rm), ("leverage", qj lev), ("margin_buffer", qj mb), ("cash_buffer", qj cb), ("max_weight", qj mw)]),
      ("expected", Json.mkObj [("weight", qj (target l s m rl rs rm lev mb cb mw))])]]
  for _ in [0:200] do
    let value ← randQ 0 4 8
    let t0 ← randQ (-1) 4 8
    let s0 ← randQ 0 2 8
    let total ← randQ (-1) 8 8
    let sweep ← randQ 0 8 8
    cases := cases ++ [Json.mkObj [("kind", "advance"),
      ("input", Json.mkObj [("value", qj value), ("state_total", qj t0), ("state_sweep", qj s0), ("total", qj total), ("sweep", qj sweep)]),
      ("expected", Json.mkObj [("value", qj (advance value t0 s0 total sweep))])]]
  for _ in [0:120] do
    let delta ← randQ (-8) 8 8
    let price ← randQ 0 16 8
    let minUsd ← optQ8 (-2) 40 8
    cases := cases ++ [Json.mkObj [("kind", "resize"),
      ("input", Json.mkObj [("delta", qj delta), ("price", qj price), ("min_trade_usd", oqj minUsd)]),
      ("expected", Json.mkObj [("below", toJson (resizeBelow delta price minUsd))])]]
  return file "cash_sweep" ["AetherFormal/CashSweep.lean"] cases

open DynamicTargets in
def dynamicTargetsCases : Gen Json := do
  let tol : ℚ := 1 / 1000000000
  let mut cases : List Json := []
  for _ in [0:300] do
    let n := (← nextNat 5) + 1
    let floor ← pick [(0 : ℚ), 1 / 8, 1 / 2]
    let maxGen ← pick [1, 2, 4]
    let mut scores : List (String × ℚ) := []
    let mut caps : List (String × ℚ) := []
    for i in [0:n] do
      let name := s!"g{i}"
      scores := scores ++ [(name, ← randQ (-1) 2 8)]
      if (← randBool) then caps := caps ++ [(name, ← randQ 0 1 8)]
    let capOf := fun (name : String) => max 0 (min 1 ((caps.lookup name).getD 1))
    let usable := (scores.map (fun p => (p.1, p.2 - floor))).filter (fun p => decide (0 < p.2))
    let ranked := usable.mergeSort (fun a b => decide (b.2 < a.2) || (decide (a.2 = b.2) && decide (a.1 < b.1 ∨ a.1 = b.1)))
    let opens : List (O ℚ) := (ranked.take maxGen).map (fun p => ⟨p.1, p.2, capOf p.1⟩)
    let filled := fill tol opens.length opens 1
    let targets := scores.map (fun p => (p.1, (filled.lookup p.1).getD 0))
    cases := cases ++ [Json.mkObj [("kind", "targets"),
      ("input", Json.mkObj [("scores", Json.mkObj (scores.map (fun p => (p.1, qj p.2)))), ("caps", Json.mkObj (caps.map (fun p => (p.1, qj p.2)))),
        ("score_floor", qj floor), ("max_generations", toJson maxGen)]),
      ("expected", Json.mkObj [("targets", Json.mkObj (targets.map (fun p => (p.1, qj p.2))))])]]
  for _ in [0:150] do
    let n := (← nextNat 5) + 1
    let shares ← genList n (optQ8 (-1) 1 6)
    cases := cases ++ [Json.mkObj [("kind", "repair"), ("input", Json.mkObj [("shares", toJson (shares.map oqj))]),
      ("expected", Json.mkObj [("shares", toJson ((repair tol shares).map qj))])]]
  return file "dynamic_targets" ["AetherFormal/DynamicTargets.lean"] cases

open ForexCap in
def forexCap : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:250] do
    let t ← optQ8 (-3) 3 10
    let b ← optQ8 (-1) 1 10
    cases := cases ++ [Json.mkObj [("input", Json.mkObj [("target", oqj t), ("book", oqj b)]), ("expected", Json.mkObj [("weight", qj (capForex t b))])]]
  return file "forex_cap" ["AetherFormal/ForexCap.lean"] cases

open VolTarget in
def volTargetCases : Gen Json := do
  let mut cases : List Json := []
  for _ in [0:250] do
    let n := (← nextNat 5) + 1
    let ws ← genList n (randQ (-1) 1 8)
    let risk ← optQ8 1 4 8
    let target ← pick [(0 : ℚ), 1 / 16, 1 / 8, 1 / 2]
    let maxLev ← randQ 0 2 8
    let squares := (ws.map (fun w => w * w)).sum
    let risk := if squares = 0 then some (0 : ℚ) else risk
    let out := volTarget ws risk target maxLev
    cases := cases ++ [Json.mkObj [
      ("input", Json.mkObj [("weights", toJson (ws.map qj)), ("risk", oqj risk), ("target", qj target), ("max_leverage", qj maxLev)]),
      ("expected", Json.mkObj [("weights", toJson (out.map qj))])]]
  return file "vol_target" ["AetherFormal/VolTarget.lean"] cases

def all : List (String × Gen Json) :=
  [("order_gate", orderGate), ("hash_chain", hashChain), ("book_neutrality", bookNeutrality),
   ("book_construction", bookConstruction), ("risk_controls", riskControls), ("kill_switch", killSwitch),
   ("position_sizing", positionSizing), ("cost_model", costModel), ("reconciliation", reconciliation),
   ("sleeve_guard", sleeveGuard), ("json_safety", jsonSafety), ("generation_blend", generationBlend), ("generation_glide", generationGlide),
   ("admission", admission), ("session_resolve", sessionResolve), ("holdout_once", holdoutOnce),
   ("account_overrides", accountOverrides), ("authorize", authorizeCases),
   -- V6.6.7: appended, so the earlier targets keep their seeds
   ("rl_sizing", rlSizing), ("drawdown_guard", drawdownGuard), ("backtest_gate", backtestGate), ("auto_rollback", autoRollback),
   ("premia_caps", premiaCaps), ("rebalance", rebalance), ("cash_sweep", cashSweep), ("dynamic_targets", dynamicTargetsCases),
   ("forex_cap", forexCap), ("vol_target", volTargetCases)]

end AetherFormal.GenCases

open AetherFormal.GenCases in
def main (args : List String) : IO UInt32 := do
  let outDir : System.FilePath := args.headD "cases"
  IO.FS.createDirAll outDir
  let mut seed := 20261102
  for (name, gen) in all do
    let (json, _) := gen.run seed
    IO.FS.writeFile (outDir / (s!"{name}.json")) (json.pretty 120 ++ "\n")
    IO.println (s!"wrote {name}.json")
    seed := seed + 1
  return 0
