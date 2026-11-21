"""aq_testtools.py: the impacted tests, the watch loop, repeats and flaky tests, the slowest tests, where a module is tested,
the clean checkout, fuzzing, the aq test verbs and aq bench. Subprocesses go through `aq_devtools.RUN`, replaced here."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import aq_devtools as dev
import aq_testtools as tt


def ns(**values):
    return argparse.Namespace(**values)


def _junit(path, cases):
    body = "".join(
        f'<testcase classname="tests.{file[:-3]}" name="{name}" time="{seconds}">{"<failure/>" if outcome == "failed" else "<skipped/>" if outcome == "skipped" else ""}</testcase>'
        for file, name, seconds, outcome in cases)
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{body}</testsuite></testsuites>', encoding="utf-8")


def test_junit_parses_and_flaky_tests_are_found(tmp_path):
    first, second = tmp_path / "a.xml", tmp_path / "b.xml"
    _junit(first, [("test_x.py", "t1", 1.5, "passed"), ("test_x.py", "t2", 0.1, "failed"), ("test_y.py", "t3", 0.2, "skipped")])
    _junit(second, [("test_x.py", "t1", 1.0, "failed"), ("test_x.py", "t2", 0.1, "failed")])
    cases = tt.parse_junit(first)
    assert cases[0] == {"file": "test_x.py", "name": "t1", "seconds": 1.5, "outcome": "passed"} and cases[2]["outcome"] == "skipped"
    summary = tt.flaky_summary([cases, tt.parse_junit(second)])
    assert summary["flaky"] == ["test_x.py::t1"] and summary["always_failing"] == ["test_x.py::t2"] and summary["runs"] == 2
    report = tt.slowest(cases, {"risk": ["test_x.py"]}, top=1)
    assert report["tests"][0]["name"] == "t1" and report["groups"] == {"risk": 1.6, "(no group)": 0.2} and report["total_seconds"] == 1.8
    assert "t1" in tt._render_slowest(report) and "by group:" in tt._render_slowest(report)
    plain = tmp_path / "c.xml"
    plain.write_text('<testsuite><testcase classname="flat" name="t"/></testsuite>', encoding="utf-8")
    assert tt.parse_junit(plain)[0]["file"] == "flat"


def test_repeat_runs_pytest_n_times_and_reports(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "coverage-report"
    outcomes = iter(["passed", "failed"])

    def fake_live(command, **kwargs):
        target = next(part for part in command if part.startswith("--junitxml=")).split("=", 1)[1]
        _junit(tt.Path(target), [("test_x.py", "t", 0.1, next(outcomes))])
        return 0

    monkeypatch.setattr(dev, "run_live", fake_live)
    summary = tt.repeat(["tests/test_x.py"], 2, root=tmp_path)
    assert summary["flaky"] == ["test_x.py::t"] and folder.exists()
    monkeypatch.setattr(tt, "repeat", lambda paths, times, extra: {"runs": 2, "tests": 1, "flaky": ["a"], "always_failing": []})
    assert tt.run_repeat(ns(paths=["tests/test_x.py"], repeat=2, json=False), []) == 3 and "flaky: a" in capsys.readouterr().out
    monkeypatch.setattr(tt, "repeat", lambda paths, times, extra: {"runs": 2, "tests": 1, "flaky": [], "always_failing": ["b"]})
    assert tt.run_repeat(ns(paths=["x"], repeat=2, json=True), []) == 1
    monkeypatch.setattr(tt, "repeat", lambda paths, times, extra: {"runs": 2, "tests": 1, "flaky": [], "always_failing": []})
    assert tt.run_repeat(ns(paths=["x"], repeat=2, json=False), []) == 0
    assert tt.run_repeat(ns(paths=[], repeat=2, json=False), []) == 2 and "name the tests" in capsys.readouterr().err


def test_a_missing_junit_counts_as_an_empty_run(tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: 1)
    assert tt.repeat(["x"], 1, root=tmp_path)["tests"] == 0


def test_the_watch_loop_reruns_on_a_change_and_stops_on_ctrl_c(capsys):
    snapshots = iter([{"a": 1}, {"a": 1}, {"a": 2}, {"a": 2}, {"a": 2, "b": 1}, {"a": 2, "b": 1}])
    runs = []
    code = tt.watch(lambda: runs.append(1) or 7, snapshot=lambda: next(snapshots), sleep=lambda seconds: None, iterations=2)
    assert code == 7 and len(runs) == 3 and capsys.readouterr().out.count("change detected") == 2

    def interrupt(seconds):
        raise KeyboardInterrupt

    assert tt.watch(lambda: 0, snapshot=dict, sleep=interrupt) == 130


def test_source_mtimes_and_impacted_tests(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(dev, "RUN", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="a.py\nmissing.py\n", stderr=""))
    assert set(tt.source_mtimes(tmp_path)) == {"a.py"}
    import aq_cli

    monkeypatch.setattr(aq_cli, "_changed_python_files", lambda run: ["risk/kelly.py"])
    monkeypatch.setattr(aq_cli, "_changed_test_files", lambda run: ["test_kelly.py", "test_unregistered_anything.py"])
    monkeypatch.setattr(aq_cli, "_git_grep_tests", lambda needle, run: ["test_kelly.py"])
    assert tt.impacted_tests() == ["test_kelly.py"]


def test_where_a_module_is_tested(tmp_path, monkeypatch, capsys):
    import aq_cli

    monkeypatch.setattr(aq_cli, "_git_grep_tests", lambda needle, run: ["test_kelly.py", "test_orphan.py"])
    (tmp_path / "risk").mkdir()
    (tmp_path / "risk" / "kelly.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_kelly.py").write_text("", encoding="utf-8")
    (tmp_path / "coverage-report").mkdir()
    (tmp_path / "coverage-report" / "coverage.json").write_text(json.dumps({"files": {"risk\\kelly.py": {"summary": {"percent_covered": 97.5}}}}), encoding="utf-8")
    report = tt.test_where("risk.kelly", root=tmp_path)
    assert report["module"] == "risk/kelly.py" and report["own_test_file"] == "test_kelly.py" and report["coverage_percent"] == 97.5
    assert {"file": "test_orphan.py", "group": None} in report["tests"]
    text = tt._render_where(report)
    assert "NOT REGISTERED" in text and "97.5%" in text
    assert "MISSING" in tt._render_where({**report, "own_test_file": None, "coverage_percent": None})
    assert tt.test_where("nothing/here", root=tmp_path)["coverage_percent"] is None


def test_the_clean_checkout_on_windows_and_elsewhere(tmp_path, monkeypatch, capsys):
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, cwd=None, env=None: live.append((command, cwd, env)) or 0)
    monkeypatch.setattr(tt.sys, "platform", "win32")
    assert tt.clean_checkout(["tests/test_x.py"], keep=True, root=tmp_path) == 0
    assert live[-1][0][-3:] == ["-PytestArgs", "tests/test_x.py", "-Keep"]
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setattr(tt.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    (tmp_path / "tmp" / "aq-clean-checkout").mkdir(parents=True)
    (tmp_path / "new.txt").write_text("n", encoding="utf-8")

    def fake_capture(command, cwd=None, **kwargs):
        if command[:2] == ["git", "diff"]:
            patch = next(part for part in command if part.startswith("--output=")).split("=", 1)[1]
            tt.Path(patch).write_text("diff", encoding="utf-8")
        if command[:3] == ["git", "ls-files", "--others"]:
            return 0, "new.txt\n\n"
        return 0, ""

    monkeypatch.setattr(dev, "run_capture", fake_capture)
    live.clear()
    assert tt.clean_checkout([], root=tmp_path) == 0
    assert live[0][0][:4] == ["git", "worktree", "add", "--detach"] and "not lean_backtest" in live[-1][0]
    assert (tmp_path / "tmp" / "aq-clean-checkout" / "new.txt").exists()
    codes = iter([0, 1])
    monkeypatch.setattr(dev, "run_live", lambda command, cwd=None, env=None: next(codes))
    assert tt.clean_checkout([], root=tmp_path) == 1 and "did not apply" in capsys.readouterr().err
    monkeypatch.setattr(dev, "run_live", lambda command, cwd=None, env=None: 128)
    assert tt.clean_checkout([], root=tmp_path) == 128


def test_fuzz_uses_atheris_where_it_is_and_hypothesis_elsewhere(monkeypatch):
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, env=None, **kwargs: live.append((command, env)) or 0)
    monkeypatch.setitem(sys.modules, "atheris", None)
    assert tt.fuzz("json_safety", 5) == 0 and live[-1][1]["HYPOTHESIS_PROFILE"] == "fuzz" and live[-1][0][-2:] == ["-k", "json_safety"]
    monkeypatch.setitem(sys.modules, "atheris", SimpleNamespace())
    assert tt.fuzz("json_safety", 5) == 0 and live[-1][0][-1] == "-max_total_time=5"
    assert tt.fuzz(None, 5) == 0 and "-k" not in live[-1][0]


def test_the_test_verbs_dispatch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: None)
    base = dict(group=None, dry_run=True, json=False, top=5, target=None, seconds=3)
    assert tt.run_verb(ns(paths=["new"], **base)) == 2 and "usage: aq test new" in capsys.readouterr().err
    monkeypatch.setattr(dev, "scaffold_test", lambda module, group, dry_run: (0, ["create tests/test_x.py"]))
    assert tt.run_verb(ns(paths=["new", "x.py"], **base)) == 0 and "would create" in capsys.readouterr().out
    assert tt.run_verb(ns(paths=["where"], **base)) == 2
    monkeypatch.setattr(tt, "test_where", lambda module: {"module": module, "tests": [], "own_test_file": None, "coverage_percent": None})
    assert tt.run_verb(ns(paths=["where", "x.py"], **base)) == 1
    monkeypatch.setattr(tt, "ROOT_DIR", tmp_path)
    assert tt.run_verb(ns(paths=["slowest"], **base)) == 1 and "run aq test first" in capsys.readouterr().err
    (tmp_path / "coverage-report").mkdir()
    _junit(tmp_path / "coverage-report" / "junit-last.xml", [("test_x.py", "t", 0.4, "passed")])
    assert tt.run_verb(ns(paths=["slowest"], **{**base, "json": True})) == 0 and json.loads(capsys.readouterr().out)["total_seconds"] == 0.4
    monkeypatch.setattr(tt, "clean_checkout", lambda rest: 4)
    assert tt.run_verb(ns(paths=["clean-checkout"], **base)) == 4
    live = []
    monkeypatch.setattr(dev, "run_live", lambda command, **kwargs: live.append(command) or 0)
    assert tt.run_verb(ns(paths=["mutation"], **base)) == 0 and live[-1][-1].endswith("mutation.json")
    assert tt.run_verb(ns(paths=["mutation", "out.json"], **base)) == 0 and live[-1][-1] == "out.json"
    monkeypatch.setattr(tt, "fuzz", lambda target, seconds: 6)
    assert tt.run_verb(ns(paths=["fuzz"], **base)) == 6
    monkeypatch.setattr(dev, "needs_checkout", lambda root=None: 1)
    assert tt.run_verb(ns(paths=["fuzz"], **base)) == 1


def test_bench_times_compares_and_saves_a_baseline(tmp_path, monkeypatch, capsys):
    assert tt.baseline_path("host").name == "host.json"
    result = {"iterations": 10, "p50_ms": 1.0, "p95_ms": 2.0, "p99_ms": 3.0, "max_ms": 4.0, "mean_ms": 1.2}
    report = tt.bench_compare({**result, "p95_ms": 3.0}, result, 0.2)
    assert report["regressed"] and report["change"]["p95_ms"] == pytest.approx(0.5)
    assert tt.bench_compare(result, {**result, "p50_ms": 0}, 0.2)["change"]["p50_ms"] is None
    monkeypatch.setattr(tt, "bench_run", lambda iterations: dict(result))
    monkeypatch.setattr(tt, "baseline_path", lambda host=None: tmp_path / "bench" / "pc.json")
    args = dict(iterations=10, json=False, threshold=0.2)
    assert tt.cmd_bench(ns(bench_command="compare", **args)) == 1 and "no baseline" in capsys.readouterr().err
    assert tt.cmd_bench(ns(bench_command="baseline", **args)) == 0 and (tmp_path / "bench" / "pc.json").exists()
    assert tt.cmd_bench(ns(bench_command="run", **args)) == 0 and "p95 2.0 ms" in capsys.readouterr().out
    assert tt.cmd_bench(ns(bench_command="compare", **args)) == 0 and "within the threshold" in capsys.readouterr().out
    monkeypatch.setattr(tt, "bench_run", lambda iterations: {**result, "p95_ms": 9.0})
    assert tt.cmd_bench(ns(bench_command="compare", **args)) == 3 and "REGRESSED" in capsys.readouterr().out
    monkeypatch.setattr(tt, "bench_run", lambda iterations: (_ for _ in ()).throw(FileNotFoundError("no model to time")))
    assert tt.cmd_bench(ns(bench_command="run", **args)) == 1 and "no model to time" in capsys.readouterr().err


def test_bench_times_a_real_model_export(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    from lab import architectures as arch

    model = arch.AetherNetMultiTaskHorizons(input_dim=4, hidden_layers=[3], dropout=0.0).eval()
    export = {"export": arch.export_multitask_horizons_architecture(model) | {"state_dict": arch.export_state_dict(model)}, "input_names": ["a", "b", "c", "d"]}
    profile = tt._load_profile_inference()
    empty = dict.fromkeys(profile.EXPERT_NAMES)
    exports = {"baseline": None, "multitask": export, "sequence": None, "experts": dict(empty), "expert_multitask": dict(empty)}
    result = tt.bench_run(5, exports=exports)
    assert result["iterations"] == 5 and result["p50_ms"] >= 0


def test_bench_exports_prefer_ml_then_an_installed_example(tmp_path, monkeypatch):
    profile = tt._load_profile_inference()
    monkeypatch.setattr(profile, "load_real_exports", lambda: {"from": "ml"})
    (tmp_path / "ml").mkdir()
    (tmp_path / "ml" / "multitask_model.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tt, "_load_profile_inference", lambda root=None: profile)
    assert tt.bench_exports(tmp_path) == {"from": "ml"}
    from retraining import model_catalog

    monkeypatch.setattr(model_catalog, "catalog", lambda: [{"name": "a"}, {"name": "b"}])
    monkeypatch.setattr(model_catalog, "load", lambda name: (_ for _ in ()).throw(FileNotFoundError()) if name == "a" else {"kind": "sequence", "export": {"x": 1}})
    exports = tt.bench_exports(tmp_path / "elsewhere")
    assert exports["sequence"] == {"x": 1} and exports["multitask"] is None
    monkeypatch.setattr(model_catalog, "load", lambda name: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(FileNotFoundError, match="no model to time"):
        tt.bench_exports(tmp_path / "elsewhere")


def test_register_adds_bench():
    import aq_cli

    assert dev._subparsers_of(dev._subparsers_of(aq_cli.build_parser())["bench"]).keys() == {"run", "baseline", "compare"}
