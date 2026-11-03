import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Algebra.BigOperators.Group.Finset.Basic
import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Tactic.FieldSimp
import Mathlib.Algebra.Order.BigOperators.Group.Finset
import Mathlib.Data.List.Sort
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/book_construction.py`

`tranche_book_params`, `partial_adjust_weights`, `combine_tranche_weights`, `apply_class_weight_caps` and the
selection core of `_select_book_group` (hysteresis margin 0, no spread or rolling-IC veto). A book over a fixed universe
of `n` symbols is `Fin n → α`; a symbol missing from a Python dict has weight 0.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.BookConstruction

open Finset

/-! ### Tranches -/

/-- `-(-n // k)` for `n ≥ 0`: the ceiling of `n / k`. -/
def ceilDiv (n k : Nat) : Nat := (n + k - 1) / k

/-- The K tranches together hold at least `n` names, and fewer than `n + K`. -/
theorem ceilDiv_bounds (n k : Nat) (hk : 0 < k) : n ≤ k * ceilDiv n k ∧ k * ceilDiv n k < n + k := by
  unfold ceilDiv
  constructor
  · have := Nat.div_add_mod (n + k - 1) k
    have hm := Nat.mod_lt (n + k - 1) hk
    omega
  · have := Nat.div_mul_le_self (n + k - 1) k
    rw [Nat.mul_comm]
    omega

theorem ceilDiv_one (n : Nat) : ceilDiv n 1 = n := by simp [ceilDiv]

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

/-- The tranches' gross caps add back up to the book's cap. -/
theorem tranche_gross_sum (cap : α) (k : Nat) (hk : 0 < k) : (k : α) * (cap / k) = cap := by
  have : (k : α) ≠ 0 := by exact_mod_cast hk.ne'
  field_simp

/-! ### Books over a fixed universe -/

def gross {n : Nat} (w : Fin n → α) : α := ∑ i, |w i|

/-- `partial_adjust_weights`: move `f` of the way to the target; |weight| < `minW` is dropped. -/
def partialAdjust {n : Nat} (f minW : α) (cur tgt : Fin n → α) : Fin n → α :=
  if 1 ≤ f then tgt
  else fun i =>
    let x := cur i + f * (tgt i - cur i)
    if minW ≤ |x| then x else 0

/-- The blend of two books stays inside the convex combination of their gross exposures. -/
theorem partialAdjust_gross {n : Nat} (f minW : α) (hf0 : 0 ≤ f) (cur tgt : Fin n → α) :
    gross (partialAdjust f minW cur tgt) ≤ (1 - min f 1) * gross cur + min f 1 * gross tgt := by
  unfold partialAdjust gross
  split_ifs with h1
  · rw [min_eq_right h1]; simp
  · push_neg at h1
    rw [min_eq_left h1.le, mul_sum, mul_sum, ← sum_add_distrib]
    apply sum_le_sum
    intro i _
    dsimp only
    have key : |cur i + f * (tgt i - cur i)| ≤ (1 - f) * |cur i| + f * |tgt i| := by
      have e : cur i + f * (tgt i - cur i) = (1 - f) * cur i + f * tgt i := by ring
      rw [e]
      calc |(1 - f) * cur i + f * tgt i| ≤ |(1 - f) * cur i| + |f * tgt i| := abs_add_le _ _
        _ = (1 - f) * |cur i| + f * |tgt i| := by
          rw [abs_mul, abs_mul, abs_of_nonneg (by linarith), abs_of_nonneg hf0]
    split_ifs
    · exact key
    · simp only [abs_zero]
      exact le_trans (abs_nonneg _) key

/-- So two books inside the same gross cap blend into a book inside that cap. -/
theorem partialAdjust_within_cap {n : Nat} (f minW cap : α) (hf0 : 0 ≤ f) (cur tgt : Fin n → α)
    (hc : gross cur ≤ cap) (ht : gross tgt ≤ cap) : gross (partialAdjust f minW cur tgt) ≤ cap := by
  have h := partialAdjust_gross f minW hf0 cur tgt
  have hm0 : 0 ≤ min f 1 := le_min hf0 zero_le_one
  have hm1 : min f 1 ≤ 1 := min_le_right _ _
  nlinarith

/-- `combine_tranche_weights`: the per-name sum of the tranches. -/
def combine {n : Nat} (ts : List (Fin n → α)) : Fin n → α := fun i => (ts.map fun t => t i).sum

/-- Netting tranches never adds gross: the live book's gross is at most the sum of the tranches'. -/
theorem combine_gross {n : Nat} (ts : List (Fin n → α)) : gross (combine ts) ≤ (ts.map gross).sum := by
  induction ts with
  | nil => simp [combine, gross]
  | cons t ts ih =>
    simp only [List.map_cons, List.sum_cons]
    calc gross (combine (t :: ts)) = ∑ i, |t i + combine ts i| := by simp [gross, combine]
      _ ≤ ∑ i, (|t i| + |combine ts i|) := sum_le_sum fun i _ => abs_add_le _ _
      _ = gross t + gross (combine ts) := by rw [sum_add_distrib]; rfl
      _ ≤ gross t + (ts.map gross).sum := by linarith

/-! ### Class weight caps (one class; the Python loop visits disjoint classes) -/

/-- Step 1 of `apply_class_weight_caps`: clip each capped name (`inClass` = in the class and not exempt). -/
def clampClass {n : Nat} (inClass : Fin n → Bool) (perName : Option α) (w : Fin n → α) : Fin n → α := fun i =>
  if inClass i then (match perName with
    | some c => max (-c) (min c (w i))
    | none => w i) else w i

def classGrossOf {n : Nat} (inClass : Fin n → Bool) (w : Fin n → α) : α := ∑ i, if inClass i then |w i| else 0

/-- Step 2: scale the capped names down when their gross is over the class cap. -/
def scaleClass {n : Nat} (inClass : Fin n → Bool) (classGross : Option α) (w : Fin n → α) : Fin n → α :=
  match classGross with
  | some cg =>
    if 0 < cg ∧ cg < classGrossOf inClass w then fun i => if inClass i then w i * (cg / classGrossOf inClass w) else w i
    else w
  | none => w

def classCap {n : Nat} (inClass : Fin n → Bool) (perName classGross : Option α) (w : Fin n → α) : Fin n → α :=
  scaleClass inClass classGross (clampClass inClass perName w)

theorem clampClass_outside {n : Nat} (inClass : Fin n → Bool) (perName : Option α) (w : Fin n → α) (i : Fin n)
    (hi : inClass i = false) : clampClass inClass perName w i = w i := by
  simp [clampClass, hi]

theorem scaleClass_outside {n : Nat} (inClass : Fin n → Bool) (cg : Option α) (w : Fin n → α) (i : Fin n)
    (hi : inClass i = false) : scaleClass inClass cg w i = w i := by
  cases cg with
  | none => rfl
  | some cg =>
    dsimp only [scaleClass]
    by_cases h : 0 < cg ∧ cg < classGrossOf inClass w
    · rw [if_pos h]; simp [hi]
    · rw [if_neg h]

/-- Names outside the class (and exempt names) are untouched. -/
theorem classCap_outside {n : Nat} (inClass : Fin n → Bool) (perName classGross : Option α) (w : Fin n → α)
    (i : Fin n) (hi : inClass i = false) : classCap inClass perName classGross w i = w i := by
  unfold classCap
  rw [scaleClass_outside inClass classGross _ i hi, clampClass_outside inClass perName w i hi]

theorem abs_clamp_le (x : α) {c : α} (hc : 0 ≤ c) : |max (-c) (min c x)| ≤ c := by
  rw [abs_le]
  exact ⟨le_max_left _ _, max_le (by linarith) (min_le_left _ _)⟩

theorem scaleClass_abs_le {n : Nat} (inClass : Fin n → Bool) (cg : Option α) (w : Fin n → α) (i : Fin n) :
    |scaleClass inClass cg w i| ≤ |w i| := by
  cases cg with
  | none => exact le_refl _
  | some cg =>
    dsimp only [scaleClass]
    by_cases h : 0 < cg ∧ cg < classGrossOf inClass w
    · rw [if_pos h]
      have hg : 0 < classGrossOf inClass w := lt_trans h.1 h.2
      have hk0 : 0 ≤ cg / classGrossOf inClass w := div_nonneg h.1.le hg.le
      have hk1 : cg / classGrossOf inClass w ≤ 1 := (div_le_one hg).mpr h.2.le
      by_cases hi : inClass i = true
      · simp only [hi, if_true]
        rw [abs_mul, abs_of_nonneg hk0]
        nlinarith [abs_nonneg (w i)]
      · simp [hi]
    · rw [if_neg h]

/-- Every capped name ends within its per-name cap. -/
theorem classCap_per_name {n : Nat} (inClass : Fin n → Bool) (c : α) (hc : 0 < c) (classGross : Option α)
    (w : Fin n → α) (i : Fin n) (hi : inClass i = true) :
    |classCap inClass (some c) classGross w i| ≤ c := by
  unfold classCap
  have hclamp : clampClass inClass (some c) w i = max (-c) (min c (w i)) := by simp [clampClass, hi]
  calc |scaleClass inClass classGross (clampClass inClass (some c) w) i| ≤ |clampClass inClass (some c) w i| :=
        scaleClass_abs_le _ _ _ _
    _ = |max (-c) (min c (w i))| := by rw [hclamp]
    _ ≤ c := abs_clamp_le _ hc.le

theorem classGrossOf_scale {n : Nat} (inClass : Fin n → Bool) (v : Fin n → α) (k : α) (hk : 0 ≤ k) :
    classGrossOf inClass (fun i => if inClass i then v i * k else v i) = k * classGrossOf inClass v := by
  unfold classGrossOf
  rw [mul_sum]
  apply sum_congr rfl
  intro i _
  by_cases hi : inClass i = true
  · simp only [hi, if_true]
    rw [abs_mul, abs_of_nonneg hk, mul_comm]
  · simp [hi]

/-- The class's gross ends within its class gross cap. -/
theorem classCap_gross {n : Nat} (inClass : Fin n → Bool) (perName : Option α) (cg : α) (hcg : 0 < cg)
    (w : Fin n → α) : classGrossOf inClass (classCap inClass perName (some cg) w) ≤ cg := by
  unfold classCap
  dsimp only [scaleClass]
  set v := clampClass inClass perName w
  by_cases h : 0 < cg ∧ cg < classGrossOf inClass v
  · rw [if_pos h]
    have hg : 0 < classGrossOf inClass v := lt_trans h.1 h.2
    have hk0 : 0 ≤ cg / classGrossOf inClass v := div_nonneg h.1.le hg.le
    calc classGrossOf inClass (fun i => if inClass i then v i * (cg / classGrossOf inClass v) else v i)
        = cg / classGrossOf inClass v * classGrossOf inClass v := classGrossOf_scale inClass v _ hk0
      _ = cg := div_mul_cancel₀ _ hg.ne'
      _ ≤ cg := le_refl _
  · rw [if_neg h]
    push_neg at h
    exact h hcg

/-! ### Book selection core -/

/-- Python's `sorted(..., reverse=True)`: stable, highest rank first. -/
def rankedDesc (pool : List (Nat × α)) : List (Nat × α) := pool.mergeSort fun a b => decide (b.2 ≤ a.2)
def longsOf (pool : List (Nat × α)) (top : Nat) : List (Nat × α) := (rankedDesc pool).take top
def restOf (pool : List (Nat × α)) (top : Nat) : List (Nat × α) := (rankedDesc pool).drop top
def shortsOf (pool : List (Nat × α)) (top bottom : Nat) : List (Nat × α) :=
  ((restOf pool top).mergeSort fun a b => decide (a.2 ≤ b.2)).take bottom

/-- `_select_book_group` with no hysteresis and no veto: longs = the `top` highest ranks, shorts = the `bottom` lowest of
the rest. Both sorts are stable, like Python's `sorted`, so ties resolve in input order on both sides. -/
def selectBook (pool : List (Nat × α)) (top bottom : Nat) : List Nat × List Nat :=
  if pool.length < 2 ∨ top = 0 then ([], [])
  else if longsOf pool top = [] then ([], [])
  else if 0 < bottom ∧ shortsOf pool top bottom = [] then ([], [])
  else ((longsOf pool top).map Prod.fst, (shortsOf pool top bottom).map Prod.fst)

theorem selectBook_lengths (pool : List (Nat × α)) (top bottom : Nat) :
    (selectBook pool top bottom).1.length ≤ top ∧ (selectBook pool top bottom).2.length ≤ bottom := by
  unfold selectBook
  split_ifs <;> simp [longsOf, shortsOf, List.length_take]

theorem selectBook_long_only (pool : List (Nat × α)) (top : Nat) : (selectBook pool top 0).2 = [] := by
  unfold selectBook
  split_ifs <;> simp [shortsOf]

theorem selectBook_members (pool : List (Nat × α)) (top bottom : Nat) (s : Nat) :
    (s ∈ (selectBook pool top bottom).1 ∨ s ∈ (selectBook pool top bottom).2) → s ∈ pool.map Prod.fst := by
  unfold selectBook
  split_ifs
  · simp
  · simp
  · simp
  · rintro (h | h)
    · obtain ⟨p, hp, rfl⟩ := List.mem_map.mp h
      exact List.mem_map.mpr ⟨p, (List.mergeSort_perm _ _).subset (List.mem_of_mem_take hp), rfl⟩
    · obtain ⟨p, hp, rfl⟩ := List.mem_map.mp h
      have h1 := List.mem_of_mem_take hp
      have h2 := (List.mergeSort_perm _ _).subset h1
      have h3 := List.mem_of_mem_drop h2
      exact List.mem_map.mpr ⟨p, (List.mergeSort_perm _ _).subset h3, rfl⟩

/-- The two legs never share a symbol (symbols in the pool are distinct). -/
theorem selectBook_disjoint (pool : List (Nat × α)) (hnd : (pool.map Prod.fst).Nodup) (top bottom : Nat) :
    ∀ s, s ∈ (selectBook pool top bottom).1 → s ∉ (selectBook pool top bottom).2 := by
  intro s
  unfold selectBook
  split_ifs
  · simp
  · simp
  · simp
  · intro hl hs
    have hperm : (rankedDesc pool).Perm pool := List.mergeSort_perm _ _
    have hnd' : ((rankedDesc pool).map Prod.fst).Nodup := (hperm.map Prod.fst).nodup_iff.mpr hnd
    have hsplit : (rankedDesc pool).map Prod.fst = (longsOf pool top).map Prod.fst ++ (restOf pool top).map Prod.fst := by
      rw [longsOf, restOf, ← List.map_append, List.take_append_drop]
    rw [hsplit] at hnd'
    have hdisj := (List.nodup_append.mp hnd').2.2
    obtain ⟨p, hp, rfl⟩ := List.mem_map.mp hl
    obtain ⟨q, hq, hqs⟩ := List.mem_map.mp hs
    have hq' : q ∈ restOf pool top := (List.mergeSort_perm _ _).subset (List.mem_of_mem_take hq)
    exact hdisj p.1 (List.mem_map.mpr ⟨p, hp, rfl⟩) q.1 (List.mem_map.mpr ⟨q, hq', rfl⟩) hqs.symm

end AetherFormal.BookConstruction
