from monitoring.strategy_catalog import build_strategy_catalog
from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY


def test_build_strategy_catalog_total_count_matches_registry():
    catalog = build_strategy_catalog()
    assert catalog["total_count"] == len(MULTI_LEG_STRATEGY_REGISTRY) == 43
    assert len(catalog["strategies"]) == 43


def test_build_strategy_catalog_entries_have_expected_shape():
    catalog = build_strategy_catalog()
    for entry in catalog["strategies"]:
        assert set(entry.keys()) == {"name", "leg_count", "risk_tier", "shape_family", "has_expiry_pair"}
        assert entry["leg_count"] > 0
        assert isinstance(entry["has_expiry_pair"], bool)


def test_build_strategy_catalog_is_sorted_by_name():
    catalog = build_strategy_catalog()
    names = [entry["name"] for entry in catalog["strategies"]]
    assert names == sorted(names)


def test_build_strategy_catalog_spot_check_known_strategy():
    catalog = build_strategy_catalog()
    by_name = {entry["name"]: entry for entry in catalog["strategies"]}
    assert "iron_condor" in by_name
    assert by_name["iron_condor"]["leg_count"] == 4
    assert "bull_call_spread" in by_name
    assert by_name["bull_call_spread"]["leg_count"] == 2


def test_build_strategy_catalog_never_raises():
    # Pure read of a static in-memory dict - should always succeed.
    catalog = build_strategy_catalog()
    assert isinstance(catalog, dict)
