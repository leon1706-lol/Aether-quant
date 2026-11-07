"""Which model generations exist and what each may hold (V6.6.1): the registry `ml/generations/registry.json`, the owner's admission rule R-ADMIT1, and a hash-chained log.

A refit of a frozen procedure is a new vintage of the same generation, so `procedure_sha256` hashes the procedure (trainer code, features, label, seeds), not the weights. A new
procedure is a new candidate and goes through a research round. Real money is outside this file: nothing here touches a broker setting or a live flag.

Stdlib only at import, apart from the project's own hash chain.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from audit.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain

# On the book, in order: gaining capital, a settled holder, still earning but falling short of its claim, on its way out. Several generations can sit in these at once.
STAGES = ("candidate", "frozen", "shadow", "ramping", "active", "fading", "winding_down", "retired", "rejected")
BOOK_STAGES = ("ramping", "active", "fading", "winding_down")
SETTLED_SESSIONS = 252
TIERS = ("installed", "tier1", "tier2", "none")
TIER2_MIN_SESSIONS = 60
SPENT_HOLDOUT_MIN_SESSIONS = 252
TIER2_MAX_NO_DATA = 0.10
CAP_LIFT_CHECKPOINTS = (252, 504, 756)
CAP_LIFT_ALPHA_T = 2.0
LIFECYCLE_EVENT = "generation_lifecycle"


@dataclass(frozen=True)
class Generation:
    id: str
    kind: str
    tier: str
    stage: str
    born: str
    procedure_sha256: str
    definition: Mapping = field(default_factory=dict)
    freeze_path: str | None = None
    needs: str | None = None
    vintages: tuple[str, ...] = ()
    expected_sharpe: float = 0.0
    note: str = ""
    admission: Mapping = field(default_factory=dict)  # selection_pass, hold_pass, edge_pass: set once, by a round's stored verdict


@dataclass(frozen=True)
class AdmissionEvidence:
    selection_pass: bool = False
    hold_pass: bool = False
    edge_pass: bool = False
    holdouts_spent: bool = False
    forward_ok_sessions: int = 0
    no_data_share: float = 0.0
    mean_diff_vs_incumbent: float | None = None
    guard_tripped: bool = False
    decay_state: str = "healthy"
    forward_alpha_t: float | None = None
    score: float | None = None  # shrunk Sharpe (`portfolio.generation_blend.shrunk_sharpe`); a generation short of its claim can still be earning


def load_registry(path: Path) -> dict[str, Generation]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, Generation] = {}
    for entry in raw["generations"]:
        if entry["stage"] not in STAGES:
            raise ValueError(f"{entry['id']}: unknown stage {entry['stage']!r}")
        if entry["tier"] not in TIERS:
            raise ValueError(f"{entry['id']}: unknown tier {entry['tier']!r}")
        out[entry["id"]] = Generation(**{**entry, "vintages": tuple(entry.get("vintages") or ())})
    return out


def save_registry(path: Path, generations: Mapping[str, Generation]) -> None:
    """Atomic, sorted, LF: one registry has one hash, and a crash can't leave half a file."""
    path = Path(path)
    payload = {"note": "Which generations exist. `aq cycle promote` changes a stage by rule; a hand edit is visible in git.", "generations": [
        {**asdict(generations[name]), "vintages": list(generations[name].vintages)} for name in sorted(generations)
    ]}
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def _tier2_forward_passes(evidence: AdmissionEvidence) -> bool:
    """R-ADMIT1's 60-session test. A zero-alpha candidate passes it about half the time, so the 30% cap is what bounds a false pass."""
    difference = evidence.mean_diff_vs_incumbent
    return (
        evidence.forward_ok_sessions >= TIER2_MIN_SESSIONS and difference is not None and difference == difference and difference >= 0.0
        and not evidence.guard_tripped and evidence.no_data_share <= TIER2_MAX_NO_DATA
    )


def admitted_to_shadow(evidence: AdmissionEvidence) -> bool:
    """Selection and the one holdout read; or, once the holdouts are spent, selection and a year of forward sessions."""
    if not evidence.selection_pass:
        return False
    if evidence.hold_pass:
        return True
    return evidence.holdouts_spent and evidence.forward_ok_sessions >= SPENT_HOLDOUT_MIN_SESSIONS


def cap_lifted(evidence: AdmissionEvidence) -> bool:
    """A tier-2 generation takes over only on forward alpha, read at fixed checkpoints so the looks are countable."""
    t = evidence.forward_alpha_t
    return (
        t is not None and t == t and t >= CAP_LIFT_ALPHA_T and evidence.forward_ok_sessions >= CAP_LIFT_CHECKPOINTS[0]
        and evidence.no_data_share <= TIER2_MAX_NO_DATA and not evidence.guard_tripped
    )


def _book_stage(stage: str, evidence: AdmissionEvidence) -> str:
    """Where a generation on the book belongs. Falling short of its claim isn't the end of it: while its score stays positive it keeps earning a share, at `fading`. It winds down only
    once it has stopped earning, and comes back if the record recovers. A stage moves one step at a time."""
    score = evidence.score
    earning = score is None or (score == score and score > 0.0)
    behind = evidence.decay_state in ("watch", "decaying")
    if stage == "ramping":
        settled = evidence.forward_ok_sessions >= SETTLED_SESSIONS and evidence.decay_state == "healthy"
        return "active" if settled else "ramping"
    if stage == "active":
        return "fading" if behind or not earning else "active"
    if stage == "fading":
        if not earning or evidence.decay_state == "decaying" and score is not None and score <= 0.0:
            return "winding_down"
        return "active" if not behind else "fading"
    return "fading" if earning and evidence.decay_state == "healthy" and score is not None else "winding_down"


def next_stage(generation: Generation, evidence: AdmissionEvidence) -> str:
    """R-ADMIT1. Moves forward only on evidence, off the book at once on a guard trip or dead state, and never by more than the rule says. Non-finite evidence holds."""
    stage = generation.stage
    if stage in ("retired", "rejected"):
        return stage
    dying = evidence.guard_tripped or evidence.decay_state == "dead"
    if stage in BOOK_STAGES:
        if dying:
            return "retired"
        return _book_stage(stage, evidence)
    if dying and stage == "shadow":
        return "rejected"
    if stage in ("candidate", "frozen"):
        if evidence.edge_pass:
            return "ramping"
        return "shadow" if admitted_to_shadow(evidence) else stage
    if stage == "shadow":
        if evidence.edge_pass or _tier2_forward_passes(evidence):
            return "ramping"
        return stage
    return stage


def share_cap(generation: Generation, evidence: AdmissionEvidence, tier2_cap: float = 0.30) -> float:
    """What the generation may hold of the paper book: all of it with a full pass or as the installed book, the tier-2 cap until its forward alpha lifts it, otherwise nothing."""
    if generation.stage in ("retired", "rejected", "candidate", "frozen", "shadow"):
        return 0.0
    if generation.tier in ("tier1", "installed") or evidence.edge_pass or cap_lifted(evidence):
        return 1.0
    return float(tier2_cap) if generation.tier == "tier2" else 0.0


def read_lifecycle(path: Path) -> list[dict]:
    path = Path(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def append_lifecycle(path: Path, *, event: str, payload: Mapping, created_at: str) -> dict:
    """A hash-chained line for each change of stage or vintage, so the record of how a generation reached the book can't be edited later without showing."""
    rows = read_lifecycle(path)
    previous = rows[-1]["hash"] if rows else GENESIS_HASH
    body = {"event": event, **payload}
    row = {"prev_hash": previous, "event_type": LIFECYCLE_EVENT, "created_at": created_at, "payload": body}
    row["hash"] = compute_entry_hash(previous, LIFECYCLE_EVENT, created_at, body)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def lifecycle_is_intact(path: Path) -> tuple[bool, int | None]:
    return verify_chain(read_lifecycle(path))
