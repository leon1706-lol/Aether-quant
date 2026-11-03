import Mathlib.Data.List.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `audit/hash_chain.py`

`verify_chain` over an abstract entry hash `H prev event created payload` (sha256 of the joined fields in Python).
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.HashChain

structure Row where
  prev : String
  hash : String
  event : String
  created : String
  payload : String
  deriving DecidableEq, Repr

variable (H : String → String → String → String → String)

/-- The loop of `verify_chain`, started at row index `i` with the expected predecessor hash `e`. -/
def verifyFrom : String → Nat → List Row → Bool × Option Nat
  | _, _, [] => (true, none)
  | e, i, r :: rs =>
    if r.prev ≠ e then (false, some i)
    else if H r.prev r.event r.created r.payload ≠ r.hash then (false, some i)
    else verifyFrom r.hash (i + 1) rs

def verify (genesis : String) (rows : List Row) : Bool × Option Nat := verifyFrom H genesis 0 rows

/-- A well-linked chain from predecessor hash `e`. -/
def Valid : String → List Row → Prop
  | _, [] => True
  | e, r :: rs => r.prev = e ∧ H r.prev r.event r.created r.payload = r.hash ∧ Valid r.hash rs

/-- The hash the next appended row must link to. -/
def tailHash : String → List Row → String
  | e, [] => e
  | _, r :: rs => tailHash r.hash rs

theorem verifyFrom_ok_iff (e : String) (i : Nat) (rs : List Row) :
    (verifyFrom H e i rs).1 = true ↔ Valid H e rs := by
  induction rs generalizing e i with
  | nil => simp [verifyFrom, Valid]
  | cons r rs ih =>
    by_cases h1 : r.prev = e
    · subst h1
      by_cases h2 : H r.prev r.event r.created r.payload = r.hash
      · simp [verifyFrom, Valid, h2, ih]
      · simp [verifyFrom, Valid, h2]
    · simp [verifyFrom, Valid, h1]

/-- `all_valid` is exactly "every row links to its predecessor and hashes to its own content". -/
theorem verify_ok_iff (g : String) (rs : List Row) : (verify H g rs).1 = true ↔ Valid H g rs :=
  verifyFrom_ok_iff H g 0 rs

theorem verifyFrom_shape (e : String) (i : Nat) (rs : List Row) :
    verifyFrom H e i rs = (true, none) ∨ ∃ k, verifyFrom H e i rs = (false, some k) := by
  induction rs generalizing e i with
  | nil => simp [verifyFrom]
  | cons r rs ih =>
    simp only [verifyFrom]
    split_ifs
    · exact Or.inr ⟨i, rfl⟩
    · exact Or.inr ⟨i, rfl⟩
    · exact ih _ _

/-- The reported index is the FIRST broken row: the rows before it form a valid chain and adding that row breaks it. -/
theorem verifyFrom_index_minimal (e : String) (i : Nat) (rs : List Row) (k : Nat)
    (h : verifyFrom H e i rs = (false, some k)) :
    i ≤ k ∧ k < i + rs.length ∧ Valid H e (rs.take (k - i)) ∧ ¬ Valid H e (rs.take (k - i + 1)) := by
  induction rs generalizing e i with
  | nil => simp [verifyFrom] at h
  | cons r rs ih =>
    by_cases h1 : r.prev = e
    · subst h1
      by_cases h2 : H r.prev r.event r.created r.payload = r.hash
      · have h' : verifyFrom H r.hash (i + 1) rs = (false, some k) := by simpa [verifyFrom, h2] using h
        obtain ⟨hk1, hk2, hv, hnv⟩ := ih r.hash (i + 1) h'
        have hsub : k - i = (k - (i + 1)) + 1 := by omega
        refine ⟨by omega, by simp; omega, ?_, ?_⟩
        · rw [hsub, List.take_succ_cons]
          exact ⟨rfl, h2, hv⟩
        · rw [hsub, List.take_succ_cons]
          rintro ⟨_, _, hv'⟩
          exact hnv hv'
      · have hk : i = k := by simpa [verifyFrom, h2] using h
        subst hk
        refine ⟨le_refl _, by simp, by simp [Valid], ?_⟩
        simp [Valid, h2]
    · have hk : i = k := by simpa [verifyFrom, h1] using h
      subst hk
      refine ⟨le_refl _, by simp, by simp [Valid], ?_⟩
      simp [Valid, h1]

theorem valid_append_one (e : String) (rs : List Row) (r : Row)
    (hv : Valid H e rs) (hp : r.prev = tailHash e rs) (hh : H r.prev r.event r.created r.payload = r.hash) :
    Valid H e (rs ++ [r]) := by
  induction rs generalizing e with
  | nil => simp [Valid, tailHash] at *; exact ⟨hp, hh⟩
  | cons x xs ih =>
    obtain ⟨h1, h2, h3⟩ := hv
    exact ⟨h1, h2, ih x.hash h3 (by simpa [tailHash] using hp)⟩

/-- Every row of a valid chain hashes to its own content. -/
theorem valid_mem (e : String) (rs : List Row) (hv : Valid H e rs) (r : Row) (hr : r ∈ rs) :
    H r.prev r.event r.created r.payload = r.hash := by
  induction rs generalizing e with
  | nil => simp at hr
  | cons x xs ih =>
    obtain ⟨_, h2, h3⟩ := hv
    rcases List.mem_cons.mp hr with h | h
    · subst h; exact h2
    · exact ih x.hash h3 h

/-- Altering one row's payload is detected when `H` is injective in the payload. -/
theorem payload_tamper_detected (e : String) (rs : List Row) (hv : Valid H e rs) (j : Nat) (hj : j < rs.length)
    (p : String) (hp : p ≠ rs[j].payload)
    (hinj : ∀ a b c x y, H a b c x = H a b c y → x = y) :
    ¬ Valid H e (rs.set j { rs[j] with payload := p }) := by
  intro hv'
  have hmem : { rs[j] with payload := p } ∈ rs.set j { rs[j] with payload := p } :=
    List.mem_set (by simpa using hj) _
  have h1 := valid_mem H e _ hv' _ hmem
  have h2 := valid_mem H e rs hv rs[j] (List.getElem_mem hj)
  exact hp (hinj _ _ _ _ _ (h1.trans h2.symm))

theorem valid_prev_of_append (e : String) (a : List Row) (x : Row) (rest : List Row)
    (hv : Valid H e (a ++ x :: rest)) : x.prev = tailHash e a := by
  induction a generalizing e with
  | nil => exact hv.1
  | cons y ys ih => exact ih y.hash hv.2.2

/-- Deleting a row that has a successor is detected, provided the deleted row's hash differs from its predecessor's. -/
theorem delete_detected (e : String) (a : List Row) (r b : Row) (c : List Row)
    (hv : Valid H e (a ++ r :: b :: c)) (hne : r.hash ≠ tailHash e a) :
    ¬ Valid H e (a ++ b :: c) := by
  intro hv'
  have hb' := valid_prev_of_append H e a b c hv'
  have hv2 : Valid H e ((a ++ [r]) ++ b :: c) := by simpa using hv
  have hb := valid_prev_of_append H e (a ++ [r]) b c hv2
  have htail : tailHash e (a ++ [r]) = r.hash := by
    clear hv hv' hv2 hb hb' hne
    induction a generalizing e with
    | nil => rfl
    | cons y ys ih => exact ih y.hash
  rw [htail] at hb
  exact hne (hb.symm.trans hb')

/-- FINDING (V6.4.3): truncating the newest rows is NOT detected. Any prefix of a valid chain is valid, so tamper
evidence for the tail needs the latest hash anchored outside the table. -/
theorem truncation_undetected (e : String) (rs : List Row) (hv : Valid H e rs) (n : Nat) :
    Valid H e (rs.take n) := by
  induction rs generalizing e n with
  | nil => simp [Valid]
  | cons r rs ih =>
    cases n with
    | zero => simp [Valid]
    | succ n => exact ⟨hv.1, hv.2.1, ih r.hash hv.2.2 n⟩

end AetherFormal.HashChain
