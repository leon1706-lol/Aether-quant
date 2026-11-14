"""aq verify and aq docs sync (V6.6.6, #359): the doc writer, the listing, the quick run and the stale-fact exit code."""

from __future__ import annotations

import argparse

import aq_cli


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


def test_verify_writes_the_doc_lists_or_runs_the_quick_set(tmp_path, monkeypatch, capsys):
    from evaluation import verification_matrix as matrix

    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(matrix, "markdown", lambda: "| table |")
    (tmp_path / "development").mkdir()
    doc = tmp_path / "development" / "verification.md"
    doc.write_text("intro", encoding="utf-8")
    base = dict(write_doc=False, list=False, quick=False, record=None)
    assert aq_cli.cmd_verify(_ns(**{**base, "write_doc": True})) == 1 and "no AQ:VERIFICATION markers" in capsys.readouterr().err
    doc.write_text("intro\n<!-- AQ:VERIFICATION_START -->\nold\n<!-- AQ:VERIFICATION_END -->\ntail", encoding="utf-8")
    assert aq_cli.cmd_verify(_ns(**{**base, "write_doc": True})) == 0 and "| table |" in doc.read_text(encoding="utf-8") and doc.read_text(encoding="utf-8").endswith("tail")
    assert aq_cli.cmd_verify(_ns(**base)) == 0 and "| table |" in capsys.readouterr().out
    results = [{"exit": 0}, {"exit": 1}]
    monkeypatch.setattr(matrix, "run_quick", lambda root: results)
    recorded = []
    monkeypatch.setattr(matrix, "record", lambda path, items: recorded.append(str(path)))
    assert aq_cli.cmd_verify(_ns(**{**base, "quick": True})) == 1 and not recorded
    results[1] = {"exit": 0}
    assert aq_cli.cmd_verify(_ns(**{**base, "record": str(tmp_path / "r.json")})) == 0 and recorded and "recorded" in capsys.readouterr().out


def test_docs_sync_exits_non_zero_for_an_unknown_fact_or_a_stale_one_under_check(monkeypatch, capsys):
    import docs_facts

    monkeypatch.setattr(docs_facts, "tracked_docs", lambda root: [])
    monkeypatch.setattr(docs_facts, "compute_facts", lambda root: {})
    monkeypatch.setattr(docs_facts, "compute_blocks", lambda root: {})
    monkeypatch.setattr(docs_facts, "sync_docs", lambda paths, facts, check, blocks: {"changed": ["README.md: tests.count"], "unknown": ["README.md: nope"]})
    assert aq_cli.cmd_docs_sync(_ns(check=True)) == 1
    captured = capsys.readouterr()
    assert "unknown fact - README.md: nope" in captured.err and "stale - README.md: tests.count" in captured.out
    monkeypatch.setattr(docs_facts, "sync_docs", lambda paths, facts, check, blocks: {"changed": ["README.md: tests.count"], "unknown": []})
    assert aq_cli.cmd_docs_sync(_ns(check=False)) == 0 and "updated - README.md" in capsys.readouterr().out
    assert aq_cli.cmd_docs_sync(_ns(check=True)) == 1
