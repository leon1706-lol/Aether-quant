"""retraining/run_resume.py (V6.6.10): run records, finished steps, the run to resume and the list of runs."""

from __future__ import annotations

import os

from retraining import run_resume as rr


def test_a_record_is_written_once_and_a_resume_keeps_its_settings(tmp_path):
    folder = tmp_path / "train_r1"
    first = rr.start_record(folder, {"mode": "sequence-only", "memory_profile": "low"})
    assert first["finished"] is False and first["mode"] == "sequence-only" and first["started"]
    assert rr.start_record(folder, {"mode": "something else"})["mode"] == "sequence-only"
    assert rr.update_record(folder, version_id="v1")["version_id"] == "v1" and rr.read_json(folder / rr.RECORD)["mode"] == "sequence-only"
    assert not (folder / "resume.json.partial").exists()


def test_steps_and_finishing(tmp_path):
    folder = tmp_path / "train_r2"
    rr.start_record(folder, {})
    assert rr.done_steps(folder) == [] and not rr.is_finished(folder)
    rr.mark_done(folder, "train_py", 0)
    rr.mark_done(folder, "gating")
    assert rr.done_steps(folder) == ["train_py", "gating"] and rr.is_finished(folder, last_step="gating")
    rr.update_record(folder, finished=True)
    assert rr.is_finished(folder)


def test_the_run_to_resume_is_named_or_the_newest_unfinished(tmp_path):
    for name, finished in (("train_old", False), ("train_done", True), ("train_new", False), ("retrain_other", False)):
        rr.start_record(tmp_path / name, {"finished": finished})
    os.utime(tmp_path / "train_old" / rr.RECORD, (1, 1))
    assert rr.find_resumable(tmp_path, "train_").name == "train_new"
    assert rr.find_resumable(tmp_path, "train_", "done").name == "train_done", "a named run is found even when finished"
    assert rr.find_resumable(tmp_path, "train_", "missing") is None and rr.find_resumable(tmp_path / "none", "train_") is None
    rows = rr.list_runs(tmp_path, ["train_", "retrain_"])
    assert {row["run_id"] for row in rows} == {"old", "done", "new", "other"} and rows[-1]["run_id"] == "old"
    assert next(row for row in rows if row["run_id"] == "done")["resumable"] is False
    (tmp_path / "train_torn").mkdir()
    (tmp_path / "train_torn" / rr.RECORD).write_text("{", encoding="utf-8")
    assert "torn" not in {row["run_id"] for row in rr.list_runs(tmp_path, ["train_"])}, "a record that cannot be read is no run"


def test_the_list_renders_for_a_terminal(tmp_path):
    assert rr.render_runs([]) == "no runs with a resume record yet"
    rr.start_record(tmp_path / "train_a", {})
    rr.mark_done(tmp_path / "train_a", "walk_forward")
    text = rr.render_runs(rr.list_runs(tmp_path, ["train_"]))
    assert "resumable" in text and "walk_forward" in text
    assert len(rr.new_run_id()) == 15
