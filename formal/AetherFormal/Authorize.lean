import Mathlib.Data.List.Basic

/-!
# `monitoring/auth.py`: `authorize` never grants above a user's role or outside their accounts

Roles are ranks (1 viewer, 2 operator, 3 admin). With auth off, a read (rank 1) is open to anyone; everything else, and
everything once auth is on, needs a user whose rank is at least the one required and whose scope covers the account.
So an anonymous caller can never write, a viewer can never lock, an operator can never unlock, and granting is
monotone in the role.
-/

namespace AetherFormal.Authorize

structure User where
  role : Nat
  all : Bool
  accounts : List String

/-- `User.may_access`: every account, or one in the user's list; no account named is always fine. -/
def mayAccess (u : User) : Option String → Bool
  | none => true
  | some a => u.all || u.accounts.contains a

/-- `authorize(user, required, account, auth_required=...)`. -/
def authorize (u : Option User) (required : Nat) (account : Option String) (authRequired : Bool) : Bool :=
  if authRequired = false ∧ required = 1 then true
  else
    match u with
    | none => false
    | some user => decide (required ≤ user.role) && mayAccess user account

theorem never_above_role (u : User) (r : Nat) (a : Option String) (h : authorize (some u) r a true = true) : r ≤ u.role := by
  simp [authorize] at h
  exact h.1

theorem never_outside_scope (u : User) (r : Nat) (a : Option String) (h : authorize (some u) r a true = true) : mayAccess u a = true := by
  simp [authorize] at h
  exact h.2

theorem anonymous_never_writes (r : Nat) (a : Option String) (b : Bool) (hr : 1 < r) : authorize none r a b = false := by
  have hne : r ≠ 1 := by omega
  simp [authorize, hne]

theorem anonymous_reads_only_when_auth_is_off (a : Option String) : authorize none 1 a true = false := by
  simp [authorize]

theorem monotone_in_role (u u' : User) (r : Nat) (a : Option String) (b : Bool) (hrole : u.role ≤ u'.role) (hall : u'.all = u.all)
    (hacc : u'.accounts = u.accounts) (h : authorize (some u) r a b = true) : authorize (some u') r a b = true := by
  have hm : mayAccess u' a = mayAccess u a := by
    cases a <;> simp [mayAccess, hall, hacc]
  unfold authorize at h ⊢
  split_ifs at h ⊢ with hc
  · rfl
  · simp at h ⊢
    rw [hm]
    exact ⟨Nat.le_trans h.1 hrole, h.2⟩

end AetherFormal.Authorize
