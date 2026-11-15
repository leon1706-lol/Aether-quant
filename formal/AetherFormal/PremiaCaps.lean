import Mathlib.Algebra.BigOperators.Ring.List
import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Algebra.BigOperators.Group.List.Basic
import Mathlib.Algebra.Order.BigOperators.Group.List
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/premia_signals.py`

The cap stage of `scale_and_cap` (`_apply_weight_caps`): each name clipped to its cap, then each class's gross scaled
down to its cap, then the whole book's gross to `gross_cap`. Every entry keeps its weight before the caps (`w0`), so
the invariants are per entry. They hold for caps that are not negative, which `WeightSettings` now enforces (V6.6.7,
#372): a negative name cap made `np.clip(x, -cap, cap)` return the cap for every name.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.PremiaCaps

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

structure E (α : Type*) where
  w0 : α
  w : α
  cls : Nat
  cap : α

/-- `np.clip(w, -cap, cap)`. -/
def clipW (e : E α) : E α := { e with w := min (max e.w (-e.cap)) e.cap }

def scaleW (k : α) (e : E α) : E α := { e with w := e.w * k }

@[simp] theorem scaleW_cls (k : α) (e : E α) : (scaleW k e).cls = e.cls := rfl

def gross (es : List (E α)) : α := (es.map (fun e => |e.w|)).sum

def classGross (c : Nat) (es : List (E α)) : α := gross (es.filter (fun e => e.cls = c))

def classFactor (c : Nat) (cap : α) (es : List (E α)) : α :=
  if cap < classGross c es then cap / classGross c es else 1

def classStep (c : Nat) (cap : α) (es : List (E α)) : List (E α) :=
  es.map (fun e => if e.cls = c then scaleW (classFactor c cap es) e else e)

def classSteps : List (Nat × α) → List (E α) → List (E α)
  | [], es => es
  | (c, cap) :: rest, es => classSteps rest (classStep c cap es)

def grossFactor (G : α) (es : List (E α)) : α := if G < gross es then G / gross es else 1

def grossStep (G : α) (es : List (E α)) : List (E α) := es.map (scaleW (grossFactor G es))

def capAll (classCaps : List (Nat × α)) (G : α) (es : List (E α)) : List (E α) :=
  grossStep G (classSteps classCaps (es.map clipW))

/-- What every entry satisfies after each step: within its cap, no larger than before, never the other sign. -/
def Good (e : E α) : Prop := |e.w| ≤ e.cap ∧ |e.w| ≤ |e.w0| ∧ 0 ≤ e.w0 * e.w

/-- What an entry satisfies before the caps. -/
def Fresh (e : E α) : Prop := e.w = e.w0 ∧ 0 ≤ e.cap

theorem gross_nonneg (es : List (E α)) : 0 ≤ gross es :=
  List.sum_nonneg (fun x hx => by
    obtain ⟨e, -, rfl⟩ := List.mem_map.mp hx
    exact abs_nonneg _)

theorem clip_cases (w cap : α) (hc : 0 ≤ cap) :
    (w < -cap ∧ min (max w (-cap)) cap = -cap) ∨ (-cap ≤ w ∧ w ≤ cap ∧ min (max w (-cap)) cap = w) ∨
      (cap < w ∧ min (max w (-cap)) cap = cap) := by
  rcases lt_or_ge w (-cap) with h1 | h1
  · left; exact ⟨h1, by rw [max_eq_right h1.le, min_eq_left (by linarith)]⟩
  · rcases le_or_gt w cap with h2 | h2
    · right; left; exact ⟨h1, h2, by rw [max_eq_left h1, min_eq_left h2]⟩
    · right; right; exact ⟨h2, by rw [max_eq_left h1, min_eq_right h2.le]⟩

theorem clip_good (e : E α) (h : Fresh e) : Good (clipW e) := by
  obtain ⟨hw, hc⟩ := h
  simp only [Good, clipW]
  rw [← hw]
  rcases clip_cases e.w e.cap hc with ⟨h1, h2⟩ | ⟨h1, h2, h3⟩ | ⟨h1, h2⟩
  · rw [h2, abs_neg, abs_of_nonneg hc, abs_of_neg (by linarith : e.w < 0)]
    exact ⟨le_rfl, by linarith, by nlinarith⟩
  · rw [h3]
    exact ⟨abs_le.mpr ⟨h1, h2⟩, le_rfl, mul_self_nonneg _⟩
  · rw [h2, abs_of_nonneg hc, abs_of_pos (by linarith : 0 < e.w)]
    exact ⟨le_rfl, h1.le, by nlinarith⟩

theorem scale_good (k : α) (hk0 : 0 ≤ k) (hk1 : k ≤ 1) (e : E α) (h : Good e) : Good (scaleW k e) := by
  obtain ⟨h1, h2, h3⟩ := h
  have hk : |k| = k := abs_of_nonneg hk0
  have hle : |e.w| * k ≤ |e.w| := mul_le_of_le_one_right (abs_nonneg _) hk1
  simp only [Good, scaleW, abs_mul, hk]
  exact ⟨hle.trans h1, hle.trans h2, by rw [← mul_assoc]; exact mul_nonneg h3 hk0⟩

theorem classFactor_mem (c : Nat) (cap : α) (es : List (E α)) (hc : 0 ≤ cap) :
    0 ≤ classFactor c cap es ∧ classFactor c cap es ≤ 1 := by
  unfold classFactor
  split_ifs with h
  · have hg : 0 < classGross c es := lt_of_le_of_lt hc h
    exact ⟨div_nonneg hc hg.le, (div_le_one hg).mpr h.le⟩
  · exact ⟨zero_le_one, le_rfl⟩

theorem grossFactor_mem (G : α) (es : List (E α)) (hG : 0 ≤ G) : 0 ≤ grossFactor G es ∧ grossFactor G es ≤ 1 := by
  unfold grossFactor
  split_ifs with h
  · have hg : 0 < gross es := lt_of_le_of_lt hG h
    exact ⟨div_nonneg hG hg.le, (div_le_one hg).mpr h.le⟩
  · exact ⟨zero_le_one, le_rfl⟩

theorem classStep_good (c : Nat) (cap : α) (hc : 0 ≤ cap) (es : List (E α)) (h : ∀ e ∈ es, Good e) :
    ∀ e ∈ classStep c cap es, Good e := by
  intro e he
  obtain ⟨x, hx, rfl⟩ := List.mem_map.mp he
  obtain ⟨k0, k1⟩ := classFactor_mem c cap es hc
  split_ifs
  · exact scale_good _ k0 k1 x (h x hx)
  · exact h x hx

theorem classSteps_good (caps : List (Nat × α)) (hc : ∀ p ∈ caps, 0 ≤ p.2) (es : List (E α)) (h : ∀ e ∈ es, Good e) :
    ∀ e ∈ classSteps caps es, Good e := by
  induction caps generalizing es with
  | nil => exact h
  | cons p rest ih =>
    obtain ⟨c, cap⟩ := p
    exact ih (fun q hq => hc q (List.mem_cons_of_mem _ hq)) _
      (classStep_good c cap (hc (c, cap) List.mem_cons_self) es h)

/-- Every name is within its cap, no larger than its signal's weight, and never flips. -/
theorem capAll_good (caps : List (Nat × α)) (G : α) (hG : 0 ≤ G) (hc : ∀ p ∈ caps, 0 ≤ p.2) (es : List (E α))
    (h : ∀ e ∈ es, Fresh e) : ∀ e ∈ capAll caps G es, Good e := by
  have h1 : ∀ e ∈ es.map clipW, Good e := by
    intro e he
    obtain ⟨x, hx, rfl⟩ := List.mem_map.mp he
    exact clip_good x (h x hx)
  have h2 := classSteps_good caps hc _ h1
  intro e he
  obtain ⟨x, hx, rfl⟩ := List.mem_map.mp he
  obtain ⟨k0, k1⟩ := grossFactor_mem G (classSteps caps (es.map clipW)) hG
  exact scale_good _ k0 k1 x (h2 x hx)

theorem gross_scale (k : α) (hk : 0 ≤ k) (es : List (E α)) : gross (es.map (scaleW k)) = gross es * k := by
  simp only [gross, List.map_map, Function.comp_def, scaleW, abs_mul, abs_of_nonneg hk]
  rw [List.sum_map_mul_right]

/-- The book's gross ends at most `gross_cap`. -/
theorem gross_cap_holds (G : α) (hG : 0 ≤ G) (es : List (E α)) : gross (grossStep G es) ≤ G := by
  unfold grossStep
  obtain ⟨k0, -⟩ := grossFactor_mem G es hG
  rw [gross_scale _ k0]
  unfold grossFactor
  split_ifs with h
  · have hg : 0 < gross es := lt_of_le_of_lt hG h
    rw [mul_div_cancel₀ _ hg.ne']
  · rw [mul_one]; exact not_lt.mp h

theorem capAll_gross (caps : List (Nat × α)) (G : α) (hG : 0 ≤ G) (es : List (E α)) : gross (capAll caps G es) ≤ G :=
  gross_cap_holds G hG _

theorem filter_classMap (c : Nat) (k : α) (es : List (E α)) :
    (es.map (fun e => if e.cls = c then scaleW k e else e)).filter (fun e => e.cls = c)
      = (es.filter (fun e => e.cls = c)).map (scaleW k) := by
  induction es with
  | nil => rfl
  | cons x xs ih =>
    by_cases hx : x.cls = c
    · simp [List.filter_cons, hx, ih]
    · simp [List.filter_cons, hx, ih]

/-- A class's own step brings its gross to at most its cap. -/
theorem class_cap_after_its_step (c : Nat) (cap : α) (hc : 0 ≤ cap) (es : List (E α)) :
    classGross c (classStep c cap es) ≤ cap := by
  obtain ⟨k0, -⟩ := classFactor_mem c cap es hc
  have h : classGross c (classStep c cap es) = classGross c es * classFactor c cap es := by
    unfold classGross classStep
    rw [filter_classMap, gross_scale _ k0]
  rw [h]
  unfold classFactor
  split_ifs with hlt
  · have hg : 0 < classGross c es := lt_of_le_of_lt hc hlt
    rw [mul_div_cancel₀ _ hg.ne']
  · rw [mul_one]; exact not_lt.mp hlt

end AetherFormal.PremiaCaps
