import json
from pathlib import Path

import pytest

from monitoring.neural_network_state import EXCLUDED_NON_NETWORKS, EXPERT_NAMES, build_neural_network_state


def _write_model_export(path: Path, node_layers: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    architecture = []
    state_dict = {}
    for index, (in_features, out_features) in enumerate(zip(node_layers, node_layers[1:])):
        weight_key = f"network.{index}.weight"
        bias_key = f"network.{index}.bias"
        architecture.append(
            {
                "type": "linear",
                "weight_key": weight_key,
                "bias_key": bias_key,
                "in_features": in_features,
                "out_features": out_features,
            }
        )
        state_dict[weight_key] = [[0.1 * (i + j) for j in range(in_features)] for i in range(out_features)]
        state_dict[bias_key] = [0.0] * out_features
    architecture.append({"type": "sigmoid"})

    path.write_text(json.dumps({"export": {"architecture": architecture, "state_dict": state_dict}}), encoding="utf-8")


def _write_branching_model_export(
    path: Path,
    trunk_node_layers: list[int],
    heads: dict[str, list[int]],
    trunk_conv: bool = False,
) -> None:
    """Writes a {"trunk": [...], "heads": {...}} export - the shape
    train.py::export_multitask_architecture()/export_sequence_multitask_architecture()
    produce for the baseline/expert multitask heads and the Phase 2
    sequence encoder, as opposed to _write_model_export()'s flat
    `architecture` shape. `trunk_conv=True` writes the trunk's first layer
    as a conv1d_causal layer (3D weight matrix, in_channels/out_channels)
    instead of linear, to exercise the sequence-model parsing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state_dict: dict = {}

    def _layer_specs(node_layers: list[int], prefix: str, use_conv_first: bool) -> list[dict]:
        specs = []
        for index, (in_features, out_features) in enumerate(zip(node_layers, node_layers[1:])):
            weight_key = f"{prefix}.{index}.weight"
            bias_key = f"{prefix}.{index}.bias"
            if use_conv_first and index == 0:
                kernel_size = 3
                specs.append(
                    {
                        "type": "conv1d_causal",
                        "weight_key": weight_key,
                        "bias_key": bias_key,
                        "in_channels": in_features,
                        "out_channels": out_features,
                        "kernel_size": kernel_size,
                        "dilation": 1,
                    }
                )
                state_dict[weight_key] = [
                    [[0.1 * (o + i + k) for k in range(kernel_size)] for i in range(in_features)]
                    for o in range(out_features)
                ]
            else:
                specs.append(
                    {
                        "type": "linear",
                        "weight_key": weight_key,
                        "bias_key": bias_key,
                        "in_features": in_features,
                        "out_features": out_features,
                    }
                )
                state_dict[weight_key] = [[0.1 * (i + j) for j in range(in_features)] for i in range(out_features)]
            state_dict[bias_key] = [0.0] * out_features
        return specs

    trunk_specs = _layer_specs(trunk_node_layers, "trunk", use_conv_first=trunk_conv)
    heads_specs = {}
    for head_name, head_node_layers in heads.items():
        full_head_layers = [trunk_node_layers[-1]] + head_node_layers
        heads_specs[head_name] = _layer_specs(full_head_layers, f"heads.{head_name}", use_conv_first=False)
        heads_specs[head_name].append({"type": "sigmoid" if head_name == "direction" else "softplus"})

    path.write_text(
        json.dumps({"export": {"trunk": trunk_specs, "heads": heads_specs, "state_dict": state_dict}}),
        encoding="utf-8",
    )


def _write_expert_metrics(ml_dir: Path, quality_by_expert: dict[str, str]) -> None:
    experts = {
        name: {"quality_gate": {"quality_status": status, "gating_eligible": status != "disabled_for_gating"}}
        for name, status in quality_by_expert.items()
    }
    (ml_dir / "expert_training_metrics.json").write_text(json.dumps({"experts": experts}), encoding="utf-8")


def test_baseline_layer_node_edge_counts(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])

    state = build_neural_network_state(ml_dir=tmp_path)

    baseline = next(n for n in state["networks"] if n["name"] == "baseline")
    assert baseline["status"] == "trained"
    assert baseline["node_layers"] == [20, 64, 32, 1]
    assert baseline["total_layers"] == 4
    assert baseline["total_nodes"] == 20 + 64 + 32 + 1
    assert baseline["total_edges"] == 20 * 64 + 64 * 32 + 32 * 1


def test_missing_expert_file_degrades_to_not_trained_never_crashes(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    # No expert_models/ directory at all - all 4 experts missing.

    state = build_neural_network_state(ml_dir=tmp_path)

    expert_names = {n["name"] for n in state["networks"] if n["role"] == "expert"}
    assert expert_names == set(EXPERT_NAMES)
    for network in state["networks"]:
        if network["role"] == "expert":
            assert network["status"] == "not_trained"
            assert network["total_layers"] == 0
            assert network["total_nodes"] == 0
            assert network["total_edges"] == 0


def test_expert_quality_status_flows_through(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    for expert_name in EXPERT_NAMES:
        _write_model_export(tmp_path / "expert_models" / expert_name / "model_weights.json", [20, 24, 1])
    _write_expert_metrics(
        tmp_path,
        {"bullish": "watchlist", "bearish": "stable", "sideways": "stable", "volatility": "disabled_for_gating"},
    )

    state = build_neural_network_state(ml_dir=tmp_path)

    quality_by_name = {n["name"]: n["quality_status"] for n in state["networks"]}
    assert quality_by_name["bullish"] == "watchlist"
    assert quality_by_name["bearish"] == "stable"
    assert quality_by_name["volatility"] == "disabled_for_gating"
    assert quality_by_name["baseline"] is None


def test_totals_sum_across_all_present_networks(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    for expert_name in EXPERT_NAMES:
        _write_model_export(tmp_path / "expert_models" / expert_name / "model_weights.json", [20, 24, 1])
    _write_model_export(tmp_path / "gating_model.json", [26, 16, 1])
    # No multitask/sequence exports written - those 6 networks degrade to
    # not_trained, still counted in total_networks (12) but not trained_count.

    state = build_neural_network_state(ml_dir=tmp_path)

    networks = state["networks"]
    assert state["totals"]["total_networks"] == 12
    assert state["totals"]["trained_count"] == 6
    assert state["totals"]["total_layers"] == sum(n["total_layers"] for n in networks)
    assert state["totals"]["total_nodes"] == sum(n["total_nodes"] for n in networks)
    assert state["totals"]["total_edges"] == sum(n["total_edges"] for n in networks)


def test_learned_topology_is_explicitly_excluded_but_gating_is_not(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])

    state = build_neural_network_state(ml_dir=tmp_path)

    excluded_names = {entry["name"] for entry in state["excluded"]}
    assert excluded_names == {"learned_topology"}
    assert state["excluded"] == EXCLUDED_NON_NETWORKS
    network_names = {n["name"] for n in state["networks"]}
    assert "learned_topology" not in network_names
    assert "gating" in network_names


def test_gating_network_reports_not_trained_when_no_model_file(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    # No gating_model.json written - train_gating.py never ran yet.

    state = build_neural_network_state(ml_dir=tmp_path)

    gating = next(n for n in state["networks"] if n["name"] == "gating")
    assert gating["role"] == "gating"
    assert gating["status"] == "not_trained"
    assert gating["quality_status"] is None
    assert gating["total_layers"] == 0


def test_gating_network_reports_learned_quality_status_when_model_present(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    _write_model_export(tmp_path / "gating_model.json", [26, 16, 1])

    state = build_neural_network_state(ml_dir=tmp_path)

    gating = next(n for n in state["networks"] if n["name"] == "gating")
    assert gating["status"] == "trained"
    assert gating["quality_status"] == "learned"
    assert gating["node_layers"] == [26, 16, 1]
    assert gating["total_layers"] == 3
    assert gating["total_nodes"] == 26 + 16 + 1
    assert gating["total_edges"] == 26 * 16 + 16 * 1


def test_missing_baseline_also_degrades_gracefully(tmp_path):
    # Completely empty ml_dir - nothing trained yet anywhere.
    state = build_neural_network_state(ml_dir=tmp_path)

    baseline = next(n for n in state["networks"] if n["name"] == "baseline")
    assert baseline["status"] == "not_trained"
    assert state["totals"]["trained_count"] == 0


def test_baseline_multitask_network_parses_branching_shape(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    _write_branching_model_export(
        tmp_path / "multitask_model.json",
        trunk_node_layers=[20, 64, 32],
        heads={"direction": [1], "magnitude": [1], "volatility": [1]},
    )

    state = build_neural_network_state(ml_dir=tmp_path)

    multitask = next(n for n in state["networks"] if n["name"] == "baseline_multitask")
    assert multitask["status"] == "trained"
    assert multitask["role"] == "multitask"
    assert multitask["node_layers"] == [20, 64, 32]
    assert set(multitask["heads"].keys()) == {"direction", "magnitude", "volatility"}
    for head_layers in multitask["heads"].values():
        assert head_layers == [32, 1]
    # Every linear layer (trunk + all 3 heads) got real weight stats.
    weighted_layers = [layer for layer in multitask["layers"] if layer["weight_abs_mean"] is not None]
    assert len(weighted_layers) == 2 + 3  # 2 trunk linears + 1 linear per head
    # Head labels correctly distinguish trunk layers (head=None) from head layers.
    trunk_layers = [layer for layer in multitask["layers"] if layer["head"] is None]
    assert len(trunk_layers) == 2
    direction_layers = [layer for layer in multitask["layers"] if layer["head"] == "direction"]
    assert len(direction_layers) == 2  # 1 linear + 1 sigmoid


def test_expert_multitask_networks_reuse_expert_quality_status(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    for expert_name in EXPERT_NAMES:
        _write_branching_model_export(
            tmp_path / "expert_models" / expert_name / "multitask_model.json",
            trunk_node_layers=[20, 24],
            heads={"direction": [1], "magnitude": [1], "volatility": [1]},
        )
    _write_expert_metrics(
        tmp_path,
        {"bullish": "watchlist", "bearish": "stable", "sideways": "stable", "volatility": "disabled_for_gating"},
    )

    state = build_neural_network_state(ml_dir=tmp_path)

    quality_by_name = {n["name"]: n["quality_status"] for n in state["networks"]}
    assert quality_by_name["bullish_multitask"] == "watchlist"
    assert quality_by_name["volatility_multitask"] == "disabled_for_gating"
    expert_multitask_names = {f"{expert_name}_multitask" for expert_name in EXPERT_NAMES}
    roles = {n["name"]: n["role"] for n in state["networks"] if n["name"] in expert_multitask_names}
    assert all(role == "expert_multitask" for role in roles.values())


def test_sequence_network_conv1d_weight_flattening_does_not_crash(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    _write_branching_model_export(
        tmp_path / "sequence_model.json",
        trunk_node_layers=[8, 4],
        heads={"direction": [1], "magnitude": [1], "volatility": [1]},
        trunk_conv=True,
    )

    state = build_neural_network_state(ml_dir=tmp_path)

    sequence = next(n for n in state["networks"] if n["name"] == "sequence")
    assert sequence["status"] == "trained"
    assert sequence["role"] == "sequence"
    conv_layer = next(layer for layer in sequence["layers"] if layer["type"] == "conv1d_causal")
    assert conv_layer["in_features"] == 8
    assert conv_layer["out_features"] == 4
    # Independently hand-computed against _write_branching_model_export's
    # own conv1d_causal weight formula (0.1 * (o + i + k), o in range(4),
    # i in range(8), k in range(3)) - proves the recursive 3D-list flatten
    # in _weight_stats()/_flatten() produces the correct mean/max, not just
    # "doesn't crash".
    expected_values = [0.1 * (o + i + k) for o in range(4) for i in range(8) for k in range(3)]
    expected_mean = sum(expected_values) / len(expected_values)
    expected_max = max(expected_values)
    assert conv_layer["weight_abs_mean"] == pytest.approx(expected_mean)
    assert conv_layer["weight_abs_max"] == pytest.approx(expected_max)


def test_missing_new_networks_degrade_to_not_trained(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    # No multitask/sequence exports written anywhere.

    state = build_neural_network_state(ml_dir=tmp_path)

    new_roles = {"multitask", "expert_multitask", "sequence"}
    new_networks = [n for n in state["networks"] if n["role"] in new_roles]
    assert len(new_networks) == 6  # baseline_multitask + 4 expert_multitask + sequence
    for network in new_networks:
        assert network["status"] == "not_trained"
        assert network["total_layers"] == 0
        assert network["heads"] == {}


def _write_horizon_training_metrics(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "backtest": {
            "direction_5d": {"mcc": 0.02},
            "direction_20d": {"mcc": -0.01},
            "rank_5d": {"mae": 0.25},
            "rank_5d_ic": {"mean_ic": 0.035, "std_ic": 0.33, "t_stat": 2.5, "num_dates": 561},
            "rank_20d": {"mae": 0.24},
            "rank_20d_ic": {"mean_ic": 0.066, "std_ic": 0.32, "t_stat": 4.85, "num_dates": 546},
            "rank_20d_ranking_quality": {
                "quality_status": "promotable",
                "promotion_eligible": True,
                "failures": [],
                "near_misses": [],
                "observed": {
                    "non_overlapping_t_stat": 2.52,
                    "non_overlapping_mean_ic": 0.066,
                    "bootstrap_ci_lower_bound": 0.035,
                    "bootstrap_ci_upper_bound": 0.308,
                    "num_eras": 12,
                    "num_opposite_sign_eras": 0,
                },
            },
        },
        "magnitude_quality": {"quality_status": "stable"},
        "volatility_quality": {"quality_status": "stable"},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_baseline_multitask_network_reports_horizon_mcc_and_rank_ic(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    _write_branching_model_export(
        tmp_path / "multitask_model.json",
        trunk_node_layers=[20, 64, 32],
        heads={"direction": [1], "magnitude": [1], "volatility": [1]},
    )
    _write_horizon_training_metrics(tmp_path / "multitask_training_metrics.json")

    state = build_neural_network_state(ml_dir=tmp_path)

    multitask = next(n for n in state["networks"] if n["name"] == "baseline_multitask")
    assert multitask["horizon_mcc"] == {"direction_5d": 0.02, "direction_20d": -0.01}
    assert multitask["rank_ic"]["rank_5d"]["mean_ic"] == pytest.approx(0.035)
    assert multitask["rank_ic"]["rank_20d"]["t_stat"] == pytest.approx(4.85)
    assert multitask["ranking_quality"]["rank_20d"]["quality_status"] == "promotable"
    assert multitask["ranking_quality"]["rank_20d"]["observed"]["num_eras"] == 12
    assert multitask["ranking_quality"]["rank_5d"] is None
    assert multitask["regression_quality"] == {"magnitude": "stable", "volatility": "stable"}


def test_sequence_network_reports_horizon_mcc_and_rank_ic(tmp_path):
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    _write_branching_model_export(
        tmp_path / "sequence_model.json",
        trunk_node_layers=[8, 4],
        heads={"direction": [1], "magnitude": [1], "volatility": [1]},
        trunk_conv=True,
    )
    _write_horizon_training_metrics(tmp_path / "sequence_training_metrics.json")

    state = build_neural_network_state(ml_dir=tmp_path)

    sequence = next(n for n in state["networks"] if n["name"] == "sequence")
    assert sequence["horizon_mcc"] == {"direction_5d": 0.02, "direction_20d": -0.01}
    assert sequence["rank_ic"]["rank_5d"]["num_dates"] == 561


def test_horizon_evaluation_fields_are_none_when_metrics_file_missing():
    from monitoring.neural_network_state import _extract_horizon_evaluation_summary

    result = _extract_horizon_evaluation_summary(None)

    assert result == {"horizon_mcc": None, "rank_ic": None, "ranking_quality": None, "regression_quality": None}


def test_horizon_evaluation_fields_are_none_for_pre_phase3_metrics_shape():
    # An older metrics file (before Phase 3/4 heads existed) has a
    # "backtest" block but no direction_5d/rank_5d keys at all - must
    # degrade to None, not KeyError or a dict of Nones treated as "present".
    from monitoring.neural_network_state import _extract_horizon_evaluation_summary

    old_shape_metrics = {
        "backtest": {"direction": {"mcc": 0.03}, "magnitude": {"mae": 0.03}, "volatility": {"mae": 0.02}},
    }

    result = _extract_horizon_evaluation_summary(old_shape_metrics)

    assert result == {"horizon_mcc": None, "rank_ic": None, "ranking_quality": None, "regression_quality": None}


def test_expert_multitask_networks_never_get_horizon_evaluation_fields(tmp_path):
    # Experts stay 1d-direction-only by design (see development/Changelog.md) -
    # even if a stray multitask_training_metrics.json-shaped file existed
    # for an expert (it never does in practice), build_neural_network_state()
    # never passes training_metrics for expert_multitask networks.
    _write_model_export(tmp_path / "model_weights.json", [20, 64, 32, 1])
    for expert_name in EXPERT_NAMES:
        _write_branching_model_export(
            tmp_path / "expert_models" / expert_name / "multitask_model.json",
            trunk_node_layers=[20, 24],
            heads={"direction": [1], "magnitude": [1], "volatility": [1]},
        )

    state = build_neural_network_state(ml_dir=tmp_path)

    expert_multitask_networks = [n for n in state["networks"] if n["role"] == "expert_multitask"]
    assert len(expert_multitask_networks) == 4
    for network in expert_multitask_networks:
        assert network["horizon_mcc"] is None
        assert network["rank_ic"] is None
        assert network["ranking_quality"] is None
        assert network["regression_quality"] is None
