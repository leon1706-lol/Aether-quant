"""evaluation/generation_registry.py: every branch of the owner's admission rule R-ADMIT1."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from evaluation.generation_registry import (
    AdmissionEvidence,
    Generation,
    admitted_to_shadow,
    append_lifecycle,
    cap_lifted,
    lifecycle_is_intact,
    load_registry,
    next_stage,
    save_registry,
    share_cap,
)

BASE = Generation(id="g2", kind="rule", tier="tier2", stage="frozen", born="2026-11-06", procedure_sha256="abc")
FORWARD_PASS = AdmissionEvidence(selection_pass=True, hold_pass=True, forward_ok_sessions=60, no_data_share=0.05, mean_diff_vs_incumbent=0.0001)


@pytest.mark.parametrize("evidence,expected", [
    (AdmissionEvidence(), "frozen"),
    (AdmissionEvidence(selection_pass=True), "frozen"),
    (AdmissionEvidence(hold_pass=True), "frozen"),
    (AdmissionEvidence(selection_pass=True, hold_pass=True), "shadow"),
    (AdmissionEvidence(edge_pass=True), "ramping"),
    (AdmissionEvidence(selection_pass=True, holdouts_spent=True, forward_ok_sessions=251), "frozen"),
    (AdmissionEvidence(selection_pass=True, holdouts_spent=True, forward_ok_sessions=252), "shadow"),
])
def test_entry_to_shadow_or_ramping(evidence, expected):
    assert next_stage(BASE, evidence) == expected


@pytest.mark.parametrize("change,expected", [
    ({}, "ramping"),
    ({"forward_ok_sessions": 59}, "shadow"),
    ({"mean_diff_vs_incumbent": -0.0001}, "shadow"),
    ({"mean_diff_vs_incumbent": None}, "shadow"),
    ({"mean_diff_vs_incumbent": float("nan")}, "shadow"),
    ({"no_data_share": 0.11}, "shadow"),
    ({"guard_tripped": True}, "rejected"),
    ({"decay_state": "dead"}, "rejected"),
    ({"edge_pass": True, "forward_ok_sessions": 0}, "ramping"),
])
def test_shadow_to_a_share_of_the_paper_book(change, expected):
    assert next_stage(replace(BASE, stage="shadow"), replace(FORWARD_PASS, **change)) == expected


@pytest.mark.parametrize("stage", ["active", "ramping", "fading", "winding_down"])
@pytest.mark.parametrize("change", [{"guard_tripped": True}, {"decay_state": "dead"}])
def test_a_generation_on_the_book_retires_on_a_guard_trip_or_death(stage, change):
    assert next_stage(replace(BASE, stage=stage), replace(FORWARD_PASS, **change)) == "retired"


@pytest.mark.parametrize("stage,evidence,expected", [
    ("ramping", AdmissionEvidence(forward_ok_sessions=251), "ramping"),
    ("ramping", AdmissionEvidence(forward_ok_sessions=252), "active"),
    ("ramping", AdmissionEvidence(forward_ok_sessions=300, decay_state="watch"), "ramping"),
    ("active", AdmissionEvidence(score=0.4), "active"),
    ("active", AdmissionEvidence(decay_state="watch", score=0.4), "fading"),
    ("active", AdmissionEvidence(score=-0.1), "fading"),
    ("fading", AdmissionEvidence(decay_state="decaying", score=0.2), "fading"),
    ("fading", AdmissionEvidence(decay_state="watch", score=-0.2), "winding_down"),
    ("fading", AdmissionEvidence(score=0.6), "active"),
    ("winding_down", AdmissionEvidence(decay_state="watch", score=-0.2), "winding_down"),
    ("winding_down", AdmissionEvidence(decay_state="healthy", score=0.5), "fading"),
    ("winding_down", AdmissionEvidence(decay_state="healthy", score=None), "winding_down"),
])
def test_the_stages_between_a_full_share_and_none(stage, evidence, expected):
    assert next_stage(replace(BASE, stage=stage), evidence) == expected


def test_short_of_its_claim_but_still_earning_is_not_the_end():
    assert next_stage(replace(BASE, stage="fading"), AdmissionEvidence(decay_state="decaying", score=0.05)) == "fading"
    assert next_stage(replace(BASE, stage="fading"), AdmissionEvidence(decay_state="decaying", score=0.0)) == "winding_down"


def test_a_stage_moves_one_step_at_a_time():
    assert next_stage(replace(BASE, stage="active"), AdmissionEvidence(decay_state="decaying", score=-1.0)) == "fading"


@pytest.mark.parametrize("stage", ["retired", "rejected"])
def test_nothing_comes_back(stage):
    assert next_stage(replace(BASE, stage=stage), AdmissionEvidence(edge_pass=True, selection_pass=True, hold_pass=True)) == stage


def test_anything_less_gets_no_share():
    for stage in ("candidate", "frozen", "shadow", "retired", "rejected"):
        assert share_cap(replace(BASE, stage=stage), FORWARD_PASS) == 0.0
    assert share_cap(replace(BASE, stage="ramping", tier="none"), FORWARD_PASS) == 0.0


def test_tier_two_is_capped_until_forward_alpha_lifts_it():
    ramping = replace(BASE, stage="ramping")
    assert share_cap(ramping, FORWARD_PASS) == 0.30
    assert share_cap(ramping, replace(FORWARD_PASS, forward_ok_sessions=252, forward_alpha_t=1.99)) == 0.30
    assert share_cap(ramping, replace(FORWARD_PASS, forward_ok_sessions=251, forward_alpha_t=3.0)) == 0.30
    assert share_cap(ramping, replace(FORWARD_PASS, forward_ok_sessions=252, forward_alpha_t=2.0)) == 1.0
    assert share_cap(ramping, replace(FORWARD_PASS, forward_ok_sessions=252, forward_alpha_t=float("nan"))) == 0.30


def test_a_full_pass_and_the_installed_book_hold_everything():
    assert share_cap(replace(BASE, stage="ramping", tier="tier1"), AdmissionEvidence()) == 1.0
    assert share_cap(replace(BASE, stage="active", tier="installed"), AdmissionEvidence()) == 1.0
    assert share_cap(replace(BASE, stage="ramping"), AdmissionEvidence(edge_pass=True)) == 1.0


def test_shadow_needs_selection_first():
    assert not admitted_to_shadow(AdmissionEvidence(hold_pass=True))
    assert not cap_lifted(AdmissionEvidence())


def test_the_registry_round_trips_and_refuses_an_unknown_stage(tmp_path):
    path = tmp_path / "registry.json"
    save_registry(path, {"g2": replace(BASE, vintages=("v1", "v2"))})
    assert load_registry(path)["g2"] == replace(BASE, vintages=("v1", "v2"))
    assert path.read_bytes().endswith(b"\n") and b"\r" not in path.read_bytes()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["generations"][0]["stage"] = "promoted_by_hand"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry(path)


def test_the_lifecycle_log_chains_and_shows_an_edit(tmp_path):
    path = tmp_path / "lifecycle.jsonl"
    append_lifecycle(path, event="seed", payload={"generation": "g1"}, created_at="2026-11-06T00:00:00+00:00")
    append_lifecycle(path, event="stage", payload={"generation": "g1", "to": "active"}, created_at="2026-11-06T00:00:01+00:00")
    assert lifecycle_is_intact(path) == (True, None)
    text = path.read_text(encoding="utf-8").replace('"to": "active"', '"to": "retired"')
    path.write_text(text, encoding="utf-8")
    assert lifecycle_is_intact(path)[0] is False
