import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import refresh_universe_availability as refresh  # noqa: E402


def _zip(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", "\n".join(rows) + "\n")


def _config_text() -> str:
    config = {
        "phase1": {"universe": {"assets": [
            {"ticker": "AAA", "data_path": "d/aaa.zip", "backfill": {"source": "x"}, "available_from": "2014-12-01", "available_to": "2021-03-30"},
            {"ticker": "BBB", "data_path": "d/bbb.zip", "available_from": "2013-01-02", "available_to": "2026-09-30"},
            {"ticker": "CCC", "data_path": "d/missing.zip", "available_from": "2014-12-01", "available_to": "2021-03-30"},
        ]}},
        "other": {"available_to": "keep-me"},
    }
    return json.dumps(config, indent=2)


def test_zip_date_range_reads_first_and_last_bar(tmp_path):
    _zip(tmp_path / "x.zip", ["20130102 00:00,1,1,1,1,5", "20260930 00:00,2,2,2,2,5"])
    assert refresh.zip_date_range(tmp_path / "x.zip") == ("2013-01-02", "2026-09-30")
    assert refresh.zip_date_range(tmp_path / "absent.zip") is None


def test_planned_updates_skip_matching_and_missing(tmp_path):
    _zip(tmp_path / "d/aaa.zip", ["20130102 00:00,1,1,1,1,5", "20260930 00:00,2,2,2,2,5"])
    _zip(tmp_path / "d/bbb.zip", ["20130102 00:00,1,1,1,1,5", "20260930 00:00,2,2,2,2,5"])
    updates = refresh.planned_updates(json.loads(_config_text()), tmp_path)
    assert [u["ticker"] for u in updates] == ["AAA"]


def test_apply_updates_changes_only_the_asset_dates(tmp_path):
    text = _config_text()
    updates = [{"ticker": "AAA", "from": ("2014-12-01", "2013-01-02"), "to": ("2021-03-30", "2026-09-30")}]
    new = json.loads(refresh.apply_updates(text, updates))
    aaa = new["phase1"]["universe"]["assets"][0]
    assert (aaa["available_from"], aaa["available_to"]) == ("2013-01-02", "2026-09-30")
    assert aaa["backfill"] == {"source": "x"}
    assert new["phase1"]["universe"]["assets"][2]["available_to"] == "2021-03-30"
    assert new["other"]["available_to"] == "keep-me"


def test_main_dry_run_writes_nothing(tmp_path, capsys):
    _zip(tmp_path / "d/aaa.zip", ["20130102 00:00,1,1,1,1,5", "20260930 00:00,2,2,2,2,5"])
    config_path = tmp_path / "config.json"
    config_path.write_text(_config_text(), encoding="utf-8")
    before = config_path.read_text(encoding="utf-8")
    assert refresh.main(["--config", str(config_path), "--root", str(tmp_path)]) == 0
    assert config_path.read_text(encoding="utf-8") == before
    assert "1 asset(s) to update" in capsys.readouterr().out
    refresh.main(["--config", str(config_path), "--root", str(tmp_path), "--apply"])
    assert json.loads(config_path.read_text(encoding="utf-8"))["phase1"]["universe"]["assets"][0]["available_to"] == "2026-09-30"
