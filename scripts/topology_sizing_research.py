"""Learned-topology sizing multiplier (V5.8.0 P5.6, rule R-TOPO): keep `phase_v2.topology_learning` ON or switch it off?

Live, a node whose learned confidence clears `min_confidence_for_learned` gets a bounded shrink-only size multiplier
`0.5 + 0.5 * confidence * (1 - disagreement)` (`risk.position_sizing.topology_sizing_multiplier`). The offline
simulator did not model it. This scores it per dataset row with the SAME prototype distances and softmax
(`topology.learned_topology.learned_sizing_inputs`) and runs the as-live book with it plugged into the member sizing
chain (`evaluation.live_parity.build_live_member_weight_fn(topology_inputs_fn=...)`).

What the dataset cannot give is the live peer term (the learned neighbours vs the deterministic cluster's peers, a
whole-bar quantity), so it is bracketed: peer distance 0 (best case), 0.5 (mid, the reported estimate), 1 (worst).
The cluster's dominant regime is approximated by the row's own regime label.

R-TOPO (fixed before any number was seen): the shipped state is ON, so it is switched OFF only if OFF beats ON(mid) by
the R-GATE margins (backtest-split net Sharpe >= +0.10 better, validation not worse by > 0.02, drawdown not worse by
> 1 pp); otherwise it stays ON. Best and worst are reported, never used to decide.

    python scripts/topology_sizing_research.py [--dataset-validation PATH --dataset-backtest PATH] [--no-cache]
    -> ml/evaluation/topology_sizing_research.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from as_live_levers import AsLiveHarness, add_split_dataset_args, dataset_for_split, summarize  # noqa: E402
from gate_research import decide as r_gate  # noqa: E402

PEER_DISTANCE = {"on_best": 0.0, "on_mid": 0.5, "on_worst": 1.0}


def decide(results: dict) -> dict:
    """`results` = {"off": {split: summary}, "on_mid": {split: summary}, ...}. OFF must pass R-GATE against ON(mid)."""
    verdict = r_gate(results["on_mid"], results["off"])
    if verdict["passes_r_gate"]:
        return {"branch": "switch_off", "topology_learning_enabled": False, "r_gate_off_vs_on_mid": verdict}
    return {"branch": "keep_on", "topology_learning_enabled": True, "r_gate_off_vs_on_mid": verdict}


def topology_inputs_by_row(frame, topo_model: dict, topo_schema: dict, probabilities, peer_distance: float, *,
                           temperature: float, min_confidence: float) -> dict:
    """{(date, ticker): inputs} from every dataset row's topology feature vector (train_topology.dataset_feature_vectors)."""
    from topology.learned_topology import learned_sizing_inputs
    from train_topology import dataset_feature_vectors_indexed

    records = frame.to_dict("records")
    indices, vectors, _outcomes, regimes = dataset_feature_vectors_indexed(records, list(probabilities))
    out = {}
    for index, vector, regime in zip(indices, vectors, regimes):
        row = records[index]
        out[(str(row["date"])[:10], str(row["ticker"]))] = learned_sizing_inputs(
            vector, topo_model, topo_schema, cluster_regime_label=regime, peer_distance=peer_distance,
            temperature=temperature, min_confidence_for_learned=min_confidence,
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topology-model", default=str(ROOT_DIR / "ml" / "topology_model.json"))
    parser.add_argument("--topology-schema", default=str(ROOT_DIR / "ml" / "topology_feature_schema.json"))
    add_split_dataset_args(parser)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    from evaluation.model_predictions import predict_heads

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    learning = config["phase_v2"].get("topology_learning", {})
    temperature = float(learning.get("temperature", 0.35))
    min_confidence = float(learning.get("min_confidence_for_learned", 0.2))
    topo_model = json.loads(Path(args.topology_model).read_text(encoding="utf-8"))
    topo_schema = json.loads(Path(args.topology_schema).read_text(encoding="utf-8"))
    mt_schema = json.loads((ROOT_DIR / "ml" / "multitask_feature_schema.json").read_text(encoding="utf-8"))
    mt_model = json.loads((ROOT_DIR / "ml" / "multitask_model.json").read_text(encoding="utf-8"))

    results: dict[str, dict] = {"off": {}, **{name: {} for name in PEER_DISTANCE}}
    multiplier_stats: dict[str, dict] = {}
    for split in ("validation", "backtest"):
        harness = AsLiveHarness(split, use_cache=not args.no_cache, dataset_path=dataset_for_split(args, split))
        probabilities = predict_heads(
            harness.frame, mt_model, list(mt_schema["model_input_names"]), ["direction"], model_kind="multitask", batched=True
        )["direction"]
        results["off"][split] = summarize(harness.as_live())
        print(f"[{split}] off: net sharpe {results['off'][split]['net_sharpe']:+.3f}", flush=True)
        for name, peer in PEER_DISTANCE.items():
            table = topology_inputs_by_row(harness.frame, topo_model, topo_schema, probabilities, peer,
                                           temperature=temperature, min_confidence=min_confidence)
            harness.topology_inputs_fn = lambda symbol, date, table=table: table.get((str(date)[:10], str(symbol)))
            harness._mechanisms.clear()
            results[name][split] = summarize(harness.as_live())
            learned = [v for v in table.values() if v["topology_source"] == "learned"]
            from risk.position_sizing import topology_sizing_multiplier

            multipliers = [topology_sizing_multiplier(v["topology_source"], v["topology_confidence"], v["topology_disagreement"])[0]
                           for v in table.values()]
            multiplier_stats.setdefault(name, {})[split] = {
                "rows": len(table), "learned_share": len(learned) / max(len(table), 1),
                "mean_multiplier": float(np.mean(multipliers)) if multipliers else None,
            }
            print(f"[{split}] {name}: net sharpe {results[name][split]['net_sharpe']:+.3f} "
                  f"(mean multiplier {multiplier_stats[name][split]['mean_multiplier']:.3f}, learned share "
                  f"{multiplier_stats[name][split]['learned_share']:.2f})", flush=True)
        harness.topology_inputs_fn = None
        harness._mechanisms.clear()

    decision = decide(results)
    print("decision:", json.dumps({k: v for k, v in decision.items() if k != "r_gate_off_vs_on_mid"}))
    out = ROOT_DIR / "ml" / "evaluation" / "topology_sizing_research.json"
    out.write_text(json.dumps({"results": results, "multiplier_stats": multiplier_stats, "decision": decision}, indent=2, default=float),
                   encoding="utf-8")
    print(f"written {out}")

    from evaluation.readme_research import refresh_readme_best_effort

    refresh_readme_best_effort()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
