"""lab/losses.py: the ranking objectives reward the right order, and the dispatcher reaches each one. (The trainers' deeper
cases live in test_train_ranking_loss.py, through train.py's re-exports.)"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from lab import losses  # noqa: E402


@pytest.mark.parametrize("objective", ["mse", "soft_spearman", "listnet", "ic_pearson"])
def test_each_objective_prefers_the_true_order(objective):
    target = torch.tensor([0.1, 0.4, 0.6, 0.9, 0.2, 0.8])
    groups = torch.tensor([0, 0, 0, 1, 1, 1])
    config = {"objective": objective, "temperature": 0.1}
    right = losses.compute_cross_sectional_ranking_loss(target * 2.0, target, groups, config)
    wrong = losses.compute_cross_sectional_ranking_loss(-target * 2.0, target, groups, config)
    assert float(right) < float(wrong) and torch.isfinite(right)


def test_the_masked_losses_ignore_what_the_mask_hides():
    predictions, targets = torch.tensor([0.0, 1.0]), torch.tensor([0.0, 100.0])
    assert float(losses.masked_mse_loss(predictions, targets, torch.tensor([True, False]))) == 0.0
    assert float(losses.masked_bce_with_logits_loss(torch.tensor([10.0, -10.0]), torch.tensor([1.0, 0.0]), torch.tensor([True, True]))) < 1e-3
    assert losses.RANKING_OBJECTIVES[0] == "mse"
