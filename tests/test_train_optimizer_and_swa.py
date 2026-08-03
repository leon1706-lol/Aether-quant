"""Tests for train.py's V5.1 Phase 3 (items 10, 11) optimizer/schedule/SWA/
smoothing helpers: build_optimizer(), build_lr_scheduler(), swa_accumulate(),
swa_finalize(), smoothed_metric()."""

import pytest
import torch
import torch.nn as nn

from train import build_lr_scheduler, build_optimizer, smoothed_metric, swa_accumulate, swa_finalize


def _tiny_model() -> nn.Module:
    return nn.Linear(2, 1)


# ---------------------------------------------------------------------------
# build_optimizer
# ---------------------------------------------------------------------------


def test_build_optimizer_defaults_to_adam():
    optimizer = build_optimizer(_tiny_model(), {})
    assert isinstance(optimizer, torch.optim.Adam)
    assert not isinstance(optimizer, torch.optim.AdamW)


def test_build_optimizer_adamw_when_configured():
    optimizer = build_optimizer(_tiny_model(), {"optimizer": "adamw"})
    assert isinstance(optimizer, torch.optim.AdamW)


def test_build_optimizer_unknown_value_falls_back_to_adam():
    optimizer = build_optimizer(_tiny_model(), {"optimizer": "not_a_real_optimizer"})
    assert isinstance(optimizer, torch.optim.Adam)
    assert not isinstance(optimizer, torch.optim.AdamW)


def test_build_optimizer_reads_learning_rate_and_weight_decay():
    optimizer = build_optimizer(_tiny_model(), {"learning_rate": 0.01, "weight_decay": 0.5})
    assert optimizer.param_groups[0]["lr"] == 0.01
    assert optimizer.param_groups[0]["weight_decay"] == 0.5


# ---------------------------------------------------------------------------
# build_lr_scheduler
# ---------------------------------------------------------------------------


def test_build_lr_scheduler_defaults_to_none():
    optimizer = build_optimizer(_tiny_model(), {"learning_rate": 0.01})
    scheduler = build_lr_scheduler(optimizer, {}, max_epochs=10)
    assert scheduler is None


def test_build_lr_scheduler_cosine_decreases_monotonically_to_min_factor():
    learning_rate = 0.01
    lr_min_factor = 0.1
    max_epochs = 10
    optimizer = build_optimizer(_tiny_model(), {"learning_rate": learning_rate})
    scheduler = build_lr_scheduler(
        optimizer, {"lr_schedule": "cosine", "lr_min_factor": lr_min_factor}, max_epochs=max_epochs
    )
    assert scheduler is not None

    observed_lrs = [optimizer.param_groups[0]["lr"]]
    for _ in range(max_epochs):
        scheduler.step()
        observed_lrs.append(optimizer.param_groups[0]["lr"])

    for earlier, later in zip(observed_lrs, observed_lrs[1:]):
        assert later <= earlier + 1e-12

    assert observed_lrs[-1] == pytest.approx(learning_rate * lr_min_factor, abs=1e-4)


def test_build_lr_scheduler_unknown_value_returns_none():
    optimizer = build_optimizer(_tiny_model(), {})
    scheduler = build_lr_scheduler(optimizer, {"lr_schedule": "not_a_real_schedule"}, max_epochs=10)
    assert scheduler is None


# ---------------------------------------------------------------------------
# swa_accumulate / swa_finalize
# ---------------------------------------------------------------------------


def test_swa_accumulate_first_call_seeds_with_an_exact_copy():
    state = {"weight": torch.tensor([1.0, 2.0, 3.0])}
    averaged, count = swa_accumulate(None, state, count=0)

    assert count == 1
    assert torch.equal(averaged["weight"], state["weight"])
    # Must be a COPY, not the same tensor object - mutating the original
    # afterward must not silently corrupt the accumulator.
    state["weight"][0] = 999.0
    assert averaged["weight"][0].item() == 1.0


def test_swa_accumulate_identical_states_is_a_noop():
    state = {"weight": torch.tensor([1.0, 2.0, 3.0])}
    averaged, count = swa_accumulate(None, state, count=0)
    averaged, count = swa_accumulate(averaged, state, count)

    assert count == 2
    assert torch.equal(averaged["weight"], state["weight"])


def test_swa_accumulate_two_different_states_is_exact_elementwise_mean():
    state_a = {"weight": torch.tensor([0.0, 10.0])}
    state_b = {"weight": torch.tensor([4.0, 20.0])}

    averaged, count = swa_accumulate(None, state_a, count=0)
    averaged, count = swa_accumulate(averaged, state_b, count)

    assert count == 2
    assert torch.allclose(averaged["weight"], torch.tensor([2.0, 15.0]))


def test_swa_accumulate_three_states_matches_running_mean():
    states = [{"weight": torch.tensor([float(value)])} for value in (1.0, 2.0, 9.0)]
    averaged = None
    count = 0
    for state in states:
        averaged, count = swa_accumulate(averaged, state, count)

    assert count == 3
    assert averaged["weight"].item() == pytest.approx((1.0 + 2.0 + 9.0) / 3.0)


def test_swa_finalize_is_a_passthrough():
    state = {"weight": torch.tensor([1.0, 2.0])}
    assert swa_finalize(state) is state


# ---------------------------------------------------------------------------
# smoothed_metric
# ---------------------------------------------------------------------------


def test_smoothed_metric_window_1_returns_raw_latest_value():
    history = [{"metric": 0.1}, {"metric": 0.2}, {"metric": 0.9}]
    assert smoothed_metric(history, "metric", window=1) == pytest.approx(0.9)


def test_smoothed_metric_averages_last_n_values():
    history = [{"metric": 0.1}, {"metric": 0.2}, {"metric": 0.3}]
    assert smoothed_metric(history, "metric", window=2) == pytest.approx(0.25)


def test_smoothed_metric_window_larger_than_history_averages_everything_available():
    history = [{"metric": 1.0}, {"metric": 3.0}]
    assert smoothed_metric(history, "metric", window=10) == pytest.approx(2.0)


def test_smoothed_metric_ignores_entries_missing_the_key():
    history = [{"other": 1.0}, {"metric": 4.0}, {"metric": 6.0}]
    assert smoothed_metric(history, "metric", window=5) == pytest.approx(5.0)


def test_smoothed_metric_ignores_none_values():
    history = [{"metric": None}, {"metric": 8.0}]
    assert smoothed_metric(history, "metric", window=5) == pytest.approx(8.0)


def test_smoothed_metric_returns_none_when_key_never_present():
    history = [{"other": 1.0}, {"other": 2.0}]
    assert smoothed_metric(history, "metric", window=5) is None


def test_smoothed_metric_empty_history_returns_none():
    assert smoothed_metric([], "metric", window=5) is None
