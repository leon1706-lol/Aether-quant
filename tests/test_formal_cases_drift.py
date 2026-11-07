"""Every committed case file was generated from the current Lean specs (`aq prove --regen-cases` after a spec edit)."""

from __future__ import annotations

from pathlib import Path

from aether_quant.formal import load_cases, spec_sha256, targets

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "formal"

EXPECTED_TARGETS = ["book_construction", "book_neutrality", "cost_model", "generation_blend", "generation_glide", "hash_chain", "json_safety", "kill_switch",
                    "order_gate", "position_sizing", "reconciliation", "risk_controls", "sleeve_guard"]


def test_every_target_has_a_case_file():
    assert targets() == EXPECTED_TARGETS


def test_case_files_match_the_current_specs():
    for target in targets():
        data = load_cases(target)
        assert data["cases"], target
        assert data["spec_sha256"] == spec_sha256(FORMAL_ROOT, data["spec_files"]), (
            f"{target}: formal/ changed since its cases were generated - run `aq prove --regen-cases`"
        )
