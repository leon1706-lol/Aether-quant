"""The production networks (moved unchanged from train.py in V6.7.1 so the library can build and export them):
the baseline `AetherNet`, the multitask and multi-horizon heads, the causal-TCN sequence encoders, their head specs,
and the JSON exporters the numpy forward pass reads. `train.py` re-exports every name.
"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn


class AetherNet(nn.Module):
    """The baseline feed-forward network: hidden layers with an activation, optional normalization and dropout, one logit out."""
    def __init__(
        self,
        input_dim: int,
        hidden_layers: list[int],
        dropout: float,
        activation: str = "relu",
        normalization: str = "none",
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        current_dim = input_dim
        for hidden_dim in hidden_layers:
            layers.append(nn.Linear(current_dim, hidden_dim))
            norm_layer = build_normalization(normalization, hidden_dim)
            if norm_layer is not None:
                layers.append(norm_layer)
            layers.append(build_activation(activation))
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            current_dim = hidden_dim
        layers.append(nn.Linear(current_dim, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features).squeeze(-1)


def build_activation(name: str) -> nn.Module:
    """The activation module a config name names (relu, gelu, silu, ...)."""
    normalized = name.lower()
    if normalized == "relu":
        return nn.ReLU()
    if normalized == "gelu":
        return nn.GELU()
    if normalized == "silu":
        return nn.SiLU()
    raise ValueError(f"Unsupported activation: {name}")


def build_normalization(name: str, hidden_dim: int) -> nn.Module | None:
    """The normalization module a config name names, for a layer of `hidden_dim` units; None for "none" or "off"."""
    normalized = name.lower()
    if normalized in {"none", "off"}:
        return None
    if normalized == "layernorm":
        return nn.LayerNorm(hidden_dim)
    if normalized == "batchnorm":
        return nn.BatchNorm1d(hidden_dim)
    raise ValueError(f"Unsupported normalization: {name}")


class AetherNetMultiTask(nn.Module):
    """Shared-trunk, three-head variant of AetherNet: direction (binary
    logit), magnitude (raw regression) and volatility (Softplus, always
    non-negative). The trunk is identical in shape to AetherNet's own
    hidden-layer stack (same build_activation/build_normalization reuse) -
    only the single output Linear(., 1) is replaced with three independent
    small heads sharing the trunk's representation. See
    inference/exported_model.py::run_exported_multitask_model() for the
    matching interpreter and export_multitask_architecture() below for the
    matching exporter."""

    def __init__(
        self,
        input_dim: int,
        hidden_layers: list[int],
        dropout: float,
        activation: str = "relu",
        normalization: str = "none",
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        current_dim = input_dim
        for hidden_dim in hidden_layers:
            layers.append(nn.Linear(current_dim, hidden_dim))
            norm_layer = build_normalization(normalization, hidden_dim)
            if norm_layer is not None:
                layers.append(norm_layer)
            layers.append(build_activation(activation))
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            current_dim = hidden_dim
        self.trunk = nn.Sequential(*layers)
        self.head_direction = nn.Linear(current_dim, 1)
        self.head_magnitude = nn.Linear(current_dim, 1)
        self.head_volatility = nn.Linear(current_dim, 1)

    def forward(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        trunk_output = self.trunk(features)
        direction_logit = self.head_direction(trunk_output).squeeze(-1)
        magnitude = self.head_magnitude(trunk_output).squeeze(-1)
        volatility = nn.functional.softplus(self.head_volatility(trunk_output).squeeze(-1))
        return direction_logit, magnitude, volatility


class AetherNetMultiTaskHorizons(nn.Module):
    """Extends AetherNetMultiTask with 4 additional heads: direction_5d/
    direction_20d (longer-horizon direction - the highest-leverage change
    this codebase's root-cause investigation identified, since next-day
    binary direction on liquid daily bars is close to efficient-market
    noise, and longer horizons give momentum/mean-reversion more room to
    show up) and rank_5d/rank_20d (cross-sectional percentile-rank of
    forward return across the universe on the same date - typically far
    more learnable than absolute direction, and maps directly onto a
    long/short portfolio).

    A NEW sibling class, not a modification of AetherNetMultiTask -
    train.py::_train_expert_multitask() (the 4 regime experts' own
    multitask heads) keeps using the original 3-head class completely
    unchanged, by design (experts/baseline/gating stay 1d-direction-only,
    see development/Changelog.md). Same trunk-building logic as
    AetherNetMultiTask; all 7 heads share it.

    forward() returns a dict, not AetherNetMultiTask's fixed 3-tuple - one
    raw (pre-activation, except volatility which applies softplus
    internally same as AetherNetMultiTask) tensor per head. This naming
    maps 1:1 onto the export's "heads" dict keys (see
    export_multitask_horizons_architecture()), which
    inference/exported_model.py::run_exported_multitask_model() already
    iterates generically - no interpreter changes needed for the new
    heads."""

    def __init__(
        self,
        input_dim: int,
        hidden_layers: list[int],
        dropout: float,
        activation: str = "relu",
        normalization: str = "none",
        extra_heads: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        current_dim = input_dim
        for hidden_dim in hidden_layers:
            layers.append(nn.Linear(current_dim, hidden_dim))
            norm_layer = build_normalization(normalization, hidden_dim)
            if norm_layer is not None:
                layers.append(norm_layer)
            layers.append(build_activation(activation))
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            current_dim = hidden_dim
        self.trunk = nn.Sequential(*layers)
        self.head_direction = nn.Linear(current_dim, 1)
        self.head_magnitude = nn.Linear(current_dim, 1)
        self.head_volatility = nn.Linear(current_dim, 1)
        self.head_direction_5d = nn.Linear(current_dim, 1)
        self.head_direction_20d = nn.Linear(current_dim, 1)
        self.head_rank_5d = nn.Linear(current_dim, 1)
        self.head_rank_20d = nn.Linear(current_dim, 1)
        # Phase 5 of the 5/10 -> 9/10 roadmap: a NEW sibling head, not a
        # modification of head_rank_20d - every existing consumer of
        # rank_20d (rank_sizing_multiplier(), etc.) is unaffected until/
        # unless someone deliberately switches to this sector-demeaned
        # variant. See build_cross_sectional_rank_targets()'s docstring.
        self.head_sector_neutral_rank_20d = nn.Linear(current_dim, 1)
        # V5.1 Phase 2 (item 5 of the roadmap) - see
        # train.py::build_residual_rank_targets()'s docstring for what
        # these targets are. beta_neutral_rank_20d ships DISABLED by
        # default (HORIZON_HEAD_SPECS/DEFAULT_HORIZON_HEAD_CONFIG) -
        # strictly dominated by the combined residual_rank_20d above it,
        # registered only so it stops being fully dead code (the target
        # column itself is computed unconditionally by
        # build_cross_sectional_rank_targets() and previously consumed by
        # no head at all).
        self.head_residual_rank_5d = nn.Linear(current_dim, 1)
        self.head_residual_rank_20d = nn.Linear(current_dim, 1)
        self.head_beta_neutral_rank_20d = nn.Linear(current_dim, 1)
        # V6.0.0: heads from EXTRA_HORIZON_HEAD_SPECS, built last so the default model's parameters (and their random
        # initialisation order) are unchanged when none is enabled.
        self.extra_heads = tuple(extra_heads)
        for name in self.extra_heads:
            setattr(self, f"head_{name}", nn.Linear(current_dim, 1))

    def forward(self, features: torch.Tensor) -> dict[str, torch.Tensor]:
        trunk_output = self.trunk(features)
        extra = {name: getattr(self, f"head_{name}")(trunk_output).squeeze(-1) for name in self.extra_heads}
        return extra | {
            "direction": self.head_direction(trunk_output).squeeze(-1),
            "magnitude": self.head_magnitude(trunk_output).squeeze(-1),
            "volatility": nn.functional.softplus(self.head_volatility(trunk_output).squeeze(-1)),
            "direction_5d": self.head_direction_5d(trunk_output).squeeze(-1),
            "direction_20d": self.head_direction_20d(trunk_output).squeeze(-1),
            "rank_5d": self.head_rank_5d(trunk_output).squeeze(-1),
            "rank_20d": self.head_rank_20d(trunk_output).squeeze(-1),
            "sector_neutral_rank_20d": self.head_sector_neutral_rank_20d(trunk_output).squeeze(-1),
            "residual_rank_5d": self.head_residual_rank_5d(trunk_output).squeeze(-1),
            "residual_rank_20d": self.head_residual_rank_20d(trunk_output).squeeze(-1),
            "beta_neutral_rank_20d": self.head_beta_neutral_rank_20d(trunk_output).squeeze(-1),
        }


class AetherNetSequenceMultiTask(nn.Module):
    """Phase 2: a causal TCN (temporal convolutional network) trunk over a
    rolling window of already-computed flat model_input vectors, replacing
    AetherNetMultiTask's flat-MLP trunk with genuine temporal structure -
    the root limitation the original root-cause investigation flagged
    ("AetherNet is a plain feedforward MLP with zero temporal structure").

    A stack of causal, dilated Conv1d layers (dilation doubling each layer:
    1, 2, 4, ... - the standard WaveNet/TCN receptive-field-growth idiom),
    each left-padded by (kernel_size-1)*dilation timesteps before the conv
    so output[t] never depends on input[>t] (no lookahead, same invariant
    every other feature in this codebase already respects) - matching
    inference/exported_model.py::_conv1d_causal()'s exact convention.
    Pools to the trunk's most-recent (causal) timestep, then the same
    three direction/magnitude/volatility heads AetherNetMultiTask already
    uses.

    Chosen over a Transformer encoder block for this first real Phase 2
    model specifically because a causal conv stack is simpler to verify
    bit-for-bit end-to-end (see
    inference/exported_model.py::run_exported_sequence_multitask_model()) -
    _multihead_attention() is implemented and independently tested as
    interpreter infrastructure for a future attention-based model, not
    wired to a trained model in this pass; see train_sequence.py's module
    docstring for the fuller scope note.
    """

    def __init__(
        self,
        input_dim: int,
        channels: list[int],
        kernel_size: int,
        dropout: float,
    ) -> None:
        super().__init__()
        if not channels:
            raise ValueError("AetherNetSequenceMultiTask requires at least one trunk channel size.")
        self.kernel_size = int(kernel_size)
        self.conv_layers = nn.ModuleList()
        current_channels = input_dim
        for layer_index, out_channels in enumerate(channels):
            dilation = 2**layer_index
            self.conv_layers.append(nn.Conv1d(current_channels, out_channels, self.kernel_size, dilation=dilation))
            current_channels = out_channels
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()
        self.head_direction = nn.Linear(current_channels, 1)
        self.head_magnitude = nn.Linear(current_channels, 1)
        self.head_volatility = nn.Linear(current_channels, 1)

    def forward(self, sequence: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        # sequence: (batch, window, input_dim) -> Conv1d wants channels-first.
        current = sequence.transpose(1, 2)  # (batch, input_dim, window)
        for _layer_index, conv in enumerate(self.conv_layers):
            dilation = conv.dilation[0]
            pad_left = (self.kernel_size - 1) * dilation
            current = nn.functional.pad(current, (pad_left, 0))
            current = conv(current)
            current = self.dropout(self.activation(current))

        pooled = current[:, :, -1]  # (batch, channels[-1]) - most-recent timestep
        direction_logit = self.head_direction(pooled).squeeze(-1)
        magnitude = self.head_magnitude(pooled).squeeze(-1)
        volatility = nn.functional.softplus(self.head_volatility(pooled).squeeze(-1))
        return direction_logit, magnitude, volatility


class AetherNetSequenceMultiTaskHorizons(nn.Module):
    """Sequence-encoder sibling of AetherNetMultiTaskHorizons: the same
    causal TCN trunk as AetherNetSequenceMultiTask, extended with the same
    4 additional heads (direction_5d/20d, rank_5d/20d). A NEW class, not a
    modification of AetherNetSequenceMultiTask - same reasoning as
    AetherNetMultiTaskHorizons above (experts never use the sequence
    model at all, so there is no shared-code risk here, but the
    new-sibling-class convention stays consistent across both trainers).
    forward() returns a dict, matching AetherNetMultiTaskHorizons and the
    export's "heads" dict shape."""

    def __init__(
        self,
        input_dim: int,
        channels: list[int],
        kernel_size: int,
        dropout: float,
        normalization: str = "none",
    ) -> None:
        super().__init__()
        if not channels:
            raise ValueError("AetherNetSequenceMultiTaskHorizons requires at least one trunk channel size.")
        self.kernel_size = int(kernel_size)
        # V5.1 Phase 3 (item 10) - the TCN trunk previously had NO
        # normalization at all (Conv1d -> ReLU -> Dropout only), unlike
        # AetherNetMultiTaskHorizons' MLP trunk (which already supports
        # LayerNorm). normalization="none" is the FUNCTION default -
        # byte-identical to every existing caller/checkpoint when this
        # param is omitted. "layernorm" inserts an nn.LayerNorm(out_channels)
        # after each Conv1d->ReLU, normalizing over the CHANNEL axis per
        # timestep - see forward()'s transpose comment for why, and
        # export_sequence_multitask_horizons_architecture()/
        # _export_conv1d_trunk() for the matching "layernorm_axis" export
        # layer (already supported by inference/exported_model.py with
        # zero interpreter changes - see that module's own docstring).
        self.normalization = str(normalization)
        self.conv_layers = nn.ModuleList()
        self.layer_norms = nn.ModuleList()
        current_channels = input_dim
        for layer_index, out_channels in enumerate(channels):
            dilation = 2**layer_index
            self.conv_layers.append(nn.Conv1d(current_channels, out_channels, self.kernel_size, dilation=dilation))
            self.layer_norms.append(nn.LayerNorm(out_channels) if self.normalization == "layernorm" else nn.Identity())
            current_channels = out_channels
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()
        self.head_direction = nn.Linear(current_channels, 1)
        self.head_magnitude = nn.Linear(current_channels, 1)
        self.head_volatility = nn.Linear(current_channels, 1)
        self.head_direction_5d = nn.Linear(current_channels, 1)
        self.head_direction_20d = nn.Linear(current_channels, 1)
        self.head_rank_5d = nn.Linear(current_channels, 1)
        self.head_rank_20d = nn.Linear(current_channels, 1)
        # Phase 5 of the 5/10 -> 9/10 roadmap - see
        # AetherNetMultiTaskHorizons.head_sector_neutral_rank_20d's
        # identical docstring.
        self.head_sector_neutral_rank_20d = nn.Linear(current_channels, 1)
        # V5.1 Phase 2 (item 5 of the roadmap) - see
        # AetherNetMultiTaskHorizons's identical new-heads docstring above.
        self.head_residual_rank_5d = nn.Linear(current_channels, 1)
        self.head_residual_rank_20d = nn.Linear(current_channels, 1)
        self.head_beta_neutral_rank_20d = nn.Linear(current_channels, 1)

    def forward(self, sequence: torch.Tensor) -> dict[str, torch.Tensor]:
        current = sequence.transpose(1, 2)  # (batch, input_dim, window)
        for conv, layer_norm in zip(self.conv_layers, self.layer_norms, strict=False):
            dilation = conv.dilation[0]
            pad_left = (self.kernel_size - 1) * dilation
            current = nn.functional.pad(current, (pad_left, 0))
            current = self.activation(conv(current))
            if self.normalization == "layernorm":
                # nn.LayerNorm(out_channels) normalizes over its last dim -
                # current is (batch, channels, window) (PyTorch's own
                # Conv1d convention), so transpose to (batch, window,
                # channels) first (normalize each timestep's channel
                # vector independently), then back. Matches
                # inference/exported_model.py's _layernorm_axis(axis=-1)
                # on a (window, channels) array exactly - same per-
                # timestep, per-channel-axis normalization, just with an
                # extra leading batch dim here.
                current = layer_norm(current.transpose(1, 2)).transpose(1, 2)
            current = self.dropout(current)

        pooled = current[:, :, -1]  # (batch, channels[-1]) - most-recent timestep
        return {
            "direction": self.head_direction(pooled).squeeze(-1),
            "magnitude": self.head_magnitude(pooled).squeeze(-1),
            "volatility": nn.functional.softplus(self.head_volatility(pooled).squeeze(-1)),
            "direction_5d": self.head_direction_5d(pooled).squeeze(-1),
            "direction_20d": self.head_direction_20d(pooled).squeeze(-1),
            "rank_5d": self.head_rank_5d(pooled).squeeze(-1),
            "rank_20d": self.head_rank_20d(pooled).squeeze(-1),
            "sector_neutral_rank_20d": self.head_sector_neutral_rank_20d(pooled).squeeze(-1),
            "residual_rank_5d": self.head_residual_rank_5d(pooled).squeeze(-1),
            "residual_rank_20d": self.head_residual_rank_20d(pooled).squeeze(-1),
            "beta_neutral_rank_20d": self.head_beta_neutral_rank_20d(pooled).squeeze(-1),
        }


def _export_conv1d_trunk(model) -> list[dict]:
    """Shared by export_sequence_multitask_architecture() and
    export_sequence_multitask_horizons_architecture() - both models build
    their causal TCN trunk identically (AetherNetSequenceMultiTask/
    AetherNetSequenceMultiTaskHorizons.__init__ are the same conv-stack
    loop), only their heads differ.

    V5.1 Phase 3 (item 10): AetherNetSequenceMultiTask (the older sibling)
    has no `normalization`/`layer_norms` attribute at all -
    getattr(..., "none")/getattr(..., None) below degrade it to the
    pre-Phase-3 trunk shape exactly (no layernorm_axis entries), so this
    stays a true shared helper rather than needing two near-duplicate
    versions."""
    trunk: list[dict] = []
    use_layernorm = getattr(model, "normalization", "none") == "layernorm"
    layer_norms = getattr(model, "layer_norms", None)
    for layer_index, conv in enumerate(model.conv_layers):
        trunk.append(
            {
                "type": "conv1d_causal",
                "weight_key": f"conv_layers.{layer_index}.weight",
                "bias_key": f"conv_layers.{layer_index}.bias",
                "dilation": conv.dilation[0],
                "in_channels": conv.in_channels,
                "out_channels": conv.out_channels,
                "kernel_size": conv.kernel_size[0],
            }
        )
        trunk.append({"type": "relu"})
        if use_layernorm and layer_norms is not None:
            layer_norm = layer_norms[layer_index]
            trunk.append(
                {
                    "type": "layernorm_axis",
                    "weight_key": f"layer_norms.{layer_index}.weight",
                    "bias_key": f"layer_norms.{layer_index}.bias",
                    "eps": layer_norm.eps,
                }
            )
        trunk.append({"type": "dropout", "p": model.dropout.p if isinstance(model.dropout, nn.Dropout) else 0.0})
    return trunk


def export_sequence_multitask_architecture(model: AetherNetSequenceMultiTask) -> dict[str, Any]:
    """Branching export for AetherNetSequenceMultiTask - same {"trunk":
    [...], "heads": {...}} shape export_multitask_architecture() produces,
    but trunk entries are "conv1d_causal" layers (each carrying its own
    dilation, doubling per layer to match __init__'s dilation=2**layer_index)
    instead of "linear". Consumed by
    inference/exported_model.py::run_exported_sequence_multitask_model()."""
    return {
        "trunk": _export_conv1d_trunk(model),
        "heads": {
            "direction": _export_head(model.head_direction, "head_direction", "sigmoid"),
            "magnitude": _export_head(model.head_magnitude, "head_magnitude", None),
            "volatility": _export_head(model.head_volatility, "head_volatility", "softplus"),
        },
    }


def export_sequence_multitask_horizons_architecture(model: AetherNetSequenceMultiTaskHorizons) -> dict[str, Any]:
    """Branching export for AetherNetSequenceMultiTaskHorizons - same
    {"trunk", "heads"} shape export_sequence_multitask_architecture()
    produces for the original 3-head sequence model, extended with 4 more
    head entries (direction_5d/20d, rank_5d/20d).
    inference/exported_model.py::run_exported_sequence_multitask_model()
    already iterates export["heads"] generically, so no interpreter change
    is needed to support the extra heads.

    V5.1 Phase 1 (development/Problems.md #73): rank_5d/rank_20d/
    sector_neutral_rank_20d export with NO final activation (was
    "sigmoid") - these heads are trained as raw linear regression against a
    [0,1] percentile-rank target (masked_mse_loss() in
    compute_combined_multitask_loss()), never through a sigmoid, so
    exporting one applied a transform inference never trained through:
    live predicted_rank_20d compressed into roughly [0.5, 0.7] instead of
    spanning [0,1] (sigmoid'(0.5)~=0.235 shrinks dispersion ~4x). Rank-IC
    (this project's own promotion-gate metric) is invariant under any
    monotone transform, which is exactly why no rank-IC-based gate ever
    caught it - it took building an offline net-of-cost simulator
    (evaluation/rank_book_simulator.py) sensitive to the ACTUAL
    dispersion to surface it. The fix pairs with
    portfolio/rank_signal.py::cross_sectional_rank_scores() (main.py),
    which re-derives a true [0,1] percentile per bar regardless of
    whatever raw scale a head happens to export at - so this export
    change is safe even for a stale artifact still carrying the old
    "sigmoid" entry (monotone-invariant either way)."""
    return {
        "trunk": _export_conv1d_trunk(model),
        "heads": {
            "direction": _export_head(model.head_direction, "head_direction", "sigmoid"),
            "magnitude": _export_head(model.head_magnitude, "head_magnitude", None),
            "volatility": _export_head(model.head_volatility, "head_volatility", "softplus"),
            "direction_5d": _export_head(model.head_direction_5d, "head_direction_5d", "sigmoid"),
            "direction_20d": _export_head(model.head_direction_20d, "head_direction_20d", "sigmoid"),
            "rank_5d": _export_head(model.head_rank_5d, "head_rank_5d", None),
            "rank_20d": _export_head(model.head_rank_20d, "head_rank_20d", None),
            "sector_neutral_rank_20d": _export_head(
                model.head_sector_neutral_rank_20d, "head_sector_neutral_rank_20d", None
            ),
            # V5.1 Phase 2 (item 5) - activation None, same reasoning as
            # rank_5d/rank_20d/sector_neutral_rank_20d above: trained as
            # raw linear regression against a [0,1] percentile target,
            # never through a sigmoid.
            "residual_rank_5d": _export_head(model.head_residual_rank_5d, "head_residual_rank_5d", None),
            "residual_rank_20d": _export_head(model.head_residual_rank_20d, "head_residual_rank_20d", None),
            "beta_neutral_rank_20d": _export_head(
                model.head_beta_neutral_rank_20d, "head_beta_neutral_rank_20d", None
            ),
        },
    }


# Head name -> (target column, "binary"/"rank", non_overlapping_stride for
# rank-IC's non-overlapping subsample - unused by binary heads). Shared by
# train_multitask.py/train_sequence.py - both trainers' Horizons model
# variants expose identically-named heads (see
# AetherNetMultiTaskHorizons/AetherNetSequenceMultiTaskHorizons docstrings).
HORIZON_HEAD_SPECS = {
    "direction_5d": ("target_direction_5d", "binary", None),
    "direction_20d": ("target_direction_20d", "binary", None),
    "rank_5d": ("target_rank_5d", "rank", 5),
    "rank_20d": ("target_rank_20d", "rank", 20),
    # Phase 5 of the 5/10 -> 9/10 roadmap - a "rank"-kind head like rank_20d,
    # so it automatically gets the exact same masked-MSE loss, rank-IC
    # metrics, AND assess_ranking_quality_from_predictions() promotion-gate
    # assessment as rank_20d, with zero extra wiring beyond this entry -
    # every consumer of HORIZON_HEAD_SPECS (compute_combined_multitask_loss(),
    # compute_multitask_metrics()/compute_sequence_multitask_metrics()) is
    # already fully generic over this dict.
    "sector_neutral_rank_20d": ("target_sector_neutral_rank_20d", "rank", 20),
    # V5.1 Phase 2 (item 5 of the roadmap) - see
    # train.py::build_residual_rank_targets()'s docstring. Same "rank"-kind
    # generic wiring as sector_neutral_rank_20d above - zero extra plumbing
    # beyond these entries.
    "residual_rank_5d": ("target_residual_rank_5d", "rank", 5),
    "residual_rank_20d": ("target_residual_rank_20d", "rank", 20),
    # Computed by build_cross_sectional_rank_targets() (a single whole-
    # history per-asset market beta, simpler than residual_rank_20d's
    # combined market+sector+size regression) but ships with NO active
    # head by default (see DEFAULT_HORIZON_HEAD_CONFIG below) - strictly
    # dominated by residual_rank_20d, registered only so it stops being
    # fully dead code and gets full metrics on a one-key config flip.
    "beta_neutral_rank_20d": ("target_beta_neutral_rank_20d", "rank", 20),
}
# V6.0.0: heads that exist only when a trainer's horizon_heads block enables them (and the dataset carries the target,
# phase1.target.ranking.extra_horizon_days); never part of the default model, export or metrics.
EXTRA_HORIZON_HEAD_SPECS = {
    "rank_60d": ("target_rank_60d", "rank", 60),
}


def enabled_extra_heads(horizon_head_config: dict[str, Any]) -> tuple[str, ...]:
    """The extra horizon heads a horizon-head config switches on, in a fixed order."""
    return tuple(name for name in EXTRA_HORIZON_HEAD_SPECS if horizon_head_config.get(name, {}).get("enabled", False))


def horizon_head_specs(horizon_head_config: dict[str, Any]) -> dict[str, Any]:
    """HORIZON_HEAD_SPECS plus every enabled extra head (identical to HORIZON_HEAD_SPECS when none is)."""
    return HORIZON_HEAD_SPECS | {name: EXTRA_HORIZON_HEAD_SPECS[name] for name in enabled_extra_heads(horizon_head_config)}


DEFAULT_HORIZON_HEAD_CONFIG = {
    "direction_5d": {"enabled": True, "loss_weight": 1.0},
    "direction_20d": {"enabled": True, "loss_weight": 0.5},
    "rank_5d": {"enabled": True, "loss_weight": 1.0},
    "rank_20d": {"enabled": True, "loss_weight": 0.5},
    # Lighter weight than rank_20d - the newest, least-validated head;
    # doesn't dominate training until its own promotion criteria clear.
    "sector_neutral_rank_20d": {"enabled": True, "loss_weight": 0.3},
    # V5.1 Phase 2 (item 5) - residual_rank_20d is meant to become the
    # cleanest live signal once validated (market+sector+size already
    # factored out), so it trains at rank_20d's own original weight;
    # residual_rank_5d lighter, matching rank_5d/rank_20d's own 1.0/0.5
    # split convention. beta_neutral_rank_20d disabled/zero-weight - see
    # HORIZON_HEAD_SPECS's own comment for why.
    "residual_rank_5d": {"enabled": True, "loss_weight": 0.5},
    "residual_rank_20d": {"enabled": True, "loss_weight": 1.0},
    "beta_neutral_rank_20d": {"enabled": False, "loss_weight": 0.0},
}


def resolve_horizon_head_config(training_config: dict[str, Any]) -> dict[str, Any]:
    """Merges a trainer's own config.json horizon_heads block (e.g.
    phase_v2.retraining.multitask_training.horizon_heads or
    ...sequence_training.horizon_heads) over DEFAULT_HORIZON_HEAD_CONFIG -
    an older config missing this key entirely (or missing one head's
    entry) still gets sane defaults for every head, rather than silently
    treating an absent head as disabled."""
    configured = training_config.get("horizon_heads", {})
    resolved = {}
    for head_name, defaults in DEFAULT_HORIZON_HEAD_CONFIG.items():
        head_config = {**defaults, **configured.get(head_name, {})}
        resolved[head_name] = head_config
    for head_name in EXTRA_HORIZON_HEAD_SPECS:
        if head_name in configured:
            resolved[head_name] = {"enabled": False, "loss_weight": 0.0, **configured[head_name]}
    return resolved


def export_state_dict(model: nn.Module) -> dict[str, Any]:
    """A model's weights as nested lists, the JSON the numpy forward pass reads."""
    exported = {}
    for key, value in model.state_dict().items():
        exported[key] = value.detach().cpu().tolist()
    return exported


def _export_sequential_layers(sequential_module: nn.Sequential, key_prefix: str) -> list[dict]:
    """Per-layer export walk shared by export_architecture() (prefix
    "network") and export_multitask_architecture()'s trunk (prefix "trunk")
    below - extracted verbatim from the original export_architecture() body,
    a behavior-preserving refactor (same dict shapes, same key naming)."""
    architecture: list[dict] = []
    for index, module in enumerate(sequential_module):
        if isinstance(module, nn.Linear):
            architecture.append(
                {
                    "type": "linear",
                    "weight_key": f"{key_prefix}.{index}.weight",
                    "bias_key": f"{key_prefix}.{index}.bias",
                    "in_features": module.in_features,
                    "out_features": module.out_features,
                }
            )
        elif isinstance(module, nn.LayerNorm):
            architecture.append(
                {
                    "type": "layernorm",
                    "weight_key": f"{key_prefix}.{index}.weight",
                    "bias_key": f"{key_prefix}.{index}.bias",
                    "normalized_shape": list(module.normalized_shape),
                    "eps": module.eps,
                }
            )
        elif isinstance(module, nn.BatchNorm1d):
            architecture.append(
                {
                    "type": "batchnorm1d",
                    "weight_key": f"{key_prefix}.{index}.weight",
                    "bias_key": f"{key_prefix}.{index}.bias",
                    "running_mean_key": f"{key_prefix}.{index}.running_mean",
                    "running_var_key": f"{key_prefix}.{index}.running_var",
                    "num_features": module.num_features,
                    "eps": module.eps,
                }
            )
        elif isinstance(module, nn.ReLU):
            architecture.append({"type": "relu"})
        elif isinstance(module, nn.GELU):
            architecture.append({"type": "gelu"})
        elif isinstance(module, nn.SiLU):
            architecture.append({"type": "silu"})
        elif isinstance(module, nn.Dropout):
            architecture.append({"type": "dropout", "p": module.p})
        else:
            architecture.append({"type": module.__class__.__name__.lower()})
    return architecture


def export_architecture(model: AetherNet) -> list[dict]:
    """The baseline network's layers as the JSON the numpy forward pass reads."""
    architecture = _export_sequential_layers(model.network, "network")
    architecture.append({"type": "sigmoid"})
    return architecture


def _export_head(module: nn.Linear, key_prefix: str, final_activation: str | None) -> list[dict]:
    """A single head's export: one Linear layer plus its final activation
    (or none, for the raw-regression magnitude head). Heads are
    deliberately restricted to a single Linear - inference/exported_model.py::
    run_exported_multitask_model() and AetherNetMultiTask both assume this
    shape; a deeper head would need matching changes in both places."""
    head: list[dict] = [
        {
            "type": "linear",
            "weight_key": f"{key_prefix}.weight",
            "bias_key": f"{key_prefix}.bias",
            "in_features": module.in_features,
            "out_features": module.out_features,
        }
    ]
    if final_activation is not None:
        head.append({"type": final_activation})
    return head


def export_multitask_architecture(model: AetherNetMultiTask) -> dict[str, Any]:
    """Branching export for AetherNetMultiTask - a {"trunk": [...], "heads":
    {"direction": [...], "magnitude": [...], "volatility": [...]}} structure
    instead of export_architecture()'s single flat list. Consumed by
    inference/exported_model.py::run_exported_multitask_model(), never by
    run_exported_model() (which only understands a flat "architecture" list
    and would KeyError on this shape - the two exports are not
    interchangeable, matching the two different interpreter entry points)."""
    return {
        "trunk": _export_sequential_layers(model.trunk, "trunk"),
        "heads": {
            "direction": _export_head(model.head_direction, "head_direction", "sigmoid"),
            "magnitude": _export_head(model.head_magnitude, "head_magnitude", None),
            "volatility": _export_head(model.head_volatility, "head_volatility", "softplus"),
        },
    }


def export_multitask_horizons_architecture(model: AetherNetMultiTaskHorizons) -> dict[str, Any]:
    """Branching export for AetherNetMultiTaskHorizons - same {"trunk",
    "heads"} shape export_multitask_architecture() produces for the
    original 3-head model, extended with 4 more head entries (direction_5d/
    20d, rank_5d/20d). inference/exported_model.py::run_exported_multitask_model()
    already iterates export["heads"] generically, so no interpreter change
    is needed to support the extra heads.

    V5.1 Phase 1 (development/Problems.md #73): rank_5d/rank_20d/
    sector_neutral_rank_20d export with NO final activation (was
    "sigmoid") - see export_sequence_multitask_horizons_architecture()'s
    matching docstring for the full writeup (same bug, same fix, both
    model families)."""
    return {
        "trunk": _export_sequential_layers(model.trunk, "trunk"),
        "heads": {
            "direction": _export_head(model.head_direction, "head_direction", "sigmoid"),
            "magnitude": _export_head(model.head_magnitude, "head_magnitude", None),
            "volatility": _export_head(model.head_volatility, "head_volatility", "softplus"),
            "direction_5d": _export_head(model.head_direction_5d, "head_direction_5d", "sigmoid"),
            "direction_20d": _export_head(model.head_direction_20d, "head_direction_20d", "sigmoid"),
            "rank_5d": _export_head(model.head_rank_5d, "head_rank_5d", None),
            "rank_20d": _export_head(model.head_rank_20d, "head_rank_20d", None),
            "sector_neutral_rank_20d": _export_head(
                model.head_sector_neutral_rank_20d, "head_sector_neutral_rank_20d", None
            ),
            # V5.1 Phase 2 (item 5) - activation None, same reasoning as
            # rank_5d/rank_20d/sector_neutral_rank_20d above.
            "residual_rank_5d": _export_head(model.head_residual_rank_5d, "head_residual_rank_5d", None),
            "residual_rank_20d": _export_head(model.head_residual_rank_20d, "head_residual_rank_20d", None),
            "beta_neutral_rank_20d": _export_head(
                model.head_beta_neutral_rank_20d, "head_beta_neutral_rank_20d", None
            ),
        }
        | {
            name: _export_head(getattr(model, f"head_{name}"), f"head_{name}", None)
            for name in getattr(model, "extra_heads", ())
        },
    }
