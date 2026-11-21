"""lab/objectives.py: the ranking objectives' names, the same ones the trainers and the lab's configs accept."""

from __future__ import annotations

from lab import objectives


def test_the_context_objectives_are_ranking_objectives_and_the_trainers_see_the_same_names():
    assert set(objectives.RANKING_OBJECTIVES) >= objectives.CONTEXT_OBJECTIVES
    assert objectives.RANKING_OBJECTIVES[0] == "mse" and len(set(objectives.RANKING_OBJECTIVES)) == len(objectives.RANKING_OBJECTIVES)
    import train

    assert train.RANKING_OBJECTIVES is objectives.RANKING_OBJECTIVES and train.CONTEXT_CLASSES == ("equity", "bond", "forex", "crypto")
