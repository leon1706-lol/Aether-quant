import Mathlib.Algebra.Order.Field.Basic
import Mathlib.Algebra.Order.Field.Rat
import Mathlib.Algebra.BigOperators.Group.List.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SplitIfs

/-!
# `portfolio/book_neutrality.py`

`apply_book_neutrality`: per-name cap, sector shrink-toward-cap, dollar neutrality (scale the larger leg down), gross cap.
The weights only; the diagnostics dict is not modelled. `reapply` is the V6.4.3 option
`reapply_sector_cap_after_dollar_neutral` (default off): the sector shrink runs again after the dollar step.
-/

set_option linter.unusedSectionVars false

namespace AetherFormal.BookNeutrality

variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]

structure Entry (α : Type*) where
  sym : Nat
  sector : Nat
  w : α
  deriving Repr

def Entry.scale (k : α) (e : Entry α) : Entry α := { e with w := e.w * k }

def clip (lo hi x : α) : α := max lo (min x hi)

/-- Step 1. A non-positive cap is skipped (V6.4.3; it used to zero the book at 0 and flip every short long below 0). -/
def capNames (c : α) (b : List (Entry α)) : List (Entry α) :=
  if 0 < c then b.map fun e => { e with w := clip (-c) c e.w } else b

def sectorNet (s : Nat) (b : List (Entry α)) : α := (b.map fun e => if e.sector = s then e.w else 0).sum

/-- The factor step 2 applies to every member of a sector whose |net| is over the cap. -/
def sectorFactor (cap : α) (b : List (Entry α)) (s : Nat) : α :=
  if 0 < cap ∧ cap < |sectorNet s b| then cap / |sectorNet s b| else 1

/-- Step 2. -/
def capSectors (cap : α) (b : List (Entry α)) : List (Entry α) :=
  b.map fun e => e.scale (sectorFactor cap b e.sector)

def longSum (b : List (Entry α)) : α := (b.map fun e => max e.w 0).sum
def shortSum (b : List (Entry α)) : α := (b.map fun e => max (-e.w) 0).sum

/-- Step 3, per entry: scale the larger leg down so both legs sum to the smaller one; a one-sided book is left alone. -/
def dollarFn (b : List (Entry α)) (e : Entry α) : Entry α :=
  if 0 < longSum b ∧ 0 < shortSum b then
    if shortSum b < longSum b then (if 0 < e.w then e.scale (shortSum b / longSum b) else e)
    else if longSum b < shortSum b then (if e.w < 0 then e.scale (longSum b / shortSum b) else e)
    else e
  else e

def dollarNeutral (b : List (Entry α)) : List (Entry α) := b.map (dollarFn b)

def gross (b : List (Entry α)) : α := (b.map fun e => |e.w|).sum

/-- Step 4. -/
def grossCap (cap : α) (b : List (Entry α)) : List (Entry α) :=
  if 0 < cap ∧ cap < gross b then b.map (Entry.scale (cap / gross b)) else b

structure Config (α : Type*) where
  nameCap : α
  sectorOn : Bool
  sectorCap : α
  dollarOn : Bool
  grossCap : α
  reapply : Bool := false

def neutralize (cfg : Config α) (b : List (Entry α)) : List (Entry α) :=
  let b1 := capNames cfg.nameCap b
  let b2 := if cfg.sectorOn then capSectors cfg.sectorCap b1 else b1
  let b3 := if cfg.dollarOn then dollarNeutral b2 else b2
  let b3' := if cfg.reapply && cfg.sectorOn then capSectors cfg.sectorCap b3 else b3
  grossCap cfg.grossCap b3'

/-! ### Shrink-only and sign preservation -/

/-- `|y| ≤ |x|` and `y` never has the opposite sign of `x`. -/
def Shrinks (x y : α) : Prop := |y| ≤ |x| ∧ 0 ≤ x * y

theorem shrinks_refl (x : α) : Shrinks x x := ⟨le_refl _, mul_self_nonneg x⟩

theorem shrinks_trans {x y z : α} (h1 : Shrinks x y) (h2 : Shrinks y z) : Shrinks x z := by
  refine ⟨h2.1.trans h1.1, ?_⟩
  by_cases hy : y = 0
  · subst hy
    have hz : z = 0 := abs_nonpos_iff.mp (by simpa using h2.1)
    simp [hz]
  · have hy2 : 0 < y * y := mul_self_pos.mpr hy
    have h3 : 0 ≤ (x * y) * (y * z) := mul_nonneg h1.2 h2.2
    have h4 : 0 * (y * y) ≤ (x * z) * (y * y) := by nlinarith [h3]
    exact le_of_mul_le_mul_right h4 hy2

theorem shrinks_scale (x : α) {k : α} (h0 : 0 ≤ k) (h1 : k ≤ 1) : Shrinks x (x * k) := by
  constructor
  · rw [abs_mul, abs_of_nonneg h0]
    nlinarith [abs_nonneg x]
  · rw [← mul_assoc]
    exact mul_nonneg (mul_self_nonneg x) h0

theorem shrinks_clip (x : α) {c : α} (hc : 0 ≤ c) : Shrinks x (clip (-c) c x) := by
  unfold clip
  rcases le_total x c with h | h
  · rw [min_eq_left h]
    rcases le_total (-c) x with h' | h'
    · rw [max_eq_right h']; exact shrinks_refl x
    · rw [max_eq_left h']
      constructor
      · rw [abs_neg, abs_of_nonneg hc, abs_of_nonpos (by linarith)]; linarith
      · nlinarith
  · rw [min_eq_right h, max_eq_right (by linarith)]
    constructor
    · rw [abs_of_nonneg hc, abs_of_nonneg (by linarith)]; exact h
    · nlinarith

theorem abs_clip_le (x : α) {c : α} (hc : 0 ≤ c) : |clip (-c) c x| ≤ c := by
  unfold clip
  rw [abs_le]
  exact ⟨le_max_left _ _, max_le (by linarith) (min_le_right _ _)⟩

/-- A step that maps every entry, keeping its symbol and sector, and shrinks its weight. -/
def ShrinkStep (f : List (Entry α) → List (Entry α)) : Prop :=
  ∀ b, (f b).length = b.length ∧
    ∀ i (h : i < b.length) (h' : i < (f b).length),
      (f b)[i].sym = b[i].sym ∧ (f b)[i].sector = b[i].sector ∧ Shrinks b[i].w (f b)[i].w

theorem shrinkStep_comp {f g : List (Entry α) → List (Entry α)} (hf : ShrinkStep f) (hg : ShrinkStep g) :
    ShrinkStep (g ∘ f) := by
  intro b
  obtain ⟨hl1, h1⟩ := hf b
  obtain ⟨hl2, h2⟩ := hg (f b)
  refine ⟨by simp [hl2, hl1], ?_⟩
  intro i h h'
  have hi : i < (f b).length := by rw [hl1]; exact h
  obtain ⟨a1, a2, a3⟩ := h1 i h hi
  obtain ⟨c1, c2, c3⟩ := h2 i hi h'
  exact ⟨c1.trans a1, c2.trans a2, shrinks_trans a3 c3⟩

/-- Every step is a `map` whose per-entry function (which may read the whole list) keeps symbol / sector and shrinks. -/
theorem shrinkStep_map (g : List (Entry α) → Entry α → Entry α)
    (hg : ∀ b e, (g b e).sym = e.sym ∧ (g b e).sector = e.sector ∧ Shrinks e.w (g b e).w) :
    ShrinkStep (fun b => b.map (g b)) := by
  intro b
  refine ⟨by simp, ?_⟩
  intro i h h'
  simp only [List.getElem_map]
  exact hg b b[i]

theorem shrinkStep_congr {f g : List (Entry α) → List (Entry α)} (h : ∀ b, f b = g b) (hg : ShrinkStep g) :
    ShrinkStep f := by
  have : f = g := funext h
  subst this
  exact hg

theorem scale_spec (e : Entry α) {k : α} (h0 : 0 ≤ k) (h1 : k ≤ 1) :
    (e.scale k).sym = e.sym ∧ (e.scale k).sector = e.sector ∧ Shrinks e.w (e.scale k).w :=
  ⟨rfl, rfl, shrinks_scale e.w h0 h1⟩

theorem id_spec (e : Entry α) : e.sym = e.sym ∧ e.sector = e.sector ∧ Shrinks e.w e.w := ⟨rfl, rfl, shrinks_refl _⟩

theorem shrinkStep_ite (p : Prop) [Decidable p] {f : List (Entry α) → List (Entry α)} (hf : ShrinkStep f) :
    ShrinkStep (fun b => if p then f b else b) := by
  by_cases hp : p
  · exact shrinkStep_congr (fun b => if_pos hp) hf
  · exact shrinkStep_congr (g := fun b => b.map fun e => e) (fun b => by rw [if_neg hp, List.map_id'])
      (shrinkStep_map (fun _ e => e) (fun _ e => id_spec e))

theorem sectorFactor_mem (cap : α) (b : List (Entry α)) (s : Nat) :
    0 ≤ sectorFactor cap b s ∧ sectorFactor cap b s ≤ 1 := by
  unfold sectorFactor
  split_ifs with h
  · obtain ⟨h0, h1⟩ := h
    have hpos : 0 < |sectorNet s b| := lt_trans h0 h1
    exact ⟨div_nonneg h0.le hpos.le, (div_le_one hpos).mpr h1.le⟩
  · exact ⟨zero_le_one, le_refl 1⟩

theorem capNames_eq (c : α) (b : List (Entry α)) :
    capNames c b = b.map fun e => if 0 < c then { e with w := clip (-c) c e.w } else e := by
  unfold capNames
  split_ifs with hc
  · simp [hc]
  · simp [hc]

theorem capNames_shrink (c : α) : ShrinkStep (capNames c) := by
  refine shrinkStep_congr (capNames_eq c) (shrinkStep_map (fun _ e => if 0 < c then { e with w := clip (-c) c e.w } else e) ?_)
  intro _ e
  by_cases hc : 0 < c
  · rw [if_pos hc]; exact ⟨rfl, rfl, shrinks_clip e.w hc.le⟩
  · rw [if_neg hc]; exact id_spec e

theorem capSectors_shrink (cap : α) : ShrinkStep (capSectors cap) :=
  shrinkStep_map (fun b e => e.scale (sectorFactor cap b e.sector))
    (fun b e => scale_spec e (sectorFactor_mem cap b e.sector).1 (sectorFactor_mem cap b e.sector).2)

theorem dollarFn_spec (b : List (Entry α)) (e : Entry α) :
    (dollarFn b e).sym = e.sym ∧ (dollarFn b e).sector = e.sector ∧ Shrinks e.w (dollarFn b e).w := by
  unfold dollarFn
  split_ifs with hb h1 he h2 he2
  · exact scale_spec e (div_nonneg hb.2.le hb.1.le) ((div_le_one hb.1).mpr h1.le)
  · exact id_spec e
  · exact scale_spec e (div_nonneg hb.1.le hb.2.le) ((div_le_one hb.2).mpr h2.le)
  · exact id_spec e
  · exact id_spec e
  · exact id_spec e

theorem dollarNeutral_shrink : ShrinkStep (dollarNeutral (α := α)) := shrinkStep_map dollarFn dollarFn_spec

theorem grossCap_eq (cap : α) (b : List (Entry α)) :
    grossCap cap b = b.map fun e => if 0 < cap ∧ cap < gross b then e.scale (cap / gross b) else e := by
  unfold grossCap
  split_ifs with h
  · rfl
  · simp

theorem grossCap_shrink (cap : α) : ShrinkStep (grossCap cap) := by
  refine shrinkStep_congr (grossCap_eq cap)
    (shrinkStep_map (fun b e => if 0 < cap ∧ cap < gross b then e.scale (cap / gross b) else e) ?_)
  intro b e
  by_cases h : 0 < cap ∧ cap < gross b
  · rw [if_pos h]
    have hg : 0 < gross b := lt_trans h.1 h.2
    exact scale_spec e (div_nonneg h.1.le hg.le) ((div_le_one hg).mpr h.2.le)
  · rw [if_neg h]; exact id_spec e

/-- Steps 2-4 (everything after the per-name cap). -/
def rest (cfg : Config α) : List (Entry α) → List (Entry α) :=
  grossCap cfg.grossCap ∘ (fun b => if cfg.reapply && cfg.sectorOn then capSectors cfg.sectorCap b else b) ∘
    (fun b => if cfg.dollarOn then dollarNeutral b else b) ∘ (fun b => if cfg.sectorOn then capSectors cfg.sectorCap b else b)

theorem neutralize_eq (cfg : Config α) (b : List (Entry α)) : neutralize cfg b = rest cfg (capNames cfg.nameCap b) := rfl

theorem rest_shrink (cfg : Config α) : ShrinkStep (rest cfg) :=
  shrinkStep_comp (shrinkStep_comp (shrinkStep_comp (shrinkStep_ite _ (capSectors_shrink _)) (shrinkStep_ite _ dollarNeutral_shrink))
    (shrinkStep_ite _ (capSectors_shrink _))) (grossCap_shrink _)

/-- Every output weight keeps its symbol and sector, shrinks in magnitude and never changes sign. -/
theorem neutralize_shrinks (cfg : Config α) : ShrinkStep (neutralize cfg) :=
  shrinkStep_congr (g := rest cfg ∘ capNames cfg.nameCap) (fun b => neutralize_eq cfg b)
    (shrinkStep_comp (capNames_shrink cfg.nameCap) (rest_shrink cfg))

/-! ### The caps -/

/-- A shrinking step keeps any bound on |weight|. -/
theorem shrinkStep_bound {f : List (Entry α) → List (Entry α)} (hf : ShrinkStep f) (b : List (Entry α)) (c : α)
    (hb : ∀ e ∈ b, |e.w| ≤ c) : ∀ e ∈ f b, |e.w| ≤ c := by
  intro e he
  obtain ⟨i, hi, rfl⟩ := List.mem_iff_getElem.mp he
  obtain ⟨hl, hs⟩ := hf b
  have hib : i < b.length := by rw [← hl]; exact hi
  exact (hs i hib hi).2.2.1.trans (hb _ (List.getElem_mem hib))

theorem capNames_bound (c : α) (hc : 0 < c) (b : List (Entry α)) : ∀ e ∈ capNames c b, |e.w| ≤ c := by
  intro e he
  rw [capNames_eq] at he
  obtain ⟨x, _, rfl⟩ := List.mem_map.mp he
  rw [if_pos hc]
  exact abs_clip_le x.w hc.le

/-- Per-name cap: every final |weight| is at most `max_weight_per_name` (when it is positive). -/
theorem name_cap (cfg : Config α) (hc : 0 < cfg.nameCap) (b : List (Entry α)) :
    ∀ e ∈ neutralize cfg b, |e.w| ≤ cfg.nameCap := by
  rw [neutralize_eq]
  exact shrinkStep_bound (rest_shrink cfg) _ _ (capNames_bound cfg.nameCap hc b)

theorem sum_map_mul_left' {β : Type*} (l : List β) (f : β → α) (k : α) :
    (l.map fun x => k * f x).sum = k * (l.map f).sum := by
  induction l with
  | nil => simp
  | cons x xs ih => simp [ih, mul_add]

theorem gross_map_scale (k : α) (hk : 0 ≤ k) (b : List (Entry α)) :
    gross (b.map (Entry.scale k)) = k * gross b := by
  unfold gross
  rw [List.map_map]
  have : ((fun e : Entry α => |e.w|) ∘ Entry.scale k) = fun e => k * |e.w| := by
    funext e
    show |e.w * k| = k * |e.w|
    rw [abs_mul, abs_of_nonneg hk, mul_comm]
  rw [this, sum_map_mul_left']

/-- Gross cap: the final gross exposure is at most `gross_exposure_cap` (when it is positive). -/
theorem gross_cap_holds (cap : α) (hc : 0 < cap) (b : List (Entry α)) : gross (grossCap cap b) ≤ cap := by
  unfold grossCap
  by_cases h : cap < gross b
  · rw [if_pos ⟨hc, h⟩]
    have hg : 0 < gross b := lt_trans hc h
    rw [gross_map_scale _ (div_nonneg hc.le hg.le), div_mul_cancel₀ _ hg.ne']
  · rw [if_neg (fun hh => h hh.2)]
    exact not_lt.mp h

theorem neutralize_gross (cfg : Config α) (hc : 0 < cfg.grossCap) (b : List (Entry α)) :
    gross (neutralize cfg b) ≤ cfg.grossCap := gross_cap_holds _ hc _

/-! ### Sector shrink -/

theorem sectorNet_scale_members (s : Nat) (k : α) (b : List (Entry α)) (g : Entry α → α)
    (hg : ∀ e, e.sector = s → g e = k) :
    sectorNet s (b.map fun e => e.scale (g e)) = k * sectorNet s b := by
  unfold sectorNet
  rw [List.map_map, ← sum_map_mul_left']
  congr 1
  apply List.map_congr_left
  intro e _
  show (if e.sector = s then e.w * g e else 0) = k * (if e.sector = s then e.w else 0)
  by_cases he : e.sector = s
  · rw [if_pos he, if_pos he, hg e he, mul_comm]
  · rw [if_neg he, if_neg he, mul_zero]

/-- After step 2 every sector's |net| is within the cap. -/
theorem sector_cap_after_capSectors (cap : α) (hc : 0 < cap) (b : List (Entry α)) (s : Nat) :
    |sectorNet s (capSectors cap b)| ≤ cap := by
  have key := sectorNet_scale_members s (sectorFactor cap b s) b (fun e => sectorFactor cap b e.sector)
    (fun e he => by simp only [he])
  have hcs : capSectors cap b = b.map fun e => e.scale (sectorFactor cap b e.sector) := rfl
  rw [hcs, key]
  unfold sectorFactor
  by_cases h : 0 < cap ∧ cap < |sectorNet s b|
  · rw [if_pos h]
    have hpos : 0 < |sectorNet s b| := lt_trans hc h.2
    rw [abs_mul, abs_div, abs_abs, abs_of_pos hc, div_mul_cancel₀ _ hpos.ne']
  · rw [if_neg h, one_mul]
    push_neg at h
    exact h hc

theorem sectorNet_map_scale (s : Nat) (k : α) (b : List (Entry α)) :
    sectorNet s (b.map (Entry.scale k)) = k * sectorNet s b :=
  sectorNet_scale_members s k b (fun _ => k) (fun _ _ => rfl)

/-- With `reapply` on, every sector is within its cap at the END of the pipeline. -/
theorem sector_cap_with_reapply (cfg : Config α) (hr : cfg.reapply = true) (hs : cfg.sectorOn = true)
    (hc : 0 < cfg.sectorCap) (b : List (Entry α)) (s : Nat) :
    |sectorNet s (neutralize cfg b)| ≤ cfg.sectorCap := by
  set b3 := (fun b => if cfg.dollarOn then dollarNeutral b else b)
    ((fun b => if cfg.sectorOn then capSectors cfg.sectorCap b else b) (capNames cfg.nameCap b))
  have hn : neutralize cfg b = grossCap cfg.grossCap (capSectors cfg.sectorCap b3) := by
    show grossCap cfg.grossCap (if cfg.reapply && cfg.sectorOn then capSectors cfg.sectorCap b3 else b3) = _
    rw [if_pos (by simp [hr, hs])]
  rw [hn]
  have h3 := sector_cap_after_capSectors cfg.sectorCap hc b3 s
  unfold grossCap
  by_cases h : 0 < cfg.grossCap ∧ cfg.grossCap < gross (capSectors cfg.sectorCap b3)
  · rw [if_pos h]
    have hg : 0 < gross (capSectors cfg.sectorCap b3) := lt_trans h.1 h.2
    have hk0 : 0 ≤ cfg.grossCap / gross (capSectors cfg.sectorCap b3) := div_nonneg h.1.le hg.le
    have hk1 : cfg.grossCap / gross (capSectors cfg.sectorCap b3) ≤ 1 := (div_le_one hg).mpr h.2.le
    rw [sectorNet_map_scale, abs_mul, abs_of_nonneg hk0]
    nlinarith [abs_nonneg (sectorNet s (capSectors cfg.sectorCap b3))]
  · rw [if_neg h]
    exact h3

/-! ### Dollar neutrality -/

theorem max_scale (x k : α) (hk : 0 ≤ k) : max (x * k) 0 = k * max x 0 := by
  rw [mul_comm k, max_mul_of_nonneg x 0 hk, zero_mul]

theorem longSum_map_scale (k : α) (hk : 0 ≤ k) (b : List (Entry α)) :
    longSum (b.map (Entry.scale k)) = k * longSum b := by
  unfold longSum
  rw [List.map_map]
  have : ((fun e : Entry α => max e.w 0) ∘ Entry.scale k) = fun e => k * max e.w 0 := by
    funext e
    exact max_scale e.w k hk
  rw [this, sum_map_mul_left']

theorem shortSum_map_scale (k : α) (hk : 0 ≤ k) (b : List (Entry α)) :
    shortSum (b.map (Entry.scale k)) = k * shortSum b := by
  unfold shortSum
  rw [List.map_map]
  have : ((fun e : Entry α => max (-e.w) 0) ∘ Entry.scale k) = fun e => k * max (-e.w) 0 := by
    funext e
    show max (-(e.w * k)) 0 = k * max (-e.w) 0
    rw [← neg_mul]
    exact max_scale (-e.w) k hk
  rw [this, sum_map_mul_left']

/-- Step 3 balances the legs when both are present. -/
theorem dollarNeutral_balanced (b : List (Entry α)) (hL : 0 < longSum b) (hS : 0 < shortSum b) :
    longSum (dollarNeutral b) = shortSum (dollarNeutral b) := by
  by_cases h1 : shortSum b < longSum b
  · have hk : 0 < shortSum b / longSum b := div_pos hS hL
    have hf : ∀ e, dollarFn b e = if 0 < e.w then e.scale (shortSum b / longSum b) else e := by
      intro e; unfold dollarFn; rw [if_pos ⟨hL, hS⟩, if_pos h1]
    have hl : longSum (dollarNeutral b) = shortSum b / longSum b * longSum b := by
      unfold dollarNeutral longSum
      rw [List.map_map, ← sum_map_mul_left']
      congr 1
      apply List.map_congr_left
      intro e _
      show max (dollarFn b e).w 0 = shortSum b / longSum b * max e.w 0
      rw [hf e]
      by_cases he : 0 < e.w
      · rw [if_pos he]; exact max_scale e.w _ hk.le
      · rw [if_neg he, max_eq_right (not_lt.mp he), mul_zero]
    have hs : shortSum (dollarNeutral b) = shortSum b := by
      unfold dollarNeutral shortSum
      rw [List.map_map]
      congr 1
      apply List.map_congr_left
      intro e _
      show max (-(dollarFn b e).w) 0 = max (-e.w) 0
      rw [hf e]
      by_cases he : 0 < e.w
      · rw [if_pos he]
        show max (-(e.w * (shortSum b / longSum b))) 0 = max (-e.w) 0
        rw [max_eq_right (by nlinarith), max_eq_right (by linarith)]
      · rw [if_neg he]
    rw [hl, hs, div_mul_cancel₀ _ hL.ne']
  · by_cases h2 : longSum b < shortSum b
    · have hk : 0 < longSum b / shortSum b := div_pos hL hS
      have hf : ∀ e, dollarFn b e = if e.w < 0 then e.scale (longSum b / shortSum b) else e := by
        intro e; unfold dollarFn; rw [if_pos ⟨hL, hS⟩, if_neg h1, if_pos h2]
      have hs : shortSum (dollarNeutral b) = longSum b / shortSum b * shortSum b := by
        unfold dollarNeutral shortSum
        rw [List.map_map, ← sum_map_mul_left']
        congr 1
        apply List.map_congr_left
        intro e _
        show max (-(dollarFn b e).w) 0 = longSum b / shortSum b * max (-e.w) 0
        rw [hf e]
        by_cases he : e.w < 0
        · rw [if_pos he]
          show max (-(e.w * (longSum b / shortSum b))) 0 = longSum b / shortSum b * max (-e.w) 0
          rw [← neg_mul]; exact max_scale (-e.w) _ hk.le
        · rw [if_neg he, max_eq_right (by linarith [not_lt.mp he]), mul_zero]
      have hl : longSum (dollarNeutral b) = longSum b := by
        unfold dollarNeutral longSum
        rw [List.map_map]
        congr 1
        apply List.map_congr_left
        intro e _
        show max (dollarFn b e).w 0 = max e.w 0
        rw [hf e]
        by_cases he : e.w < 0
        · rw [if_pos he]
          show max (e.w * (longSum b / shortSum b)) 0 = max e.w 0
          rw [max_eq_right (by nlinarith), max_eq_right he.le]
        · rw [if_neg he]
      rw [hl, hs, div_mul_cancel₀ _ hS.ne']
    · have hid : dollarNeutral b = b := by
        unfold dollarNeutral
        conv_rhs => rw [← List.map_id b]
        apply List.map_congr_left
        intro e _
        unfold dollarFn
        rw [if_pos ⟨hL, hS⟩, if_neg h1, if_neg h2]
        rfl
      rw [hid]
      exact le_antisymm (not_lt.mp h1) (not_lt.mp h2)

/-- Dollar neutrality survives the gross cap (which scales both legs by the same factor). -/
theorem grossCap_balanced (cap : α) (b : List (Entry α)) (h : longSum b = shortSum b) :
    longSum (grossCap cap b) = shortSum (grossCap cap b) := by
  unfold grossCap
  by_cases hc : 0 < cap ∧ cap < gross b
  · rw [if_pos hc]
    have hg : 0 < gross b := lt_trans hc.1 hc.2
    have hk : 0 ≤ cap / gross b := div_nonneg hc.1.le hg.le
    rw [longSum_map_scale _ hk, shortSum_map_scale _ hk, h]
  · rw [if_neg hc]
    exact h

/-- FINDING (V6.4.3): with the shipped pipeline (`reapply` off) a sector that holds both a long and a short can end
ABOVE the sector cap, because step 3 shrinks one leg only. Sector 0 = {+0.04, -0.09} sits exactly at the cap 0.05,
sectors 1 and 2 = {+0.5} are capped to +0.05; the longs then scale by 9/14 and sector 0's net becomes -9/140.
(`native_decide` evaluates the concrete book with compiled exact rational arithmetic.) -/
def counterBook : List (Entry ℚ) :=
  [⟨0, 0, 1 / 25⟩, ⟨1, 0, -9 / 100⟩, ⟨2, 1, 1 / 2⟩, ⟨3, 2, 1 / 2⟩]

def counterConfig : Config ℚ :=
  { nameCap := 1, sectorOn := true, sectorCap := 1 / 20, dollarOn := true, grossCap := 10 }

theorem counter_net : sectorNet 0 (neutralize counterConfig counterBook) = -9 / 140 := by native_decide

theorem sector_cap_counterexample :
    counterConfig.sectorCap < |sectorNet 0 (neutralize counterConfig counterBook)| := by
  rw [counter_net]
  show (1 / 20 : ℚ) < |(-9 / 140 : ℚ)|
  rw [abs_of_neg (by norm_num)]
  norm_num

/-- FINDING (V6.4.3): the pre-V6.4.3 per-name clip with a negative cap turns every weight, shorts included, into a
long of size |cap|. -/
theorem old_clip_flips_shorts : clip (-(-1 / 10 : ℚ)) (-1 / 10) (-1 / 2) = 1 / 10 := by
  unfold clip; norm_num

end AetherFormal.BookNeutrality
