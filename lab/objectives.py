"""The names of the ranking objectives the trainers accept (torch-free, so configs validate without torch)."""

from __future__ import annotations

CONTEXT_OBJECTIVES = frozenset({"ls_sharpe", "class_balanced", "cost_aware"})  # objectives that read the row context (asset class, ticker, forward return)
RANKING_OBJECTIVES = ("mse", "soft_spearman", "listnet", "ic_pearson", "ls_sharpe", "class_balanced", "cost_aware")
CONTEXT_CLASSES = ("equity", "bond", "forex", "crypto")
