"""Every committed case file was generated from the current Lean specs (`aq prove --regen-cases` after a spec edit)."""

from __future__ import annotations

from pathlib import Path

from aether_quant.formal import load_cases, spec_sha256, targets

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "formal"

EXPECTED_TARGETS = [
    "account_overrides",
    "admission",
    "authorize",
    "auto_rollback",
    "backtest_gate",
    "book_construction",
    "book_guards",
    "book_neutrality",
    "cash_sweep",
    "cost_model",
    "drawdown_guard",
    "dynamic_targets",
    "forex_cap",
    "generation_blend",
    "generation_glide",
    "hash_chain",
    "holdout_once",
    "inverse_vol_share",
    "json_safety",
    "kelly",
    "kill_switch",
    "model_book_guard",
    "multi_asset_rules",
    "no_trade_band",
    "order_gate",
    "paper_loss_guard",
    "position_sizing",
    "premia_caps",
    "rebalance",
    "reconciliation",
    "risk_controls",
    "rl_sizing",
    "session_resolve",
    "sharpe_clauses",
    "sleeve_guard",
    "vol_target",
    "window_index",
]


def test_every_target_has_a_case_file():
    assert targets() == EXPECTED_TARGETS


def test_case_files_match_the_current_specs():
    for target in targets():
        data = load_cases(target)
        assert data["cases"], target
        assert data["spec_sha256"] == spec_sha256(FORMAL_ROOT, data["spec_files"]), (
            f"{target}: formal/ changed since its cases were generated - run `aq prove --regen-cases`"
        )
