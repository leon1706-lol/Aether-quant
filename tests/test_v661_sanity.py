"""scripts/v661_sanity.py (V6.6.6): the pooled book's oracle, reversal and random signal, with a stand-in cell and scorer."""

from __future__ import annotations

import json

from script_loader import block_path_writes, run_script
from test_v660_sanity import fake_cell_source, fake_scoring


def test_the_pooled_book_scores_all_three_and_writes_them(monkeypatch):
    seen = []
    fake_scoring(monkeypatch, seen)
    fake_cell_source(monkeypatch, 0.1)
    writes = block_path_writes(monkeypatch)
    assert run_script("v661_sanity", [], monkeypatch) == 0
    assert [name for name, _ in seen] == ["oracle", "reversed_oracle", "random"]
    (written,) = [args for method, path, args in writes if method == "write_text" and path.name == "sanity_pooled.json"]
    assert set(json.loads(written[0])) == {"oracle", "reversed_oracle", "random"}
    assert any(method == "mkdir" for method, _path, _args in writes)
