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
import subprocess
import sys
import time as _time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.research_cycle import ram_preflight, retrain_stages  # noqa: E402

STATE_ROOT = ROOT / "ml" / "cycle"
CODESPACE = "aq-Training-Ground-Fixed"
REMOTE_REPO = "/workspaces/Aether-quant"
# What a procedure trains. Adding one is a code change, visible in git: a retrain has no free-form command.
PROCEDURES: dict[str, dict] = {
    "k06": {"model": "gbm_monotone", "variant": "a", "seeds": "1,2,3", "feature_set": "fundamental", "train_start": "2011-07-01", "first_test_year": 2013, "purge_days": 31},
    "k07": {"model": "mlp_multitask", "variant": "a", "seeds": "1,2,3,4,5", "feature_set": "fundamental", "train_start": "2011-07-01", "first_test_year": 2013, "purge_days": 31},
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


def trainer_command(python: str, name: str, procedure: Mapping, *, panel: str, out: str, score_end: str | None = None) -> list[str]:
    command = [
        python, "train_cross_sectional.py", "--panel", panel, "--model", str(procedure["model"]), "--variant", str(procedure["variant"]), "--seeds", str(procedure["seeds"]),
        "--feature-set", str(procedure["feature_set"]), "--train-start", str(procedure["train_start"]), "--first-test-year", str(procedure["first_test_year"]), "--purge-days", str(procedure["purge_days"]), "--out", out,
    ]
    return [*command, "--score-end", score_end] if score_end else command


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
        go("scripts/build_wide_root.py")
        go("scripts/build_wide_info.py")
        return "built data_wide from public sources"

    def refresh() -> str:
        return go("scripts/data_append_refresh.py", "--apply")

    def build_panel() -> str:
        return go("scripts/v660_build_panel.py", "TA", "--out", panel) if not (ROOT / panel).exists() else "panel present"

    def walk() -> str:
        return _run(trainer_command(python, name, procedure, panel=panel, out=str(scores)), runner=runner)

    def score() -> dict:
        if not scores.exists():
            raise RuntimeError(f"{scores} was not written")
        return {"scores": str(scores.relative_to(ROOT)) if scores.is_relative_to(ROOT) else str(scores), "sha256": hashlib.sha256(scores.read_bytes()).hexdigest()}

    def gate() -> str:
        return "a refit keeps its procedure's verdict; a new procedure needs `aq cycle research`: nothing is promoted here"

    def register() -> dict:
        trainer = (ROOT / "train_cross_sectional.py").read_bytes()
        return {"procedure": name, "procedure_sha256": procedure_sha256(name, procedure, trainer), "vintage": run_dir.name}

    def report() -> str:
        return str(run_dir)

    return {"bootstrap_data": bootstrap, "refresh_data": refresh, "build_panel": build_panel, "walk_forward": walk, "score": score, "round": gate, "register": register, "report": report}


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


def remote_command(name: str, *, run_id: str, smoke: bool = False) -> list[str]:
    """What runs over there: this same script, as a local run on that machine. The argv holds no quote or space, since Windows OpenSSH strips quotes from a command line."""
    flags = ["--smoke"] if smoke else ["--procedure", name]
    return ["python3", f"{REMOTE_REPO}/scripts/cycle_retrain.py", "--host", "local", *flags, "--run-id", run_id, "--on-codespace"]


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
    gh: Sequence[str] = ("gh", "codespace"), scratch: Path | None = None, sleep: Callable[[float], None] = _time.sleep, attempts: int = 6,
) -> dict:
    """Start, push the code, run, pull, and stop in a `finally`: a Codespace left running bills the owner, so stopping doesn't depend on the run going well."""
    work = Path(scratch) if scratch else STATE_ROOT / f"retrain_{run_id}"
    work.mkdir(parents=True, exist_ok=True)
    codespace = resolve_codespace(codespace, gh=gh, runner=runner)
    try:
        wait_until_reachable(codespace, gh=gh, runner=runner, sleep=sleep)
        _run(["powershell", "-NoProfile", "-File", "scripts/codespace_sync.ps1", "-Mode", "push", "-CodeOnly", "-Codespace", codespace], runner=runner)
        emit("code pushed")
        # The VM reboots about hourly, which drops this session. Stages resume, so another attempt continues the run.
        for attempt in range(1, attempts + 1):
            try:
                emit(_run([*gh, "ssh", "-c", codespace, "--", *remote_command(name, run_id=run_id, smoke=smoke)], runner=runner))
                break
            except RuntimeError as error:
                if attempt == attempts:
                    raise
                emit(f"attempt {attempt} ended: {str(error)[:200]}; resuming")
                wait_until_reachable(codespace, gh=gh, runner=runner, sleep=sleep)
        # `gh codespace cp` quotes a remote path, which Windows' scp reads literally, so the state comes back over ssh.
        state = _run_full([*gh, "ssh", "-c", codespace, "--", "cat", f"{REMOTE_REPO}/ml/cycle/retrain_{run_id}/state.json"], runner=runner)
        (work / "state.json").write_text(state, encoding="utf-8", newline="\n")
        return {"ran": True, "state": load_state(work / "state.json")}
    finally:
        result = runner([*gh, "stop", "-c", codespace], cwd=str(ROOT), capture_output=True, text=True)
        emit(f"Codespace stop exit {result.returncode}")
        if result.returncode != 0:
            # It bills while it runs, so this must not pass quietly.
            print(f"THE CODESPACE {codespace} DID NOT STOP: gh codespace stop -c {codespace} ({(result.stderr or '')[-200:]})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", choices=["local", "codespace"], required=True)
    parser.add_argument("--procedure", default=None, choices=sorted(PROCEDURES))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--min-ram-gb", type=float, default=14.0)
    parser.add_argument("--dry-run", action="store_true", help="print the stages and the preflight, and stop")
    parser.add_argument("--on-codespace", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.smoke and not args.procedure:
        parser.error("name a --procedure, or run --smoke")
    run_id = args.run_id or f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%d}_{uuid.uuid4().hex[:6]}"
    run_dir = STATE_ROOT / f"retrain_{run_id}"
    state_path = run_dir / "state.json"
    name = "smoke" if args.smoke else args.procedure
    procedure = PROCEDURES.get(name, PROCEDURES["k06"])
    preflight = ram_preflight(args.host, min_gb=args.min_ram_gb)
    data_present = args.smoke or (ROOT / "data_wide" / "wide_manifest.json").exists()
    stages = retrain_stages(data_present=data_present)
    print(json.dumps({"run": run_id, "host": args.host, "procedure": name, "smoke": args.smoke, "preflight": preflight, "stages": stages}, indent=1))
    if args.dry_run:
        return 0 if (preflight["ok"] or args.smoke) else 2
    if args.host == "codespace":
        drive_codespace(name, procedure, run_id=run_id, smoke=args.smoke)
        return 0
    if not preflight["ok"] and not args.smoke and not args.on_codespace:
        print(f"refusing: {preflight['reason']}", file=sys.stderr)
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)
    actions = smoke_actions(run_dir=run_dir) if args.smoke else local_actions(name, procedure, run_dir=run_dir)
    run_stages(stages, actions, state_path=state_path)
    print(f"done: {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
