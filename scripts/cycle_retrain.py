"""A retrain anyone can run (V6.6.1): the same stages on this machine or on the training Codespace, resumable after a reboot, every stage logged.

    python scripts/cycle_retrain.py --host local --procedure k06              # a machine with the RAM; builds its own data if it has none
    python scripts/cycle_retrain.py --host codespace --procedure k06          # drives the training Codespace from here, and stops it however the run ends
    python scripts/cycle_retrain.py --host local --smoke                      # every stage on a tiny synthetic panel: proves the plumbing on any machine

A refit of a frozen procedure adds a vintage to its generation. A new procedure is a candidate: it goes through a research round first, and this script only writes its scores for that round.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time as _time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.research_cycle import ram_preflight, retrain_stages, stack_plan, stack_stages, validate_plan_flags  # noqa: E402
from retraining import run_resume  # noqa: E402

CONTACT_ENV = "AQ_SEC_CONTACT"
STATE_ROOT = ROOT / "ml" / "cycle"
CODESPACE = "aq-Training-Ground-Fixed"
REMOTE_REPO = "/workspaces/Aether-quant"
# What a procedure trains. Adding one is a code change, visible in git: a retrain has no free-form command.
PROCEDURES: dict[str, dict] = {
    "k06": {"model": "gbm_monotone", "variant": "a", "seeds": "1,2,3", "feature_set": "fundamental", "train_start": "2011-07-01", "first_test_year": 2013, "purge_days": 31},
    "k07": {"model": "mlp_multitask", "variant": "a", "seeds": "1,2,3,4,5", "feature_set": "fundamental", "train_start": "2011-07-01", "first_test_year": 2013, "purge_days": 31},
    # V6.6.9: the model stack (`ml/`'s multitask, sequence and gating models) as one procedure. `stack` is the installed recipe, so a refit is a new vintage of
    # its generation (g0006); `stack_asof` (as-of labels, within-class ranked inputs) is a new procedure and only writes scores for a research round.
    "stack": {"kind": "stack", "mode": "expanding", "trainers": ["train.py", "train_multitask.py", "train_sequence.py", "train_gating.py"]},
    "stack_asof": {"kind": "stack", "mode": "expanding", "asof_labels": True, "trainers": ["train.py", "train_multitask.py", "train_sequence.py", "train_gating.py"]},
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def load_state(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {"done": {}}


def save_state(path: Path, state: Mapping) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    temporary.replace(path)


def run_stages(stages: Sequence[str], actions: Mapping[str, Callable[[], object]], *, state_path: Path, emit: Callable[[str], None] = print) -> dict:
    """Runs what isn't done yet, saving after each stage, so a reboot costs one stage at most. A failed stage stops the run: a later stage must not read a half-built result."""
    state = load_state(state_path)
    for stage in stages:
        if stage in state["done"]:
            emit(f"{stage}: already done")
            continue
        emit(f"{stage}: running")
        result = actions[stage]()
        state["done"][stage] = {"at": _now(), "result": result if isinstance(result, (str, int, float, dict, list, type(None))) else str(result)}
        save_state(state_path, state)
    return state


def procedure_sha256(name: str, procedure: Mapping, trainer_source: bytes) -> str:
    """What makes two fits the same generation: the trainer's code and every setting, not the weights they produce."""
    return hashlib.sha256(trainer_source + json.dumps({"name": name, **procedure}, sort_keys=True).encode("utf-8")).hexdigest()


def register_vintage(registry_path: Path, lifecycle_path: Path, procedure_sha: str, vintage: str, *, created_at: str) -> dict:
    """A refit of a frozen procedure is a new vintage of its generation (Problems #321): the vintage name goes on the generation whose `procedure_sha256` this is, with a hash-chained lifecycle
    row. A procedure no generation holds is a candidate and has no vintage to add: it goes through `aq cycle research` first. A vintage is added once."""
    from dataclasses import replace

    from evaluation.generation_registry import append_lifecycle, load_registry, save_registry

    if not Path(registry_path).exists():
        return {"added": False, "reason": "no registry"}
    registry = load_registry(Path(registry_path))
    owner = next((generation for generation in registry.values() if generation.procedure_sha256 == procedure_sha), None)
    if owner is None:
        return {"added": False, "reason": "no generation holds this procedure: it is a candidate, and goes through a research round first"}
    if vintage in owner.vintages:
        return {"added": False, "generation": owner.id, "reason": "this vintage is already recorded"}
    registry[owner.id] = replace(owner, vintages=(*owner.vintages, vintage))
    save_registry(Path(registry_path), registry)
    append_lifecycle(Path(lifecycle_path), event="vintage_added", created_at=created_at, payload={"generation": owner.id, "vintage": vintage, "procedure_sha256": procedure_sha})
    return {"added": True, "generation": owner.id}


def sync_shell() -> str:
    """The PowerShell that runs scripts/codespace_sync.ps1: `pwsh` where it exists, else Windows PowerShell. Anywhere else the push script can't run, and that is said plainly."""
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        raise RuntimeError("scripts/codespace_sync.ps1 needs PowerShell (pwsh or powershell on PATH); run the retrain on the Codespace itself with --host local --on-codespace")
    return shell


def trainer_command(python: str, name: str, procedure: Mapping, *, panel: str, out: str, score_end: str | None = None, year_cache: str | None = None) -> list[str]:
    """The cross-sectional trainer's command; `year_cache` keeps each test year's scores so a resumed walk-forward continues at its next year."""
    command = [
        python, "train_cross_sectional.py", "--panel", panel, "--model", str(procedure["model"]), "--variant", str(procedure["variant"]), "--seeds", str(procedure["seeds"]),
        "--feature-set", str(procedure["feature_set"]), "--train-start", str(procedure["train_start"]), "--first-test-year", str(procedure["first_test_year"]), "--purge-days", str(procedure["purge_days"]), "--out", out,
    ]
    command = [*command, "--score-end", score_end] if score_end else command
    return [*command, "--year-cache", year_cache] if year_cache else command


def _run_full(command: Sequence[str], *, cwd: Path = ROOT, runner: Callable = subprocess.run) -> str:
    """A failed step stops the run with what it said. The command is logged by name, and an environment value is never on it."""
    result = runner(list(command), cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{command[0]} {' '.join(command[1:3])} exit {result.returncode}: {(result.stderr or result.stdout or '')[-800:]}")
    return result.stdout or ""


def _run(command: Sequence[str], *, cwd: Path = ROOT, runner: Callable = subprocess.run) -> str:
    return _run_full(command, cwd=cwd, runner=runner)[-400:]


def local_actions(name: str, procedure: Mapping, *, run_dir: Path, python: str = sys.executable, runner: Callable = subprocess.run) -> dict[str, Callable[[], object]]:
    panel = "data_wide/reference/panel_TA.parquet"
    scores = run_dir / f"{name}.csv"

    def go(*command: str) -> str:
        return _run([python, *command], runner=runner)

    def bootstrap() -> str:
        if not os.environ.get(CONTACT_ENV, "").strip():
            raise RuntimeError(f"bootstrap_data builds EDGAR fundamentals, which SEC refuses without a contact: set {CONTACT_ENV} for this run (it is never stored)")
        go("scripts/build_wide_root.py")
        go("scripts/build_wide_info.py")
        return "built data_wide from public sources"

    def refresh() -> str:
        return go("scripts/data_append_refresh.py", "--apply")

    def build_panel() -> str:
        return go("scripts/v660_build_panel.py", "TA", "--out", panel) if not (ROOT / panel).exists() else "panel present"

    def walk() -> str:
        return _run(trainer_command(python, name, procedure, panel=panel, out=str(scores), year_cache=str(run_dir / "years")), runner=runner)

    def score() -> dict:
        if not scores.exists():
            raise RuntimeError(f"{scores} was not written")
        return {"scores": str(scores.relative_to(ROOT)) if scores.is_relative_to(ROOT) else str(scores), "sha256": hashlib.sha256(scores.read_bytes()).hexdigest()}

    def gate() -> str:
        return "a refit keeps its procedure's verdict; a new procedure needs `aq cycle research`: nothing is promoted here"

    def register() -> dict:
        trainer = (ROOT / "train_cross_sectional.py").read_bytes()
        sha = procedure_sha256(name, procedure, trainer)
        recorded = register_vintage(ROOT / "ml" / "generations" / "registry.json", ROOT / "ml" / "generations" / "lifecycle.jsonl", sha, run_dir.name, created_at=_now())
        return {"procedure": name, "procedure_sha256": sha, "vintage": run_dir.name, "registered": recorded}

    def report() -> str:
        return str(run_dir)

    return {"bootstrap_data": bootstrap, "refresh_data": refresh, "build_panel": build_panel, "walk_forward": walk, "score": score, "round": gate, "register": register, "report": report}


def stack_actions(
    name: str, procedure: Mapping, *, run_dir: Path, run_id: str, python: str = sys.executable, runner: Callable = subprocess.run, score_end: str | None = None,
    profile: str = "standard", resume_walk_forward: str | None = None,
) -> dict[str, Callable[[], object]]:
    """The model stack's stages (`evaluation.research_cycle.stack_plan`): each a command from the plan, or one of three that run here. The walk-forward's run id is read
    from its own output, so `scores` knows which windows to score."""
    import re

    from retraining.artifact_pins import snapshot_active, write_artifact_pins

    plan = dict(stack_plan(procedure, run_id=run_id, python=python, score_end=score_end, profile=profile, resume_id=resume_walk_forward))
    # a walk-forward stopped part way continues its own windows (V6.6.10): the scores stage reads that run
    found: dict[str, str] = {"walk_forward": resume_walk_forward} if resume_walk_forward else {}

    def command_stage(stage: str) -> Callable[[], object]:
        def run() -> object:
            command = plan[stage]
            if command is None:
                return "skipped: pass --score-end, the last date the next round may read"
            if stage == "scores":
                command = [*command[:3], found["walk_forward"], *command[4:]]
            output = _run_full(command, runner=runner)
            if stage == "walk_forward":
                # the id is logged to stderr at the start and printed to stdout at the end ("Walk-forward run <id>: ..."); a resumed run knows it already
                match = re.search(r"(walk-forward-[0-9a-f][0-9a-f-]+)", output)
                if match is None and "walk_forward" not in found:
                    raise RuntimeError("the walk-forward printed no run id; its windows cannot be found")
                if match is not None:
                    found["walk_forward"] = match.group(1)
            return output[-400:]

        return run

    def snapshot() -> str:
        return str(snapshot_active(ROOT / "ml", ROOT / "ml" / "backups" / f"pre_retrain_{run_id}.zip"))

    def pins() -> dict:
        return write_artifact_pins(ROOT / "ml" / "versions" / f"{run_id}_base", run_dir / "artifact_pins.json")

    def register() -> dict:
        source = b"".join((ROOT / trainer).read_bytes() for trainer in procedure["trainers"])
        sha = procedure_sha256(name, procedure, source)
        recorded = register_vintage(ROOT / "ml" / "generations" / "registry.json", ROOT / "ml" / "generations" / "lifecycle.jsonl", sha, run_id, created_at=_now())
        return {"procedure": name, "procedure_sha256": sha, "vintage": run_id, "registered": recorded}

    actions = {stage: command_stage(stage) for stage in stack_stages()}
    actions.update(snapshot_active=snapshot, pins=pins, register=register, report=lambda: str(run_dir))
    return actions


def memory_estimate(dataset: Path, config_path: Path, *, schema: Path | None = None) -> dict:
    """Each memory profile's estimated peak for the sequence stage (the stack's largest) on this dataset, and this machine's RAM: what
    `--estimate` prints before anyone spends a night on a run that cannot fit."""
    from evaluation.research_cycle import GIB, total_memory_bytes
    from retraining.slicing import PROFILES, estimate_peak_gb

    if not dataset.exists():
        return {"dataset": str(dataset), "error": "no dataset: build one first (train.py --dataset-only)"}
    with dataset.open("rb") as handle:
        columns = len(handle.readline().split(b","))
        rows = sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 22), b""))
    schema = schema or dataset.parents[1] / "feature_schema.json"
    features = len(json.loads(schema.read_text(encoding="utf-8"))["model_input_names"]) if schema.exists() else columns
    window = int(json.loads(config_path.read_text(encoding="utf-8"))["phase_v2"]["retraining"]["sequence_training"].get("window_size", 30))
    total = total_memory_bytes()
    return {
        "dataset": str(dataset), "rows": rows, "columns": columns, "features": features, "window": window,
        "machine_gb": None if total is None else round(total / GIB, 1),
        "estimated_peak_gb": {name: estimate_peak_gb(rows, columns, features, window=window, profile=name) for name in PROFILES},
    }


def smoke_panel(path: Path, *, seed: int = 3) -> None:
    """A tiny synthetic panel: three years, 40 names, a planted signal. Small enough for any machine."""
    import numpy as np
    import pandas as pd

    from train_cross_sectional import FUNDAMENTAL_SIGNS

    rng = np.random.default_rng(seed)
    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2012-01-02", "2014-12-31", freq="5B")]
    tickers = [f"T{index:02d}" for index in range(40)]
    rows = []
    for date in dates:
        block = {name: rng.normal(size=len(tickers)) for name in FUNDAMENTAL_SIGNS}
        signal = sum(sign * block[name] for name, sign in FUNDAMENTAL_SIGNS.items()) / len(FUNDAMENTAL_SIGNS)
        label = signal + rng.normal(scale=0.3, size=len(tickers))
        label = (pd.Series(label).rank(pct=True) - 0.5).to_numpy()
        rows.append(pd.DataFrame({"date": date, "ticker": tickers, "sector": "tech", "target_wide_20d": label, **block}))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pd.concat(rows, ignore_index=True).to_parquet(path)


def smoke_actions(*, run_dir: Path, python: str = sys.executable, runner: Callable = subprocess.run) -> dict[str, Callable[[], object]]:
    """Every stage on the synthetic panel with the small tree model: no real data read, no download."""
    panel = run_dir / "panel.parquet"
    scores = run_dir / "smoke.csv"
    procedure = {**PROCEDURES["k06"], "seeds": "1", "train_start": "2012-01-01", "first_test_year": 2014, "purge_days": 20}

    def build() -> str:
        smoke_panel(panel)
        return str(panel.name)

    def walk() -> str:
        return _run(trainer_command(python, "smoke", procedure, panel=str(panel), out=str(scores)), runner=runner)

    def score() -> dict:
        import pandas as pd

        frame = pd.read_csv(scores)
        if frame.empty or not frame["score"].notna().all():
            raise RuntimeError("the smoke run wrote no usable scores")
        return {"rows": int(len(frame)), "sha256": hashlib.sha256(scores.read_bytes()).hexdigest()}

    return {
        "bootstrap_data": lambda: "skipped: a synthetic panel", "refresh_data": lambda: "skipped: a synthetic panel", "build_panel": build, "walk_forward": walk, "score": score,
        "round": lambda: "skipped: a synthetic panel earns no verdict", "register": lambda: "skipped: a synthetic panel is no generation", "report": lambda: str(run_dir.name),
    }


def remote_command(name: str, *, run_id: str, smoke: bool = False, resume: bool = False) -> list[str]:
    """What runs over there: this same script, as a local run on that machine. The argv holds no quote or space, since Windows OpenSSH strips quotes from a command line.
    `resume` (V6.6.10): continue that machine's own run folder (its resume.json and walk_forward_run_id), so a stopped walk-forward keeps its windows."""
    flags = ["--smoke"] if smoke else ["--procedure", name]
    return ["python3", f"{REMOTE_REPO}/scripts/cycle_retrain.py", "--host", "local", *flags, "--run-id", run_id, "--on-codespace", *(["--resume", run_id] if resume else [])]


def resolve_codespace(name: str, *, gh: Sequence[str] = ("gh", "codespace"), runner: Callable = subprocess.run) -> str:
    """`gh codespace ... -c` wants the generated name; the training Codespace is known by its display name."""
    result = runner([*gh, "list", "--json", "name,displayName"], cwd=str(ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh codespace list exit {result.returncode}: {(result.stderr or '')[-300:]}")
    for entry in json.loads(result.stdout or "[]"):
        if name in (entry.get("name"), entry.get("displayName")):
            return str(entry["name"])
    raise RuntimeError(f"no Codespace named or titled {name!r} (gh codespace list)")


def wait_until_reachable(
    codespace: str, *, gh: Sequence[str] = ("gh", "codespace"), runner: Callable = subprocess.run, sleep: Callable[[float], None] = _time.sleep, attempts: int = 40, pause_seconds: float = 15.0,
) -> None:
    """A Codespace stopped a moment ago answers nothing until it has shut down, and a push would then report only that it found no repo. `ssh` starts a stopped one."""
    for _ in range(attempts):
        listed = runner([*gh, "list", "--json", "name,state"], cwd=str(ROOT), capture_output=True, text=True)
        states = {entry.get("name"): entry.get("state") for entry in json.loads(listed.stdout or "[]")} if listed.returncode == 0 else {}
        if states.get(codespace) in ("Available", "Shutdown"):
            probe = runner([*gh, "ssh", "-c", codespace, "--", "test", "-f", "/workspaces/Aether-quant/train.py"], cwd=str(ROOT), capture_output=True, text=True)
            if probe.returncode == 0:
                return
        sleep(pause_seconds)
    raise RuntimeError(f"{codespace} did not become reachable")


def drive_codespace(
    name: str, procedure: Mapping, *, run_id: str, smoke: bool, codespace: str = CODESPACE, runner: Callable = subprocess.run, emit: Callable[[str], None] = print,
    gh: Sequence[str] = ("gh", "codespace"), scratch: Path | None = None, sleep: Callable[[float], None] = _time.sleep, attempts: int = 6, resume: bool = False,
) -> dict:
    """Start, push the code, run, pull, and stop in a `finally`: a Codespace left running bills the owner, so stopping doesn't depend on the run going well."""
    work = Path(scratch) if scratch else STATE_ROOT / f"retrain_{run_id}"
    work.mkdir(parents=True, exist_ok=True)
    codespace = resolve_codespace(codespace, gh=gh, runner=runner)
    try:
        wait_until_reachable(codespace, gh=gh, runner=runner, sleep=sleep)
        _run([sync_shell(), "-NoProfile", "-File", "scripts/codespace_sync.ps1", "-Mode", "push", "-CodeOnly", "-Codespace", codespace], runner=runner)
        emit("code pushed")
        # The VM reboots about hourly, which drops this session. Stages resume, so another attempt continues the run.
        for attempt in range(1, attempts + 1):
            try:
                # every attempt after the first (the VM rebooted mid-run) continues the run there, as `--resume` does
                emit(_run([*gh, "ssh", "-c", codespace, "--", *remote_command(name, run_id=run_id, smoke=smoke, resume=resume or attempt > 1)], runner=runner))
                break
            except RuntimeError as error:
                if attempt == attempts:
                    raise
                emit(f"attempt {attempt} ended: {str(error)[:200]}; resuming")
                wait_until_reachable(codespace, gh=gh, runner=runner, sleep=sleep)
        # `gh codespace cp` quotes a remote path, which Windows' scp reads literally, so the state comes back over ssh.
        state = _run_full([*gh, "ssh", "-c", codespace, "--", "cat", f"{REMOTE_REPO}/ml/cycle/retrain_{run_id}/state.json"], runner=runner)
        (work / "state.json").write_text(state, encoding="utf-8", newline="\n")
        pulled = load_state(work / "state.json")
        # the scores are the point of a retrain and they stayed on the Codespace: bring them back the same way, so a stopped Codespace loses nothing
        scores_file = (((pulled.get("done") or {}).get("score") or {}).get("result") or {}).get("scores")
        if scores_file:
            remote = scores_file if scores_file.startswith("/") else f"{REMOTE_REPO}/{scores_file}"
            text = _run_full([*gh, "ssh", "-c", codespace, "--", "cat", remote], runner=runner)
            (work / Path(scores_file).name).write_text(text, encoding="utf-8", newline="\n")
            emit(f"scores pulled: {work / Path(scores_file).name}")
        return {"ran": True, "state": pulled}
    finally:
        result = runner([*gh, "stop", "-c", codespace], cwd=str(ROOT), capture_output=True, text=True)
        emit(f"Codespace stop exit {result.returncode}")
        if result.returncode != 0:
            # It bills while it runs, so this must not pass quietly.
            print(f"THE CODESPACE {codespace} DID NOT STOP: gh codespace stop -c {codespace} ({(result.stderr or '')[-200:]})", file=sys.stderr)


RESUME_KEYS = ("host", "procedure", "smoke", "memory_profile", "score_end", "min_ram_gb")


def write_resume(run_dir: Path, args: argparse.Namespace, *, run_id: str) -> dict:
    """The run's resume record (V6.6.10): what `--resume` needs to continue it with the same settings, and where the snapshot
    of the installed models went. Written once when the run starts; the walk-forward adds its own run id beside it."""
    record = {"run_id": run_id, **{key: getattr(args, key) for key in RESUME_KEYS}, "started": _now(),
              "snapshot": str(ROOT / "ml" / "backups" / f"pre_retrain_{run_id}.zip")}
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "resume.json").write_text(json.dumps(record, indent=1), encoding="utf-8", newline="\n")
    return record


def find_resumable(state_root: Path, run_id: str | None = None) -> Path | None:
    """The run folder to continue: the named one, or the newest whose resume record exists and whose last stage has not run."""
    return run_resume.find_resumable(state_root, "retrain_", run_id, last_step="report")


def resume_args(args: argparse.Namespace, *, state_root: Path) -> argparse.Namespace | None:
    """`--resume [RUN_ID]`: the stopped run's own settings, its run id and the walk-forward it had started; None when there is none."""
    folder = find_resumable(state_root, None if args.resume == "latest" else args.resume)
    if folder is None:
        return None
    record = json.loads((folder / "resume.json").read_text(encoding="utf-8"))
    walk_forward = folder / "walk_forward_run_id"
    merged = argparse.Namespace(**{**vars(args), **{key: record.get(key) for key in RESUME_KEYS}, "run_id": record["run_id"]})
    merged.resume_walk_forward = args.resume_walk_forward or (walk_forward.read_text(encoding="utf-8").strip() if walk_forward.exists() else None)
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", choices=["local", "codespace"], default=None, help="required, except with --resume (the run's own) or --estimate")
    parser.add_argument("--procedure", default=None, choices=sorted(PROCEDURES))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--min-ram-gb", type=float, default=None, help="override the memory profile's minimum (standard 14, low 3.5)")
    parser.add_argument("--memory-profile", choices=["standard", "low"], default="standard", help="low: train the stack on a 4 GB machine, slower (V6.6.10)")
    parser.add_argument("--estimate", action="store_true", help="print each profile's estimated peak memory for the active dataset, and stop")
    parser.add_argument("--dry-run", action="store_true", help="print the stages and the preflight, and stop")
    parser.add_argument("--score-end", default=None, help="a stack run: the last date of the walk-forward scores (the next research round's window)")
    parser.add_argument("--resume-walk-forward", default=None, metavar="RUN_ID", help="a stack run: continue this walk-forward run's windows instead of starting a new one")
    parser.add_argument("--resume", nargs="?", const="latest", default=None, metavar="RUN_ID",
                        help="continue a stopped run with its own settings (the newest unfinished one, or RUN_ID): finished stages are skipped, the walk-forward continues its windows, the sequence trainer its checkpoint")
    parser.add_argument("--list-runs", action="store_true", help="list every retrain and `aq train` run with a resume record: its finished stages and whether it can be resumed")
    parser.add_argument("--on-codespace", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.list_runs:
        print(run_resume.render_runs(run_resume.list_runs(STATE_ROOT, ["retrain_", "train_"], last_step="report")))
        return 0
    if args.resume:
        resumed = resume_args(args, state_root=STATE_ROOT)
        if resumed is None and (args.procedure or args.smoke) and args.run_id:
            # a retry whose first attempt never got to write its record: the settings came along, so the run starts now
            print(f"no resume record for {args.run_id} yet: starting it")
            resumed = args
        elif resumed is None:
            print("nothing to resume: no unfinished run with a resume record under " + str(STATE_ROOT), file=sys.stderr)
            return 1
        args = resumed
        print(f"resuming {args.run_id}" + (f" (walk-forward {args.resume_walk_forward})" if args.resume_walk_forward else ""))
    if args.host is None and not args.estimate:
        parser.error("name a --host, or --resume a run")
    if args.estimate:
        print(json.dumps(memory_estimate(ROOT / "ml" / "datasets" / "full_dataset.csv", ROOT / "config.json"), indent=1))
        return 0
    if not args.smoke and not args.procedure:
        parser.error("name a --procedure, or run --smoke")
    run_id = args.run_id or f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%d}_{uuid.uuid4().hex[:6]}"
    run_dir = STATE_ROOT / f"retrain_{run_id}"
    state_path = run_dir / "state.json"
    chosen = PROCEDURES.get(args.procedure) if args.procedure else None
    is_stack = chosen is not None and chosen.get("kind") == "stack"
    name = args.procedure if is_stack else ("smoke" if args.smoke else args.procedure)
    procedure = chosen if is_stack else PROCEDURES.get(name, PROCEDURES["k06"])
    preflight = ram_preflight(args.host, min_gb=args.min_ram_gb, profile=args.memory_profile)
    data_present = args.smoke or (ROOT / "data_wide" / "wide_manifest.json").exists()
    if args.smoke and args.procedure and is_stack:
        # a stack's plumbing is proved by its commands: every flag the plan passes is one its trainer lists
        problems = validate_plan_flags(
            stack_plan(procedure, run_id=run_id, python=sys.executable, score_end="2023-06-30", resume_id="walk-forward-smoke", profile=args.memory_profile), runner=subprocess.run,
        )
        print(json.dumps({"run": run_id, "procedure": name, "stages": stack_stages(), "flag_problems": problems}, indent=1))
        return 1 if problems else 0
    stages = stack_stages() if is_stack else retrain_stages(data_present=data_present)
    print(json.dumps({"run": run_id, "host": args.host, "procedure": name, "smoke": args.smoke, "memory_profile": args.memory_profile, "preflight": preflight, "stages": stages}, indent=1))
    if args.dry_run:
        return 0 if (preflight["ok"] or args.smoke) else 2
    if args.host == "codespace":
        if not (run_dir / "resume.json").exists():
            write_resume(run_dir, args, run_id=run_id)
        drive_codespace(name, procedure, run_id=run_id, smoke=args.smoke, resume=bool(args.resume))
        return 0
    if not preflight["ok"] and not args.smoke and not args.on_codespace:
        print(f"refusing: {preflight['reason']}", file=sys.stderr)
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)
    if not (run_dir / "resume.json").exists():
        write_resume(run_dir, args, run_id=run_id)
    if is_stack:
        actions = stack_actions(name, procedure, run_dir=run_dir, run_id=run_id, score_end=args.score_end, profile=args.memory_profile,
                                resume_walk_forward=args.resume_walk_forward)
    else:
        actions = smoke_actions(run_dir=run_dir) if args.smoke else local_actions(name, procedure, run_dir=run_dir)
    run_stages(stages, actions, state_path=state_path)
    print(f"done: {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
