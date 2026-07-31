import json

from features.sector_map import UNKNOWN_SECTOR_LABEL, load_sector_mapping, resolve_sector


def _config(mapping_path=None):
    ranking = {}
    if mapping_path is not None:
        ranking["sector_neutral"] = {"mapping_path": str(mapping_path)}
    return {"phase1": {"target": {"ranking": ranking}}}


def test_load_sector_mapping_reads_the_real_reference_file():
    mapping = load_sector_mapping(_config())
    assert mapping["AAPL"] == "Technology"
    assert mapping["EURUSD"] == "Forex"
    assert mapping["BTCUSD"] == "Crypto"
    assert mapping["SHY"] == "Fixed Income"


def test_load_sector_mapping_covers_103_of_104_universe_tickers():
    # V5.1 Phase 0 (Problems.md #75): expanded from 29 -> 103 of 104 - AAA
    # stays intentionally unmapped (ambiguous legacy ticker, observation-only).
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    universe_tickers = [asset["ticker"] for asset in config["phase1"]["universe"]["assets"]]
    mapping = load_sector_mapping(config)

    mapped = [ticker for ticker in universe_tickers if ticker in mapping]
    unmapped = [ticker for ticker in universe_tickers if ticker not in mapping]

    assert len(universe_tickers) == 104
    assert len(mapped) == 103
    assert unmapped == ["AAA"]


def test_load_sector_mapping_strips_underscore_prefixed_comment_keys():
    mapping = load_sector_mapping(_config())
    assert all(not key.startswith("_") for key in mapping)


def test_load_sector_mapping_missing_file_returns_empty_dict_never_raises(tmp_path):
    mapping = load_sector_mapping(_config(mapping_path=tmp_path / "does_not_exist.json"))
    assert mapping == {}


def test_load_sector_mapping_malformed_json_returns_empty_dict_never_raises(tmp_path):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    mapping = load_sector_mapping(_config(mapping_path=bad_path))
    assert mapping == {}


def test_load_sector_mapping_honors_override_path(tmp_path):
    override_path = tmp_path / "override.json"
    override_path.write_text(json.dumps({"_comment": "x", "ZZZ": "TestSector"}), encoding="utf-8")

    mapping = load_sector_mapping(_config(mapping_path=override_path))

    assert mapping == {"ZZZ": "TestSector"}


def test_resolve_sector_known_and_unknown_ticker():
    mapping = {"AAPL": "Technology"}
    assert resolve_sector("AAPL", mapping) == "Technology"
    assert resolve_sector("NOPE", mapping) == UNKNOWN_SECTOR_LABEL
