import Mathlib.Order.Basic
import Mathlib.Order.Lattice
import Mathlib.Tactic.Linarith

/-!
# `evaluation/forward_ledger.py`: `resolve_session`

The session a run records. A date is a natural number (days). With no override it is the newest session on or before today: a schedule delayed past midnight UTC, or a weekend dispatch,
still records the session it was for, never one that has not happened and never an older gap (Problems #332). With an override it is that date only if it is a session.
-/

namespace AetherFormal.SessionResolve

/-- The newest session on or before `now`, or none. -/
def best (now : Nat) : List Nat → Option Nat
  | [] => none
  | s :: rest =>
    match best now rest with
    | none => if s ≤ now then some s else none
    | some b => if s ≤ now then some (max s b) else some b

/-- `resolve_session(sessions, now_date, override)`. -/
def resolve (sessions : List Nat) (now : Nat) : Option Nat → Option Nat
  | none => best now sessions
  | some o => if o ∈ sessions then some o else none

theorem best_mem (now : Nat) : ∀ (l : List Nat) (r : Nat), best now l = some r → r ∈ l := by
  intro l
  induction l with
  | nil => intro r h; simp [best] at h
  | cons s rest ih =>
    intro r h
    simp only [best] at h
    cases hb : best now rest with
    | none =>
      rw [hb] at h
      by_cases hs : s ≤ now
      · simp [hs] at h; simp [h]
      · simp [hs] at h
    | some b =>
      rw [hb] at h
      have hbm : b ∈ rest := ih b hb
      by_cases hs : s ≤ now
      · simp only [hs, if_true, Option.some.injEq] at h
        rcases le_total s b with hsb | hbs
        · rw [← h, max_eq_right hsb]; exact List.mem_cons_of_mem _ hbm
        · rw [← h, max_eq_left hbs]; exact List.mem_cons_self
      · simp only [hs, if_false, Option.some.injEq] at h
        rw [← h]; exact List.mem_cons_of_mem _ hbm

theorem best_le (now : Nat) : ∀ (l : List Nat) (r : Nat), best now l = some r → r ≤ now := by
  intro l
  induction l with
  | nil => intro r h; simp [best] at h
  | cons s rest ih =>
    intro r h
    simp only [best] at h
    cases hb : best now rest with
    | none =>
      rw [hb] at h
      by_cases hs : s ≤ now
      · simp [hs] at h; omega
      · simp [hs] at h
    | some b =>
      rw [hb] at h
      have hbn : b ≤ now := ih b hb
      by_cases hs : s ≤ now
      · simp only [hs, if_true, Option.some.injEq] at h
        rw [← h]; exact max_le hs hbn
      · simp only [hs, if_false, Option.some.injEq] at h
        omega

/-- Every session on or before today is at or below the answer, and an answer exists. -/
theorem best_newest (now : Nat) : ∀ (l : List Nat) (s : Nat), s ∈ l → s ≤ now → ∃ r, best now l = some r ∧ s ≤ r := by
  intro l
  induction l with
  | nil => intro s hs; simp at hs
  | cons t rest ih =>
    intro s hs hsn
    simp only [best]
    rcases List.mem_cons.mp hs with rfl | hmem
    · cases hb : best now rest with
      | none => exact ⟨s, by simp [hsn], le_refl s⟩
      | some b => exact ⟨max s b, by simp [hsn], le_max_left _ _⟩
    · obtain ⟨r, hr, hsr⟩ := ih s hmem hsn
      rw [hr]
      by_cases ht : t ≤ now
      · exact ⟨max t r, by simp [ht], le_trans hsr (le_max_right _ _)⟩
      · exact ⟨r, by simp [ht], hsr⟩

theorem best_none_iff (now : Nat) (l : List Nat) : best now l = none ↔ ∀ s ∈ l, now < s := by
  constructor
  · intro h s hs
    by_contra hle
    obtain ⟨r, hr, _⟩ := best_newest now l s hs (by omega)
    rw [h] at hr
    simp at hr
  · intro h
    cases hb : best now l with
    | none => rfl
    | some r =>
      have hm := best_mem now l r hb
      have hn := best_le now l r hb
      have := h r hm
      omega

/-- The same inputs resolve to the same session. -/
theorem resolve_stable (sessions : List Nat) (now : Nat) (o : Option Nat) : resolve sessions now o = resolve sessions now o := rfl

/-- Without an override the answer is a session, on or before today, and the newest such. -/
theorem resolve_default (sessions : List Nat) (now r : Nat) (h : resolve sessions now none = some r) :
    r ∈ sessions ∧ r ≤ now ∧ ∀ s ∈ sessions, s ≤ now → s ≤ r := by
  refine ⟨best_mem now sessions r h, best_le now sessions r h, ?_⟩
  intro s hs hsn
  obtain ⟨r', hr', hsr'⟩ := best_newest now sessions s hs hsn
  have : r' = r := by
    simp only [resolve] at h
    rw [h] at hr'
    exact (Option.some.inj hr').symm
  rw [← this]; exact hsr'

/-- An override is honoured only if it is a session. -/
theorem resolve_override (sessions : List Nat) (now o : Nat) :
    resolve sessions now (some o) = if o ∈ sessions then some o else none := rfl

end AetherFormal.SessionResolve
