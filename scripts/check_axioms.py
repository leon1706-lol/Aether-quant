"""Which axioms do the Lean proofs rest on? (V6.6.4)

`lake build` accepts a theorem that uses `sorry` as a warning, and a proof can lean on `native_decide` (which trusts the compiler) or an added axiom without saying so. This asks Lean for
`#print axioms` of every theorem in `formal/AetherFormal/*.lean` and fails on anything beyond Lean's three standard ones. The known exceptions are listed with their reason below.

    python scripts/check_axioms.py            # needs a built formal/ (a Codespace; `aq prove` first)
    python scripts/check_axioms.py --list     # only print the theorems it would check
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "formal"
STANDARD = {"propext", "Classical.choice", "Quot.sound"}
# A proof that trusts the compiler is allowed only where it is named here with its reason (a `native_decide` adds `Lean.ofReduceBool` and one axiom of its own, `<theorem>._native.native_decide.ax_n_m`);
# any other extra axiom, and the same trust in any other theorem, fails.
ALLOWED_NATIVE = {
    "AetherFormal.BookNeutrality.counter_net": "the sector-cap counterexample is a computed finding, not a general result (formal/README.md, Findings)",
    "AetherFormal.BookNeutrality.sector_cap_counterexample": "built on counter_net",
}
ALLOWED_EXTRA = {"Lean.ofReduceBool": "native_decide, in the two theorems of ALLOWED_NATIVE only"}
NATIVE_AXIOM = re.compile(r".*\._native\.native_decide\.ax_\d+_\d+$")
NAMESPACE = re.compile(r"^namespace\s+(\S+)", re.M)
THEOREM = re.compile(r"^(?:@\[[^\]]*\]\s*)?(?:protected\s+)?(?:theorem|lemma)\s+([A-Za-z0-9_'.]+)", re.M)


def theorems(root: Path = FORMAL) -> list[str]:
    """Fully qualified names of every theorem and lemma, by file namespace. A private one is skipped (it cannot be printed from outside)."""
    names: list[str] = []
    for path in sorted((root / "AetherFormal").glob("*.lean")):
        text = path.read_text(encoding="utf-8")
        if path.name in ("GenCases.lean", "Axioms.lean"):
            continue
        namespaces = NAMESPACE.findall(text)
        prefix = namespaces[0] if namespaces else ""
        for match in THEOREM.finditer(text):  # THEOREM is anchored at a line start, so a `private theorem` never matches
            names.append(f"{prefix}.{match.group(1)}" if prefix else match.group(1))
    return names


def parse_axioms(output: str) -> dict[str, set[str]]:
    """{theorem: axioms} from `#print axioms` output: `'name' depends on axioms: [a, b]` or `'name' does not depend on any axioms`."""
    found: dict[str, set[str]] = {}
    # Lean wraps a long axiom list over several lines, and a name may itself hold an apostrophe, so this reads the whole text and ends the name at the first `' depends`.
    for match in re.finditer(r"'([^\n]*?)' depends on axioms: \[(.*?)\]", output, re.S):
        found[match.group(1)] = {item.strip() for item in match.group(2).replace("\n", " ").split(",") if item.strip()}
    for match in re.finditer(r"'([^\n]*?)' does not depend on any axioms", output):
        found[match.group(1)] = set()
    return found


def violations(found: dict[str, set[str]], expected: list[str]) -> list[str]:
    problems = []
    for name in expected:
        if name not in found:
            problems.append(f"{name}: Lean printed nothing for it")
            continue
        extra = found[name] - STANDARD
        if name in ALLOWED_NATIVE:
            extra = {axiom for axiom in extra if axiom not in ALLOWED_EXTRA and not NATIVE_AXIOM.match(axiom)}
        if extra:
            problems.append(f"{name} rests on {sorted(extra)}")
        if "sorryAx" in found[name]:
            problems.append(f"{name} uses sorry")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    names = theorems()
    if "--list" in args:
        print("\n".join(names))
        return 0
    probe = FORMAL / "AxiomProbe.lean"
    probe.write_text("import AetherFormal\n\n" + "\n".join(f"#print axioms {name}" for name in names) + "\n", encoding="utf-8", newline="\n")
    try:
        result = subprocess.run(["lake", "env", "lean", str(probe.name)], cwd=FORMAL, capture_output=True, text=True, timeout=3600)
    finally:
        probe.unlink(missing_ok=True)
    found = parse_axioms(result.stdout)
    problems = violations(found, names)
    for line in problems:
        print(f"axiom check: {line}", file=sys.stderr)
    print(f"axiom check: {len(names)} theorems, {len(problems)} problem(s); extra axioms seen: {sorted({axiom for value in found.values() for axiom in value} - STANDARD)}")
    return 1 if problems or result.returncode not in (0,) else 0


if __name__ == "__main__":
    raise SystemExit(main())
