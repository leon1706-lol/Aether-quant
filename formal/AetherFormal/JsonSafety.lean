/-!
# `json_safety.sanitize_json_finite`

A JSON tree whose numbers carry a finiteness flag; sanitising turns every non-finite number into `null`, rebuilds
arrays (tuples become lists in Python) and objects, and keeps keys. NumPy scalars are outside the model.
-/

namespace AetherFormal.JsonSafety

mutual
  inductive J (α : Type) where
    | null
    | bool (b : Bool)
    | int (i : Int)
    | num (x : α) (finite : Bool)
    | str (s : String)
    | arr (xs : JList α)
    | obj (kvs : JObj α)
  inductive JList (α : Type) where
    | nil
    | cons (j : J α) (rest : JList α)
  inductive JObj (α : Type) where
    | nil
    | cons (k : String) (j : J α) (rest : JObj α)
end

variable {α : Type}

mutual
  def sanitize : J α → J α
    | .num x true => .num x true
    | .num _ false => .null
    | .arr xs => .arr (sanitizeList xs)
    | .obj kvs => .obj (sanitizeObj kvs)
    | j => j
  def sanitizeList : JList α → JList α
    | .nil => .nil
    | .cons j rest => .cons (sanitize j) (sanitizeList rest)
  def sanitizeObj : JObj α → JObj α
    | .nil => .nil
    | .cons k j rest => .cons k (sanitize j) (sanitizeObj rest)
end

mutual
  def allFinite : J α → Bool
    | .num _ f => f
    | .arr xs => allFiniteList xs
    | .obj kvs => allFiniteObj kvs
    | _ => true
  def allFiniteList : JList α → Bool
    | .nil => true
    | .cons j rest => allFinite j && allFiniteList rest
  def allFiniteObj : JObj α → Bool
    | .nil => true
    | .cons _ j rest => allFinite j && allFiniteObj rest
end

def keys : JObj α → List String
  | .nil => []
  | .cons k _ rest => k :: keys rest

mutual
  /-- The output holds no non-finite number, so `json.dumps(..., allow_nan=False)` never raises. -/
  theorem sanitize_finite : ∀ j : J α, allFinite (sanitize j) = true
    | .null => rfl
    | .bool _ => rfl
    | .int _ => rfl
    | .num _ true => rfl
    | .num _ false => rfl
    | .str _ => rfl
    | .arr xs => by simp only [sanitize, allFinite]; exact sanitizeList_finite xs
    | .obj kvs => by simp only [sanitize, allFinite]; exact sanitizeObj_finite kvs
  theorem sanitizeList_finite : ∀ xs : JList α, allFiniteList (sanitizeList xs) = true
    | .nil => rfl
    | .cons j rest => by
      simp only [sanitizeList, allFiniteList, sanitize_finite j, sanitizeList_finite rest, Bool.and_self]
  theorem sanitizeObj_finite : ∀ kvs : JObj α, allFiniteObj (sanitizeObj kvs) = true
    | .nil => rfl
    | .cons _ j rest => by
      simp only [sanitizeObj, allFiniteObj, sanitize_finite j, sanitizeObj_finite rest, Bool.and_self]
end

mutual
  /-- Sanitising twice is sanitising once. -/
  theorem sanitize_idem : ∀ j : J α, sanitize (sanitize j) = sanitize j
    | .null => rfl
    | .bool _ => rfl
    | .int _ => rfl
    | .num _ true => rfl
    | .num _ false => rfl
    | .str _ => rfl
    | .arr xs => by simp only [sanitize, sanitizeList_idem xs]
    | .obj kvs => by simp only [sanitize, sanitizeObj_idem kvs]
  theorem sanitizeList_idem : ∀ xs : JList α, sanitizeList (sanitizeList xs) = sanitizeList xs
    | .nil => rfl
    | .cons j rest => by simp only [sanitizeList, sanitize_idem j, sanitizeList_idem rest]
  theorem sanitizeObj_idem : ∀ kvs : JObj α, sanitizeObj (sanitizeObj kvs) = sanitizeObj kvs
    | .nil => rfl
    | .cons _ j rest => by simp only [sanitizeObj, sanitize_idem j, sanitizeObj_idem rest]
end

/-- Object keys pass through unchanged. -/
theorem sanitizeObj_keys : ∀ kvs : JObj α, keys (sanitizeObj kvs) = keys kvs
  | .nil => rfl
  | .cons k _ rest => by simp only [sanitizeObj, keys, sanitizeObj_keys rest]

/-- A tree with only finite numbers is returned unchanged. -/
theorem sanitize_finite_id (x : α) : sanitize (J.num x true) = J.num x true := rfl

end AetherFormal.JsonSafety
