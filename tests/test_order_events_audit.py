import json

from scripts.order_events_audit import (
    _iter_order_events_jsons,
    _merge_summaries,
    load_order_events,
    summarize_order_events,
)


def _event(order_id, status, time, symbol="AAPL", fill_quantity=0.0):
    return {
        "orderId": order_id,
        "status": status,
        "time": time,
        "symbol": f"{symbol} X",
        "symbolValue": symbol,
        "fillQuantity": fill_quantity,
    }


def test_summarize_order_events_status_histogram():
    events = [
        _event(1, "submitted", 0.0),
        _event(1, "filled", 3600.0, fill_quantity=10.0),
        _event(2, "submitted", 0.0),
        _event(2, "cancelPending", 7200.0),
        _event(2, "canceled", 10800.0),
    ]

    summary = summarize_order_events(events)

    assert summary["status_histogram"] == {"submitted": 2, "filled": 1, "cancelPending": 1, "canceled": 1}
    assert summary["num_events"] == 5
    assert summary["num_orders"] == 2


def test_summarize_order_events_fill_latency_computed_per_order_id():
    events = [
        _event(1, "submitted", 0.0),
        _event(1, "filled", 3600.0 * 2),  # 2 hours later
    ]

    summary = summarize_order_events(events)

    assert summary["fill_latency_hours"]["mean"] == 2.0
    assert summary["fill_latency_hours"]["num_orders_measured"] == 1


def test_summarize_order_events_canceled_count_by_symbol_is_upper_bound_proxy():
    events = [
        _event(1, "submitted", 0.0, symbol="HYG"),
        _event(1, "canceled", 100.0, symbol="HYG"),
        _event(2, "submitted", 0.0, symbol="JNK"),
        _event(2, "filled", 100.0, symbol="JNK"),
    ]

    summary = summarize_order_events(events)

    assert summary["canceled_count_by_symbol"] == {"HYG": 1}


def test_summarize_order_events_empty_list_returns_zero_stats():
    summary = summarize_order_events([])

    assert summary == {
        "num_events": 0,
        "num_orders": 0,
        "status_histogram": {},
        "fill_latency_hours": {"mean": None, "median": None, "max": None, "num_orders_measured": 0},
        "canceled_count_by_symbol": {},
    }


def test_iter_order_events_jsons_skips_folders_without_one(tmp_path):
    run_with = tmp_path / "2026-01-01_00-00-00"
    run_with.mkdir()
    (run_with / "111-order-events.json").write_text("[]", encoding="utf-8")
    run_without = tmp_path / "2026-01-02_00-00-00"
    run_without.mkdir()
    (run_without / "111.json").write_text("{}", encoding="utf-8")

    found = list(_iter_order_events_jsons(tmp_path))

    assert len(found) == 1
    assert found[0].name == "111-order-events.json"


def test_load_order_events_tolerates_malformed_file(tmp_path):
    bad_path = tmp_path / "bad-order-events.json"
    bad_path.write_text("{not valid json", encoding="utf-8")

    assert load_order_events(bad_path) == []


def test_load_order_events_rejects_non_list_top_level(tmp_path):
    path = tmp_path / "111-order-events.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

    assert load_order_events(path) == []


def test_merge_summaries_aggregates_across_files():
    summary_a = summarize_order_events([_event(1, "submitted", 0.0), _event(1, "filled", 3600.0)])
    summary_b = summarize_order_events([_event(2, "submitted", 0.0), _event(2, "canceled", 7200.0, symbol="JNK")])

    aggregate = _merge_summaries([summary_a, summary_b])

    assert aggregate["num_files"] == 2
    assert aggregate["num_orders"] == 2
    assert aggregate["status_histogram"]["filled"] == 1
    assert aggregate["status_histogram"]["canceled"] == 1


def test_summarize_order_events_sanity_against_real_backtest_file():
    """Regression guard proving this tool agrees with the already hand-
    verified 23/23 cancelPending/canceled pairing from Problems.md #34/#96
    (644 submitted / 620 filled / 23 cancelPending / 23 canceled,
    backtests/2026-08-11_09-56-24)."""
    from pathlib import Path

    path = Path("backtests/2026-08-11_09-56-24/1198299145-order-events.json")
    if not path.exists():
        import pytest

        pytest.skip(f"{path} not present in this environment")
        return

    events = load_order_events(path)
    summary = summarize_order_events(events)

    assert summary["status_histogram"]["cancelPending"] == 23
    assert summary["status_histogram"]["canceled"] == 23
    assert summary["status_histogram"]["submitted"] == 644
    assert summary["status_histogram"]["filled"] == 620
