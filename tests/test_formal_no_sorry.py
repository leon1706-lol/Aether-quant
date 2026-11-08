"""The Lean proofs are complete and listed (V6.6.4). `lake build` treats `sorry` as a warning, so nothing but this scan stood between an unfinished proof and the README's claim (infrastructure.md
said CI ran `aq prove --check-sorry`; it did not). This runs in the suite on every platform, needs no Lean, and checks the files the build never reads:

- no `sorry` or `admit` in any spec;
- every spec is imported by `AetherFormal.lean` (a file nothing imports is never built, so its theorems are never checked);
- every spec has its row in `formal/README.md`'s theorem index, and a case generator or a stated reason.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "formal"
SPECS = sorted(path.stem for path in (FORMAL / "AetherFormal").glob("*.lean") if path.stem not in ("GenCases",))
# Specs with proofs but no differential cases: `Real` restates headline theorems at the reals.
NO_CASES = {"Real"}


def test_no_spec_contains_sorry_or_admit():
    sys.path.insert(0, str(ROOT))
    import aq_cli

    assert aq_cli._formal_sorry_hits() == []


def test_every_spec_is_imported_by_the_library_file_so_it_is_built():
    library = (FORMAL / "AetherFormal.lean").read_text(encoding="utf-8")
    imported = set(re.findall(r"^import AetherFormal\.(\w+)", library, re.M))
    assert set(SPECS) <= imported, f"never built: {sorted(set(SPECS) - imported)}"
    cases = (FORMAL / "AetherFormal" / "GenCases.lean").read_text(encoding="utf-8")
    imported_by_cases = set(re.findall(r"^import AetherFormal\.(\w+)", cases, re.M))
    assert set(SPECS) - NO_CASES <= imported_by_cases | {"GenCases"}, f"no case generator imports: {sorted(set(SPECS) - NO_CASES - imported_by_cases)}"


def test_every_spec_has_a_row_in_the_theorem_index():
    readme = (FORMAL / "README.md").read_text(encoding="utf-8")
    missing = [name for name in SPECS if f"`{name}.lean`" not in readme]
    assert not missing, f"formal/README.md's theorem index lacks {missing}"


def test_every_target_with_cases_has_a_differential_test():
    for target in (path.stem for path in (ROOT / "aether_quant" / "_formal_cases").glob("*.json")):
        assert (ROOT / "tests" / f"test_formal_differential_{target}.py").exists(), target


def test_the_ci_workflow_builds_the_proofs_and_checks_axioms():
    text = (ROOT / ".github" / "workflows" / "formal.yml").read_text(encoding="utf-8")
    for needed in ("lake build", "check-sorry", "check_axioms.py", "regen-cases", "git diff --exit-code"):
        assert needed in text, needed
