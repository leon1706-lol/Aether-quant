"""moe/gating.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from moe.gating import EXPERT_NAMES, ExpertGateWeight, build_gating_model_features


def test_four_features_per_expert_in_a_fixed_order_and_a_missing_probability_reads_half():
    weights = [ExpertGateWeight(expert=name, weight=0.25, raw_score=0.0, probability_up=None if name == "bearish" else 0.6, quality_status="ok",
                                quality_multiplier=1.0, gating_eligible=True, regime_alignment=0.5, performance_score=0.1, reason="", magnitude=0.0, volatility=0.0)
               for name in EXPERT_NAMES]
    features = build_gating_model_features({}, 0.5, weights)
    assert features[:4] == [0.6, 1.0, 0.1, 0.5]
    bearish = list(EXPERT_NAMES).index("bearish") * 4
    assert features[bearish] == 0.5
