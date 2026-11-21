"""lab/architectures.py: the production networks build with their heads, and their exports run in the numpy forward pass.
(The trainers' own files, test_train_multitask*.py and test_train_sequence*.py, test them in depth through train.py.)"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from inference.exported_model import run_exported_model, run_exported_multitask_model, run_exported_sequence_multitask_model  # noqa: E402
from lab import architectures as arch  # noqa: E402


def test_the_networks_are_the_ones_train_py_names():
    import train

    for name in ("AetherNet", "AetherNetMultiTaskHorizons", "AetherNetSequenceMultiTaskHorizons", "export_state_dict", "horizon_head_specs"):
        assert getattr(train, name) is getattr(arch, name)


def test_each_network_exports_to_the_same_numbers_the_numpy_pass_computes():
    torch.manual_seed(0)
    rows = torch.randn(3, 5)
    baseline = arch.AetherNet(input_dim=5, hidden_layers=[4], dropout=0.0).eval()
    export = {"export": {"architecture": arch.export_architecture(baseline), "state_dict": arch.export_state_dict(baseline)}}
    assert run_exported_model(export, rows[0].tolist()) == pytest.approx(float(torch.sigmoid(baseline(rows[:1]))[0]), abs=1e-5), "the export ends in the sigmoid"

    multi = arch.AetherNetMultiTaskHorizons(input_dim=5, hidden_layers=[4], dropout=0.0).eval()
    outputs = multi(rows)
    assert {"rank_20d", "direction_20d", "rank_5d"} <= set(outputs)
    export = {"export": arch.export_multitask_horizons_architecture(multi) | {"state_dict": arch.export_state_dict(multi)}}
    assert run_exported_multitask_model(export, rows[0].tolist())["rank_20d"] == pytest.approx(float(outputs["rank_20d"][0]), abs=1e-5)

    sequence = arch.AetherNetSequenceMultiTaskHorizons(input_dim=5, channels=[4], kernel_size=2, dropout=0.0).eval()
    windows = torch.randn(2, 6, 5)
    scores = sequence(windows)["rank_20d"]
    export = {"export": arch.export_sequence_multitask_horizons_architecture(sequence) | {"state_dict": arch.export_state_dict(sequence)}}
    assert run_exported_sequence_multitask_model(export, windows[0].tolist())["rank_20d"] == pytest.approx(float(scores[0]), abs=1e-5)


def test_head_specs_and_building_blocks():
    config = arch.resolve_horizon_head_config({})
    specs = arch.horizon_head_specs(config)
    assert "rank_20d" in specs and arch.enabled_extra_heads(config) == ()
    assert isinstance(arch.build_activation("relu"), torch.nn.ReLU) and arch.build_normalization("none", 4) is None
    assert np.isfinite(arch.AetherNetMultiTask(input_dim=3, hidden_layers=[2], dropout=0.0)(torch.zeros(1, 3))[0].detach().numpy()).all()
