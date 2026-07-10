"""Neural-network layer/node/edge state for Aether Quant V2's webui (V2-20).

Reads the JSON-exported weights train.py already produces for the baseline
model and the 4 MoE experts (ml/model_weights.json,
ml/expert_models/<name>/model_weights.json), plus the optional learned
gating blend (ml/gating_model.json, see moe/gating.py's
GATING_MODEL_FEATURE_KEYS/build_gating_model_features()) when
train_gating.py has produced one - and reshapes all of them into a
network-agnostic layer/node/edge summary the webui renders as an
interactive 3D diagram. Pure, read-only - never trains anything, never
touches the binary ml/model.pt checkpoints, only the JSON exports meant for
non-PyTorch consumers (same exports main.py's own _run_exported_model
interpreter reads).

Also reads the 6 optional multitask/sequence networks added in the
multitask/sequence pass: ml/multitask_model.json (baseline_multitask),
ml/expert_models/<name>/multitask_model.json (<name>_multitask, one per
expert) and ml/sequence_model.json (sequence, the Phase 2 causal-TCN
encoder). These use a branching `{"trunk": [...], "heads": {"direction":
[...], "magnitude": [...], "volatility": [...]}}` export shape instead of
the flat `architecture` list the baseline/expert/gating networks use -
_parse_network_export() dispatches between the two shapes automatically.
`sequence`'s trunk also has conv1d_causal layers (in_channels/out_channels
instead of linear's in_features/out_features, and a 3D weight matrix) -
see _flatten()/_weight_stats() below.

The gating network degrades to status="not_trained" (same as any other
network here) until a gating model has actually been trained - see `aq
train --gating-only` or the retraining pipeline's best-effort
train_gating() stage. Before a learned gating model exists, moe/gating.py
still runs its deterministic hardcoded blend at runtime; that fallback
path has no weight matrix and is not itself represented as a network here.

The learned-topology KMeans prototypes (topology/learned_topology.py) are
deliberately excluded - it's cluster centroids, not a layered network, so
there is nothing to lay out as layers/nodes/edges. Its absence is reported
explicitly via `excluded` rather than left silent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

EXPERT_NAMES = ("bullish", "bearish", "sideways", "volatility")

DEFAULT_ML_DIR = Path(__file__).resolve().parent.parent / "ml"

EXCLUDED_NON_NETWORKS = [
    {
        "name": "learned_topology",
        "reason": (
            "KMeans cluster prototype centroids (topology/learned_topology.py), "
            "not a layered network"
        ),
    },
]


@dataclass(frozen=True)
class NetworkLayer:
    index: int
    type: str
    in_features: int | None
    out_features: int | None
    weight_abs_mean: float | None
    weight_abs_max: float | None
    head: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NetworkSummary:
    name: str
    label: str
    role: str
    status: str
    quality_status: str | None
    node_layers: list[int]
    layers: list[NetworkLayer]
    total_layers: int
    total_nodes: int
    total_edges: int
    last_modified: str | None
    heads: dict[str, list[int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["layers"] = [layer.to_dict() for layer in self.layers]
        return payload


def _flatten(value) -> list[float]:
    """Flattens an arbitrarily-nested list of numbers. linear weights are
    2D ([out][in]); conv1d_causal weights are 3D ([out_channels]
    [in_channels][kernel_size]) - this handles both without needing to
    know the layer type in advance."""
    if isinstance(value, list):
        flat: list[float] = []
        for item in value:
            flat.extend(_flatten(item))
        return flat
    return [float(value)]


def _weight_stats(state_dict: dict, weight_key: str) -> tuple[float, float]:
    matrix = state_dict.get(weight_key)
    if not matrix:
        return 0.0, 0.0
    flat = [abs(value) for value in _flatten(matrix)]
    if not flat:
        return 0.0, 0.0
    return sum(flat) / len(flat), max(flat)


# Layer types whose weight is 2D and keyed by in_features/out_features.
_LINEAR_LAYER_TYPES = {"linear"}
# Layer types whose weight is 3D and keyed by in_channels/out_channels.
_CONV_LAYER_TYPES = {"conv1d_causal"}


def _append_layer_specs(
    layer_specs: list[dict],
    state_dict: dict,
    start_index: int,
    head: str | None,
) -> tuple[list[NetworkLayer], list[int]]:
    """Shared per-layer-type dispatch used by both the flat `architecture`
    parse path and the branching `trunk`/`heads` parse path, so a linear or
    conv1d_causal layer is handled identically regardless of which export
    shape it came from."""
    layers: list[NetworkLayer] = []
    node_layers: list[int] = []

    for offset, layer_spec in enumerate(layer_specs):
        layer_type = layer_spec.get("type", "unknown")
        weighted = layer_type in _LINEAR_LAYER_TYPES or layer_type in _CONV_LAYER_TYPES
        if layer_type in _LINEAR_LAYER_TYPES:
            in_features = layer_spec.get("in_features")
            out_features = layer_spec.get("out_features")
        elif layer_type in _CONV_LAYER_TYPES:
            in_features = layer_spec.get("in_channels")
            out_features = layer_spec.get("out_channels")
        else:
            in_features = layer_spec.get("in_features")
            out_features = layer_spec.get("out_features")

        weight_abs_mean = weight_abs_max = None
        if weighted:
            weight_abs_mean, weight_abs_max = _weight_stats(state_dict, layer_spec["weight_key"])
            if not node_layers:
                node_layers.append(int(in_features))
            node_layers.append(int(out_features))

        layers.append(
            NetworkLayer(
                index=start_index + offset,
                type=layer_type,
                in_features=in_features,
                out_features=out_features,
                weight_abs_mean=weight_abs_mean,
                weight_abs_max=weight_abs_max,
                head=head,
            )
        )
    return layers, node_layers


def _parse_flat_network_export(export: dict) -> tuple[list[NetworkLayer], list[int], dict[str, list[int]]]:
    architecture = export.get("architecture", [])
    state_dict = export.get("state_dict", {})
    layers, node_layers = _append_layer_specs(architecture, state_dict, start_index=0, head=None)
    return layers, node_layers, {}


def _parse_branching_network_export(export: dict) -> tuple[list[NetworkLayer], list[int], dict[str, list[int]]]:
    """Parses the multitask/sequence `{"trunk": [...], "heads": {"direction":
    [...], "magnitude": [...], "volatility": [...]}}` export shape - a
    shared trunk feeding 3 independent output heads, instead of one flat
    layer list. Trunk and each head's node_layers are kept separate (a head
    is a branch off the trunk's output, not a continuation of the same
    layer stack) so the webui can render each head as its own labeled
    mini-network sharing the trunk."""
    state_dict = export.get("state_dict", {})
    trunk_specs = export.get("trunk", [])
    head_specs = export.get("heads", {})

    layers, trunk_node_layers = _append_layer_specs(trunk_specs, state_dict, start_index=0, head=None)

    heads_node_layers: dict[str, list[int]] = {}
    next_index = len(layers)
    for head_name, layer_specs in head_specs.items():
        head_layers, head_node_layers = _append_layer_specs(
            layer_specs, state_dict, start_index=next_index, head=head_name
        )
        layers.extend(head_layers)
        heads_node_layers[head_name] = head_node_layers
        next_index += len(head_layers)

    return layers, trunk_node_layers, heads_node_layers


def _parse_network_export(export: dict) -> tuple[list[NetworkLayer], list[int], dict[str, list[int]]]:
    if "trunk" in export or "heads" in export:
        return _parse_branching_network_export(export)
    return _parse_flat_network_export(export)


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _last_modified(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _build_network_summary(
    name: str,
    label: str,
    role: str,
    weights_path: Path,
    quality_status: str | None,
) -> NetworkSummary:
    payload = _load_json(weights_path)
    if payload is None or "export" not in payload:
        return NetworkSummary(
            name=name,
            label=label,
            role=role,
            status="not_trained",
            quality_status=quality_status,
            node_layers=[],
            layers=[],
            total_layers=0,
            total_nodes=0,
            total_edges=0,
            last_modified=None,
            heads={},
        )

    layers, node_layers, heads_node_layers = _parse_network_export(payload["export"])
    total_edges = sum(a * b for a, b in zip(node_layers, node_layers[1:]))
    total_edges += sum(
        a * b for head_layers in heads_node_layers.values() for a, b in zip(head_layers, head_layers[1:])
    )

    return NetworkSummary(
        name=name,
        label=label,
        role=role,
        status="trained",
        quality_status=quality_status,
        node_layers=node_layers,
        layers=layers,
        total_layers=len(node_layers) + sum(len(head_layers) for head_layers in heads_node_layers.values()),
        total_nodes=sum(node_layers) + sum(sum(head_layers) for head_layers in heads_node_layers.values()),
        total_edges=total_edges,
        last_modified=_last_modified(weights_path),
        heads=heads_node_layers,
    )


def build_neural_network_state(ml_dir: Path | None = None) -> dict:
    """Reads ml/model_weights.json + ml/expert_models/*/model_weights.json +
    the optional ml/gating_model.json and reshapes them into a
    network-agnostic layer/node/edge summary. A missing export file
    degrades that one network to status="not_trained" - never raises,
    mirroring main.py's own optional-model loading."""
    ml_dir = ml_dir or DEFAULT_ML_DIR

    expert_metrics = _load_json(ml_dir / "expert_training_metrics.json") or {}
    experts_metrics_block = expert_metrics.get("experts", {})

    networks = [
        _build_network_summary(
            name="baseline",
            label="Baseline Model",
            role="baseline",
            weights_path=ml_dir / "model_weights.json",
            quality_status=None,
        )
    ]

    for expert_name in EXPERT_NAMES:
        quality_gate = experts_metrics_block.get(expert_name, {}).get("quality_gate", {})
        quality_status = quality_gate.get("quality_status")
        networks.append(
            _build_network_summary(
                name=expert_name,
                label=f"{expert_name.capitalize()} Expert",
                role="expert",
                weights_path=ml_dir / "expert_models" / expert_name / "model_weights.json",
                quality_status=quality_status,
            )
        )

    # Learned gating blend (train_gating.py) - optional, same graceful
    # degrade-to-not_trained contract as every other network here. Reuses
    # the webui's existing "learned" badge tone (already used for the
    # topology overlay) once a gating model file is actually present.
    gating_weights_path = ml_dir / "gating_model.json"
    networks.append(
        _build_network_summary(
            name="gating",
            label="Gating Network",
            role="gating",
            weights_path=gating_weights_path,
            quality_status="learned" if gating_weights_path.exists() else None,
        )
    )

    # Multitask (direction + magnitude + volatility) networks - optional,
    # same graceful degrade-to-not_trained contract. Branching trunk/heads
    # export shape (see _parse_branching_network_export()), sharing the
    # exact same file existence check as every other network here.
    networks.append(
        _build_network_summary(
            name="baseline_multitask",
            label="Baseline Multitask",
            role="multitask",
            weights_path=ml_dir / "multitask_model.json",
            quality_status=None,
        )
    )

    for expert_name in EXPERT_NAMES:
        quality_gate = experts_metrics_block.get(expert_name, {}).get("quality_gate", {})
        quality_status = quality_gate.get("quality_status")
        networks.append(
            _build_network_summary(
                name=f"{expert_name}_multitask",
                label=f"{expert_name.capitalize()} Expert Multitask",
                role="expert_multitask",
                weights_path=ml_dir / "expert_models" / expert_name / "multitask_model.json",
                quality_status=quality_status,
            )
        )

    # Phase 2 sequence encoder (causal TCN) - optional, informational only
    # in main.py (never feeds gating/analyzer/sizing), but still a real
    # trained network worth visualizing here like every other one.
    networks.append(
        _build_network_summary(
            name="sequence",
            label="Sequence Encoder (Phase 2)",
            role="sequence",
            weights_path=ml_dir / "sequence_model.json",
            quality_status=None,
        )
    )

    totals = {
        "total_networks": len(networks),
        "total_layers": sum(network.total_layers for network in networks),
        "total_nodes": sum(network.total_nodes for network in networks),
        "total_edges": sum(network.total_edges for network in networks),
        "trained_count": sum(1 for network in networks if network.status == "trained"),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "networks": [network.to_dict() for network in networks],
        "totals": totals,
        "excluded": EXCLUDED_NON_NETWORKS,
    }
