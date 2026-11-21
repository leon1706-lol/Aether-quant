"""lab/training_utils.py: seeding, the device, early stopping and whole-date batches. (The trainers' deeper cases live in
test_train_optimizer_and_swa.py, test_train_threshold_and_early_stop.py and test_train_cross_sectional_batching.py.)"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from lab import training_utils as tu  # noqa: E402


def test_the_device_is_cpu_unless_cuda_is_there_and_asked_for(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert tu.select_device("cpu") == "cpu" and tu.select_device("auto") == "cpu"
    with pytest.raises(RuntimeError, match="no CUDA device"):
        tu.select_device("cuda")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert tu.select_device("auto") == "cuda" and tu.select_device("cuda") == "cuda" and tu.select_device("cpu") == "cpu"


def test_seeding_repeats_and_batches_hold_whole_dates():
    tu.set_seed(3)
    first = torch.rand(2)
    tu.set_seed(3)
    assert torch.equal(first, torch.rand(2))
    dates = np.array(["a", "a", "b", "b", "c"])
    batches = tu.build_cross_sectional_date_batches(dates, batch_dates=1, min_group_size=2, shuffle=False, seed=0)
    assert [sorted(set(dates[batch])) for batch in batches] == [["a"], ["b"]], "a date with one name is dropped"
    assert tu.build_date_group_ids(np.array(["x", "x", "y"])).tolist() == [0, 0, 1]
    assert tu.smoothed_metric([{"ic": 0.1}, {"ic": None}, {"ic": 0.3}], "ic", 2) == pytest.approx(0.2) and tu.smoothed_metric([], "ic", 1) is None
    assert tu.is_new_best_epoch(0.2, 0.1, 5) and not tu.is_new_best_epoch(0.2, 0.1, 1)
