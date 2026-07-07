import json
from pathlib import Path

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

    state = build_neural_network_state(ml_dir=tmp_path)

    networks = state["networks"]
    assert state["totals"]["total_networks"] == 6
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
