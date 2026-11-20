"""One command from data to a verdict (V6.6.10): `aq pipeline run` for any project, `aq init`'s template or no project at all.

A pipeline is a short TOML file. Its stages run in order and each records its result in `<runs>/<run id>/state.json`, so a run
stopped by a reboot continues where it was:

    data      the closes: the bundled sample, or a wide CSV (a date column, one column per ticker)
    signal    your `score(closes)` from the signal file: a dates x tickers table, higher = expected to do better
    train     optional: a small model trained on the same closes (the example-model recipe, `--memory-profile low`), scored too
    evaluate  each signal's alpha report: IC by horizon, half-life, the long-short spread after costs, breadth
    gate      the thresholds the file wrote before the run: IC and its t at the gate horizon
    report    report.json and report.md in the run folder

    [pipeline]
    name = "my-signal"
    data = "sample"            # or "data/closes.csv"
    signal = "my_signal.py"
    train = false              # true: also train and score a small model

    [gate]
    horizon = 20
    min_ic = 0.02
    min_t = 2.0
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

STAGES = ("data", "signal", "train", "evaluate", "gate", "report")
DEFAULTS: dict[str, Any] = {
    "pipeline": {"name": "pipeline", "data": "sample", "signal": "my_signal.py", "train": False, "cost_bps": 10.0},
    "gate": {"horizon": 20, "min_ic": 0.02, "min_t": 2.0},
}
SMOKE_SIGNAL = "momentum_20"


def load_pipeline(path: Path | None) -> dict[str, Any]:
    """The pipeline file merged over the defaults; no file is the defaults (the bundled sample and 20-session momentum)."""
    spec = {section: dict(values) for section, values in DEFAULTS.items()}
    if path is None:
        spec["pipeline"]["signal"] = SMOKE_SIGNAL
        return spec
    if sys.version_info < (3, 11):
        raise ValueError("a pipeline file needs Python 3.11 or newer (tomllib); without a file, the defaults run on 3.10")
    import tomllib  # novermin  (guarded above: the library itself runs on 3.10)

    loaded = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    for section, values in loaded.items():
        spec.setdefault(section, {}).update(values)
    spec["root"] = str(Path(path).resolve().parent)
    return spec


def load_closes(source: str, *, root: Path) -> pd.DataFrame:
    """`sample` is the library's bundled sample; anything else a wide CSV, relative to the pipeline file."""
    if source == "sample":
        from aether_quant.samples import load_sample_prices

        return load_sample_prices()
    closes = pd.read_csv(root / source, index_col=0)
    closes.index = closes.index.astype(str)
    return closes.astype(float)


def momentum_20(closes: pd.DataFrame) -> pd.DataFrame:
    """The smoke run's signal: the return over the last 20 sessions."""
    return closes.pct_change(20, fill_method=None)


def load_signal(reference: str, *, root: Path) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """The `score` function of a signal file (relative to the pipeline file), or the built-in smoke signal."""
    if reference == SMOKE_SIGNAL:
        return momentum_20
    path = root / reference
    spec = importlib.util.spec_from_file_location(f"aq_pipeline_signal_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"no signal file at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "score", None)):
        raise AttributeError(f"{path.name} defines no score(closes)")
    return module.score


def gate_verdict(report: Mapping[str, Any], gate: Mapping[str, Any]) -> dict[str, Any]:
    """Pass iff the IC at the gate horizon and its Newey-West t both reach the thresholds the file set before the run."""
    horizon = int(gate["horizon"])
    row = report.get("term_structure", {}).get(horizon) or report.get("term_structure", {}).get(str(horizon)) or {}
    ic, t_stat = row.get("mean_ic"), row.get("t_hac")
    passed = ic is not None and t_stat is not None and ic >= float(gate["min_ic"]) and t_stat >= float(gate["min_t"])
    return {"passed": bool(passed), "horizon": horizon, "mean_ic": ic, "t_hac": t_stat, "min_ic": float(gate["min_ic"]), "min_t": float(gate["min_t"])}


def run_stages(stages: Sequence[str], actions: Mapping[str, Callable[[], Any]], *, state_path: Path, emit: Callable[[str], None] = print) -> dict:
    """Each stage once: a finished stage is skipped on a rerun, a failed one reruns. The state is written after every stage."""
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"done": {}}
    for stage in stages:
        if stage in state["done"]:
            emit(f"{stage}: done before, skipped")
            continue
        emit(f"{stage}: running")
        result = actions[stage]()
        state["done"][stage] = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "result": result}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")
    return state


def _wide(long: pd.DataFrame) -> pd.DataFrame:
    return long.pivot(index="date", columns="ticker", values="score").sort_index()


def pipeline_actions(spec: Mapping[str, Any], *, run_dir: Path, train_model: Callable[..., pd.DataFrame] | None = None) -> dict[str, Callable[[], Any]]:
    """The stage functions of one run. `train_model(closes, work)` returns long model scores; the default trains the example multitask
    network (torch, `--memory-profile low`) and is only imported when the file asks for it."""
    from evaluation.alpha_behaviour import alpha_report

    root = Path(spec.get("root", "."))
    settings, gate = spec["pipeline"], spec["gate"]
    paths = {"closes": run_dir / "closes.csv", "signal": run_dir / "signal.csv", "model": run_dir / "model_scores.csv", "evaluate": run_dir / "evaluate.json"}

    def data() -> dict:
        closes = load_closes(str(settings["data"]), root=root)
        run_dir.mkdir(parents=True, exist_ok=True)
        closes.to_csv(paths["closes"], index_label="date")
        return {"sessions": int(len(closes)), "tickers": int(closes.shape[1]), "first": str(closes.index[0]), "last": str(closes.index[-1])}

    def closes() -> pd.DataFrame:
        frame = pd.read_csv(paths["closes"], index_col=0)
        frame.index = frame.index.astype(str)
        return frame

    def signal() -> dict:
        table = load_signal(str(settings["signal"]), root=root)(closes())
        long = table.stack(future_stack=True).rename("score").reset_index()
        long.columns = ["date", "ticker", "score"]
        long.dropna().to_csv(paths["signal"], index=False)
        return {"rows": int(long["score"].notna().sum())}

    def train() -> dict:
        if not settings.get("train"):
            return {"skipped": "train = false"}
        trainer = train_model or train_example_model
        scores = trainer(closes(), run_dir / "model")
        scores.to_csv(paths["model"], index=False)
        return {"rows": int(len(scores))}

    def evaluate() -> dict:
        prices = closes()
        groups = dict.fromkeys(prices.columns, "all")
        reports = {}
        for name, path in (("signal", paths["signal"]), ("model", paths["model"])):
            if path.exists():
                report = alpha_report(_wide(pd.read_csv(path, dtype={"date": str})).reindex(index=prices.index), prices, groups=groups,
                                      factors={"momentum_20": momentum_20(prices)}, horizon=int(gate["horizon"]), cost_bps=float(settings.get("cost_bps", 10.0)))
                reports[name] = report
        paths["evaluate"].write_text(json.dumps(reports, indent=1, default=str), encoding="utf-8")
        return {name: report["term_structure"][int(gate["horizon"])] for name, report in reports.items()}

    def gate_stage() -> dict:
        reports = json.loads(paths["evaluate"].read_text(encoding="utf-8"))
        return {name: gate_verdict(report, gate) for name, report in reports.items()}

    def report() -> str:
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        verdicts = state["done"]["gate"]["result"]
        summary = {"name": settings["name"], "data": state["done"]["data"]["result"], "gate": verdicts}
        (run_dir / "report.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
        lines = [f"# {settings['name']}", "", f"Data: {summary['data']}", ""]
        lines += [f"- **{name}**: {'PASS' if v['passed'] else 'FAIL'} - IC {v['mean_ic']} (t {v['t_hac']}) at {v['horizon']} sessions; needs IC >= {v['min_ic']}, t >= {v['min_t']}"
                  for name, v in verdicts.items()]
        (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(run_dir / "report.md")

    return {"data": data, "signal": signal, "train": train, "evaluate": evaluate, "gate": gate_stage, "report": report}


def train_example_model(closes: pd.DataFrame, work: Path) -> pd.DataFrame:
    """The example multitask network trained on these closes (the example-model recipe), scored on them."""
    from retraining import model_catalog as catalog

    root = Path(__file__).resolve().parents[1]
    if not (root / "scripts" / "build_example_models.py").exists():
        raise FileNotFoundError("`train = true` trains with the project's trainers: run it from a source checkout (pip install -e \".[train]\")")
    spec = importlib.util.spec_from_file_location("aq_build_example_models", root / "scripts" / "build_example_models.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    work.mkdir(parents=True, exist_ok=True)
    frame = catalog.example_dataset(closes)
    frame.to_csv(work / "dataset.csv", index=False)
    (work / "schema.json").write_text(json.dumps({"model_input_names": list(catalog.FEATURES)}), encoding="utf-8")
    (work / "config.json").write_text(json.dumps(builder.training_config(json.loads((root / "config.json").read_text(encoding="utf-8")))), encoding="utf-8")
    version = builder.train("multitask", work=work, config_path=work / "config.json", dataset=work / "dataset.csv", schema=work / "schema.json")
    return catalog.score(catalog.load(version), closes)
