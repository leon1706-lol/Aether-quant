"""scripts/check_axioms.py: it finds the theorems, reads Lean's output and fails on anything but the standard axioms (V6.6.4). Lean itself runs on a Codespace."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_axioms as ax  # noqa: E402


def test_every_spec_file_contributes_its_theorems_under_its_namespace():
    names = ax.theorems()
    assert "AetherFormal.Admission.tier_none_never_capital" in names
    assert "AetherFormal.SessionResolve.best_newest" in names
    assert "AetherFormal.HoldoutOnce.second_read_refused" in names
    assert "AetherFormal.OrderGate.observation_never" in names
    assert len(names) >= 150, "the specs hold well over a hundred theorems"
    assert all(name.startswith("AetherFormal.") for name in names)


def test_lean_output_is_parsed_and_only_the_standard_axioms_pass():
    output = """
'AetherFormal.A.t1' depends on axioms: [propext, Classical.choice, Quot.sound]
'AetherFormal.A.t2' does not depend on any axioms
'AetherFormal.A.t3' depends on axioms: [propext, sorryAx]
'AetherFormal.A.t4' depends on axioms: [Lean.ofReduceBool, propext]
'AetherFormal.A.t5' depends on axioms: [myAxiom]
'AetherFormal.A.it's' depends on axioms: [propext]
'AetherFormal.BookNeutrality.counter_net' depends on axioms: [propext, Lean.ofReduceBool,
  AetherFormal.BookNeutrality.counter_net._native.native_decide.ax_1_1]
"""
    found = ax.parse_axioms(output)
    assert found["AetherFormal.A.t2"] == set() and found["AetherFormal.A.t1"] == ax.STANDARD and found["AetherFormal.A.it\'s"] == {"propext"}
    names = ["AetherFormal.A.t1", "AetherFormal.A.t2", "AetherFormal.A.t3", "AetherFormal.A.t4", "AetherFormal.A.t5", "AetherFormal.A.missing", "AetherFormal.BookNeutrality.counter_net"]
    problems = ax.violations(found, names)
    joined = "\n".join(problems)
    assert "t3 rests on ['sorryAx']" in joined and "t3 uses sorry" in joined
    assert "t5 rests on ['myAxiom']" in joined and "missing: Lean printed nothing" in joined
    assert "t1" not in joined and "t2" not in joined, "the standard axioms pass"
    assert "t4 rests on ['Lean.ofReduceBool']" in joined, "compiler trust in a theorem that is not on the list fails"
    assert "counter_net" not in joined, "and on the list, with its own native axiom, it passes"


def test_the_allowed_exception_has_a_reason():
    assert all(reason.strip() for reason in ax.ALLOWED_EXTRA.values())


def _formal(tmp_path):
    spec = tmp_path / "AetherFormal"
    spec.mkdir()
    (spec / "Book.lean").write_text("namespace Book\ntheorem cap_holds : True := trivial\nprivate theorem helper : True := trivial\n", encoding="utf-8")
    (spec / "Plain.lean").write_text("lemma loose : True := trivial\n", encoding="utf-8")
    (spec / "Axioms.lean").write_text("theorem skipped : True := trivial\n", encoding="utf-8")
    return tmp_path


def test_list_and_a_full_check_with_lean_as_a_stand_in(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    formal = _formal(tmp_path)
    monkeypatch.setattr(ax, "FORMAL", formal)
    monkeypatch.setattr(ax, "theorems", lambda root=formal: ["Book.cap_holds", "loose"])
    assert ax.main(["--list"]) == 0 and capsys.readouterr().out.split() == ["Book.cap_holds", "loose"]
    output = "'Book.cap_holds' depends on axioms: [propext]\n'loose' does not depend on any axioms\n"
    monkeypatch.setattr(ax.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=output, returncode=0))
    assert ax.main([]) == 0 and not (formal / "AxiomProbe.lean").exists() and "2 theorems, 0 problem(s)" in capsys.readouterr().out
    monkeypatch.setattr(ax.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="'loose' depends on axioms: [sorryAx]\n", returncode=1))
    assert ax.main([]) == 1 and "axiom check:" in capsys.readouterr().err


def test_theorems_skip_private_ones_and_the_generated_files(tmp_path):
    names = ax.theorems(_formal(tmp_path))
    assert names == ["Book.cap_holds", "loose"]


def test_the_check_runs_as_a_script(monkeypatch, capsys):
    from script_loader import run_script

    assert run_script("check_axioms", ["--list"], monkeypatch) == 0 and capsys.readouterr().out.strip()
