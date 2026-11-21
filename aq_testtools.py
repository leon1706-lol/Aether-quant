"""Testing tools behind `aq test` and `aq bench`: the impacted tests, a watch loop, flaky-test repeats, the slowest tests,
a new module's test file, which tests cover a module, a clean checkout, mutation, fuzzing, and hot-path benchmarks.

`aq_cli.cmd_test` hands a run here when it is one of these modes. Every subprocess goes through `aq_devtools.RUN`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import aq_devtools as dev

ROOT_DIR = dev.ROOT_DIR
TEST_VERBS = ("new", "where", "slowest", "clean-checkout", "mutation", "fuzz")
JUNIT_LAST = Path("coverage-report") / "junit-last.xml"


# ---------------------------------------------------------------------------
# impacted tests and the watch loop
# ---------------------------------------------------------------------------


def impacted_tests() -> list[str]:
    """Registered test files that name a module changed since HEAD, plus changed registered test files."""
    import aq_cli

    changed = aq_cli._changed_python_files(dev.RUN)
    registered = {name for names in aq_cli._SUBSYSTEM_TEST_FILES.values() for name in names}
    chosen = set(aq_cli._tests_for_changed(changed, registered, lambda needle: aq_cli._git_grep_tests(needle, dev.RUN)))
    return sorted(chosen | (set(aq_cli._changed_test_files(dev.RUN)) & registered))


def source_mtimes(root: Path = ROOT_DIR) -> dict[str, float]:
    """{path: mtime} of every tracked or new .py file (what a save changes)."""
    code, out = dev.run_capture(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.py"], cwd=root)
    stamps = {}
    for line in out.splitlines() if code == 0 else []:
        path = root / line.strip()
        if path.exists():
            stamps[line.strip()] = path.stat().st_mtime
    return stamps


def watch(run_once: Callable[[], int], *, snapshot: Callable[[], Mapping[str, float]] = source_mtimes, sleep: Callable[[float], None] = time.sleep,
          interval: float = 1.0, debounce: float = 0.5, iterations: int | None = None) -> int:
    """Run `run_once`, then again after every change `snapshot` sees, until Ctrl-C (exit 130) or `iterations` reruns."""
    last = dict(snapshot())
    code = run_once()
    reruns = 0
    try:
        while iterations is None or reruns < iterations:
            sleep(interval)
            current = dict(snapshot())
            if current == last:
                continue
            sleep(debounce)
            last = dict(snapshot())
            changed = sorted(path for path in set(current) | set(last) if current.get(path) != last.get(path)) or sorted(set(current) ^ set(last))
            print(f"\n== change detected ({len(changed) or 'some'} file(s)): rerunning", flush=True)
            code = run_once()
            reruns += 1
    except KeyboardInterrupt:
        print("\naq test --watch: stopped")
        return dev.EXIT_INTERRUPTED
    return code


# ---------------------------------------------------------------------------
# JUnit: repeats and the slowest tests
# ---------------------------------------------------------------------------


def parse_junit(path: Path) -> list[dict]:
    """[{file, name, seconds, outcome}] for every testcase of a JUnit XML file."""
    root = ElementTree.parse(path).getroot()
    cases = []
    for case in root.iter("testcase"):
        outcome = "passed"
        for child in case:
            if child.tag in {"failure", "error"}:
                outcome = "failed"
            elif child.tag == "skipped":
                outcome = "skipped"
        parts = case.get("classname", "").split(".")
        module = next((part for part in parts if part.startswith("test_")), parts[-1])  # tests.test_x (or tests.test_x.TestClass)
        file = case.get("file") or (f"{module}.py" if len(parts) > 1 else module)
        cases.append({"file": Path(file).name, "name": case.get("name", ""), "seconds": float(case.get("time") or 0.0), "outcome": outcome})
    return cases


def flaky_summary(runs: Sequence[Sequence[dict]]) -> dict:
    """Per test across repeated runs: passes, failures, and the flaky ones (both)."""
    table: dict[str, dict[str, int]] = {}
    for cases in runs:
        for case in cases:
            row = table.setdefault(f"{case['file']}::{case['name']}", {"passed": 0, "failed": 0})
            if case["outcome"] in row:
                row[case["outcome"]] += 1
    flaky = sorted(test for test, row in table.items() if row["passed"] and row["failed"])
    always = sorted(test for test, row in table.items() if row["failed"] and not row["passed"])
    return {"runs": len(runs), "tests": len(table), "flaky": flaky, "always_failing": always}


def slowest(cases: Sequence[dict], groups: Mapping[str, Sequence[str]], top: int = 15) -> dict:
    """The `top` slowest tests, and the total seconds per file and per test group."""
    by_file: dict[str, float] = {}
    for case in cases:
        by_file[case["file"]] = by_file.get(case["file"], 0.0) + case["seconds"]
    group_of = {name: group for group, names in groups.items() for name in names}
    by_group: dict[str, float] = {}
    for file, seconds in by_file.items():
        by_group[group_of.get(file, "(no group)")] = by_group.get(group_of.get(file, "(no group)"), 0.0) + seconds
    return {
        "tests": [{**case} for case in sorted(cases, key=lambda case: -case["seconds"])[:top]],
        "files": dict(sorted(by_file.items(), key=lambda item: -item[1])[:top]),
        "groups": dict(sorted(by_group.items(), key=lambda item: -item[1])),
        "total_seconds": round(sum(by_file.values()), 2),
    }


def _render_slowest(data: dict) -> str:
    lines = [f"{case['seconds']:8.2f}s  {case['file']}::{case['name']}" for case in data["tests"]]
    lines.append("by group:")
    lines += [f"{seconds:8.1f}s  {group}" for group, seconds in data["groups"].items()]
    lines.append(f"total {data['total_seconds']}s")
    return "\n".join(lines)


def repeat(paths: Sequence[str], times: int, *, extra: Sequence[str] = (), root: Path = ROOT_DIR) -> dict:
    """Run pytest `times` times on `paths`, each writing JUnit, and summarise flakiness."""
    runs = []
    folder = root / "coverage-report"
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(times):
        junit = folder / f"repeat_{index}.xml"
        junit.unlink(missing_ok=True)
        print(f"== run {index + 1}/{times}", flush=True)
        dev.run_live([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not lean_backtest", f"--junitxml={junit}", *extra, *paths])
        runs.append(parse_junit(junit) if junit.exists() else [])
    return flaky_summary(runs)


# ---------------------------------------------------------------------------
# where a module is tested
# ---------------------------------------------------------------------------


def test_where(module: str, root: Path = ROOT_DIR) -> dict:
    """The registered (and unregistered) test files that name `module`, their groups, and its line coverage if known."""
    import aq_cli

    posix = module.replace("\\", "/")
    if not posix.endswith(".py") and not (root / posix).exists():
        candidate = posix.replace(".", "/") + ".py"
        posix = candidate if (root / candidate).exists() else posix
    group_of = {name: group for group, names in aq_cli._SUBSYSTEM_TEST_FILES.items() for name in names}
    files = sorted({name for needle in aq_cli._module_needles(posix) for name in aq_cli._git_grep_tests(needle, dev.RUN)})
    report = root / "coverage-report" / "coverage.json"
    coverage = None
    if report.exists():
        data = json.loads(report.read_text(encoding="utf-8")).get("files", {})
        entry = next((value for name, value in data.items() if name.replace("\\", "/") == posix), None)
        coverage = entry["summary"]["percent_covered"] if entry else None
    own = f"test_{Path(posix).stem}.py"
    return {"module": posix, "tests": [{"file": name, "group": group_of.get(name)} for name in files], "own_test_file": own if (root / "tests" / own).exists() else None,
            "coverage_percent": coverage}


def _render_where(data: dict) -> str:
    lines = [f"{data['module']}: own test file {data['own_test_file'] or 'MISSING (aq test new ' + data['module'] + ')'}"]
    lines += [f"  {item['file']} ({item['group'] or 'NOT REGISTERED'})" for item in data["tests"]]
    if data["coverage_percent"] is not None:
        lines.append(f"  coverage (last run): {data['coverage_percent']:.1f}%")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# clean checkout, mutation, fuzz
# ---------------------------------------------------------------------------


def clean_checkout(pytest_args: Sequence[str], *, keep: bool = False, root: Path = ROOT_DIR) -> int:
    """The suite in a detached worktree of HEAD plus the working-tree changes and new files, without any gitignored file."""
    if sys.platform == "win32":
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / "scripts" / "clean_checkout_test.ps1"),
                   "-PytestArgs", " ".join(pytest_args) or "tests", *(["-Keep"] if keep else [])]
        return dev.run_live(command)
    work = Path(tempfile.gettempdir()) / "aq-clean-checkout"
    if work.exists():
        dev.run_capture(["git", "worktree", "remove", "--force", str(work)], cwd=root)
        shutil.rmtree(work, ignore_errors=True)
    if (code := dev.run_live(["git", "worktree", "add", "--detach", str(work), "HEAD"])) != 0:
        return code
    try:
        patch = Path(tempfile.gettempdir()) / "aq-clean-checkout.patch"
        dev.run_capture(["git", "diff", "HEAD", "--binary", f"--output={patch}"], cwd=root)
        if patch.exists() and patch.stat().st_size and dev.run_live(["git", "-C", str(work), "apply", "--binary", "--whitespace=nowarn", str(patch)]) != 0:
            print("aq test clean-checkout: the working-tree changes did not apply", file=sys.stderr)
            return dev.EXIT_FAIL
        _, others = dev.run_capture(["git", "ls-files", "--others", "--exclude-standard"], cwd=root)
        for line in others.splitlines():
            if line.strip():
                target = work / line.strip()
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / line.strip(), target)
        dev.run_capture(["git", "-C", str(work), "add", "-A"], cwd=root)
        env = {**os.environ, "PYTHONPATH": str(work)}
        code = dev.run_live([sys.executable, "-m", "pytest", *(pytest_args or ["tests"]), "-m", "not lean_backtest", "-ra", "-q", "-p", "no:cacheprovider"], cwd=work, env=env)
        print(f"clean-checkout pytest exit code: {code}")
        return code
    finally:
        if not keep:
            dev.run_capture(["git", "worktree", "remove", "--force", str(work)], cwd=root)


def fuzz(target: str | None, seconds: int, root: Path = ROOT_DIR) -> int:
    """atheris on `fuzz/targets.py` where it is installed (Linux), else the hypothesis drivers under the `fuzz` profile."""
    try:
        import atheris  # noqa: F401
    except ImportError:
        atheris_found = False
    else:
        atheris_found = True
    if atheris_found and target:
        return dev.run_live([sys.executable, "fuzz/run_fuzz.py", target, f"-max_total_time={seconds}"])
    env = {**os.environ, "HYPOTHESIS_PROFILE": "fuzz"}
    return dev.run_live([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_fuzz_targets.py", *(["-k", target] if target else [])], env=env)


# ---------------------------------------------------------------------------
# the dispatcher aq_cli.cmd_test calls
# ---------------------------------------------------------------------------


def run_verb(args: argparse.Namespace) -> int:
    """`aq test new|where|slowest|clean-checkout|mutation|fuzz` (the first positional word)."""
    verb, rest = args.paths[0], list(args.paths[1:])
    if (missing := dev.needs_checkout()) is not None:
        return missing
    if verb == "new":
        if len(rest) != 1:
            print("usage: aq test new MODULE [--group G] [--dry-run]", file=sys.stderr)
            return dev.EXIT_USAGE
        code, actions = dev.scaffold_test(rest[0], group=args.group, dry_run=args.dry_run)
        print("\n".join(("would " if args.dry_run else "") + action for action in actions))
        return code
    if verb == "where":
        if len(rest) != 1:
            print("usage: aq test where MODULE [--json]", file=sys.stderr)
            return dev.EXIT_USAGE
        data = test_where(rest[0])
        dev.emit(data, args.json, _render_where)
        return dev.EXIT_OK if data["tests"] else dev.EXIT_FAIL
    if verb == "slowest":
        junit = ROOT_DIR / JUNIT_LAST
        if not junit.exists():
            print("aq test slowest: no coverage-report/junit-last.xml yet: run aq test first", file=sys.stderr)
            return dev.EXIT_FAIL
        import aq_cli

        dev.emit(slowest(parse_junit(junit), aq_cli._SUBSYSTEM_TEST_FILES, args.top), args.json, _render_slowest)
        return dev.EXIT_OK
    if verb == "clean-checkout":
        return clean_checkout(rest)
    if verb == "mutation":
        out = rest[0] if rest else str(ROOT_DIR / "coverage-report" / "mutation.json")
        return dev.run_live([sys.executable, "scripts/mutation_check.py", "--out", out])
    return fuzz(args.target, args.seconds)


def run_repeat(args: argparse.Namespace, pytest_extra: Sequence[str]) -> int:
    if not args.paths:
        print("aq test --repeat: name the tests to repeat (aq test --repeat 5 tests/test_x.py)", file=sys.stderr)
        return dev.EXIT_USAGE
    summary = repeat(args.paths, args.repeat, extra=pytest_extra)
    dev.emit(summary, args.json, lambda data: "\n".join(
        [f"{data['runs']} runs of {data['tests']} tests: {len(data['flaky'])} flaky, {len(data['always_failing'])} always failing"]
        + [f"  flaky: {test}" for test in data["flaky"]] + [f"  failing: {test}" for test in data["always_failing"]]))
    return dev.EXIT_GATE if summary["flaky"] else dev.EXIT_FAIL if summary["always_failing"] else dev.EXIT_OK


# ---------------------------------------------------------------------------
# aq bench: hot-path latency against a per-machine baseline
# ---------------------------------------------------------------------------


def _load_profile_inference(root: Path = ROOT_DIR):
    sys.path.insert(0, str(root / "scripts"))
    try:
        import profile_inference
    finally:
        sys.path.pop(0)
    return profile_inference


def bench_exports(root: Path = ROOT_DIR) -> dict:
    """The installed models' exports (ml/); without them, an installed example model as the multitask export."""
    profile = _load_profile_inference(root)
    if (root / "ml" / "multitask_model.json").exists():
        return profile.load_real_exports()
    from retraining import model_catalog

    for name in model_catalog.catalog():
        try:
            loaded = model_catalog.load(name)
        except (FileNotFoundError, KeyError, ValueError, OSError):
            continue
        empty = dict.fromkeys(profile.EXPERT_NAMES)
        key = "multitask" if loaded["kind"] == "multitask" else "sequence"
        return {"baseline": None, "multitask": None, "sequence": None, "experts": dict(empty), "expert_multitask": dict(empty), key: loaded["export"]}
    raise FileNotFoundError("no model to time: install one (aq models install example-crypto-mlp) or run in a checkout with ml/")


def bench_run(iterations: int, *, root: Path = ROOT_DIR, exports: dict | None = None) -> dict:
    """p50/p95/p99/max/mean ms per symbol-bar of the numpy forward pass (scripts/profile_inference.py's workload)."""
    profile = _load_profile_inference(root)
    exports = exports or bench_exports(root)
    width = 0
    for export in [exports.get("multitask"), exports.get("sequence"), exports.get("baseline")]:
        if export:
            width = len(export.get("input_names") or export.get("feature_names") or []) or int(export.get("input_dim") or 0)
            break
    inputs = profile.pregenerate_inputs(max(width, 1), 20, iterations)
    durations = profile.run_workload(exports, inputs, use_batched=True)
    return {"iterations": iterations, **{key: round(value, 4) for key, value in profile.summarize_durations(durations).items()}}


def baseline_path(host: str | None = None) -> Path:
    return Path.home() / ".aq" / "bench" / f"{host or socket.gethostname()}.json"


def bench_compare(current: Mapping[str, float], baseline: Mapping[str, float], threshold: float) -> dict:
    """Each percentile's change against the baseline; regressed when p95 is more than `threshold` slower."""
    keys = ("p50_ms", "p95_ms", "p99_ms", "mean_ms")
    change = {key: (current[key] / baseline[key] - 1.0) if baseline.get(key) else None for key in keys}
    return {"current": dict(current), "baseline": dict(baseline), "change": change, "regressed": bool(change["p95_ms"] is not None and change["p95_ms"] > threshold)}


def cmd_bench(args: argparse.Namespace) -> int:
    try:
        result = bench_run(args.iterations)
    except FileNotFoundError as error:
        print(f"aq bench: {error}", file=sys.stderr)
        return dev.EXIT_FAIL
    path = baseline_path()
    if args.bench_command == "baseline":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"saved the baseline for this machine: {path}")
        dev.emit(result, args.json, lambda data: f"p50 {data['p50_ms']} ms, p95 {data['p95_ms']} ms, p99 {data['p99_ms']} ms over {data['iterations']}")
        return dev.EXIT_OK
    if args.bench_command == "run":
        dev.emit(result, args.json, lambda data: f"p50 {data['p50_ms']} ms, p95 {data['p95_ms']} ms, p99 {data['p99_ms']} ms, max {data['max_ms']} ms over {data['iterations']}")
        return dev.EXIT_OK
    if not path.exists():
        print(f"aq bench compare: no baseline for this machine yet: aq bench baseline ({path})", file=sys.stderr)
        return dev.EXIT_FAIL
    report = bench_compare(result, json.loads(path.read_text(encoding="utf-8")), args.threshold)
    dev.emit(report, args.json, lambda data: "\n".join(
        [f"{key}: {data['baseline'][key]} -> {data['current'][key]} ms ({value:+.1%})" for key, value in data["change"].items() if value is not None]
        + [("REGRESSED: p95 is more than " + f"{args.threshold:.0%} slower") if data["regressed"] else "within the threshold"]))
    return dev.EXIT_GATE if report["regressed"] else dev.EXIT_OK


def register(subparsers) -> None:
    bench = dev._parser(subparsers, "bench", "Hot-path latency of the numpy forward pass, against a baseline saved for this machine",
                        "aq bench baseline", "aq bench compare --threshold 0.2", "aq bench run --iterations 500 --json")
    bench_sub = bench.add_subparsers(dest="bench_command", required=True, parser_class=type(bench))
    for name, help_text, example in (("run", "Time it and print p50/p95/p99", "aq bench run"), ("baseline", "Time it and save the result as this machine's baseline", "aq bench baseline"),
                                     ("compare", "Time it against the baseline (exit 3 when p95 regressed)", "aq bench compare")):
        sub = dev._parser(bench_sub, name, help_text, example)
        sub.add_argument("--iterations", type=int, default=2000, help="Symbol-bars to time (default 2000)")
        dev.add_json_flag(sub)
        if name == "compare":
            sub.add_argument("--threshold", type=float, default=0.2, help="Allowed p95 slowdown as a fraction (default 0.2)")
    bench.set_defaults(func=cmd_bench)
