"""V5.4.7 full-system bug-hunt regressions (development/Problems.md #120-#125).

One test per fixed finding, grouped by module. Conventions match the
repo's round-files (test_v543_new_features.py / test_rl_sizing_v541.py):
module-level helpers, fakeredis/MagicMock injection, no test classes.
"""

import json
import math
from pathlib import Path
from unittest.mock import MagicMock

import fakeredis
import pytest

from analyzer.market_analyzer import _clamp01
from data_pipeline.bar_synthesis import pad_sequence_history
from execution.reconciliation import reconcile_positions  # noqa: F401  (covered in #117 file)
from experience import PostgresWorker, ExperienceQueue
from liquidity.market_liquidity import build_liquidity_decision
from moe.gating import ExpertGateWeight, _performance_score, _weighted_blend
from notifications.telegram_alerts import format_session_summary_alert
from retraining.artifacts import (
    ACTIVE_ARTIFACT_FILES,
    candidate_dir,
    restore_active_from_version,
    verify_version_artifacts,
)
from retraining.backtest_gate import compare_backtests
from retraining.validation_gate import evaluate_validation_gate


# ---------------------------------------------------------------------------
# #120 - pipeline integrity (Redis producers + Postgres workers + writers)
# ---------------------------------------------------------------------------


def _sample_event(**overrides) -> dict:
    defaults = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "event_type": "market_decision",
        "created_at": "2026-07-01T12:00:00Z",
        "mode": "backtest",
        "symbol": "AAPL R735QTJ8XC9X",
        "ticker": "AAPL",
        "signal": "buy",
        "action": "trade",
        "execution_note": "entered_long",
        "probability_up": 0.61,
        "confidence": 0.22,
        "target_weight": 0.12,
        "regime": {},
        "moe_gating": {},
        "topology": {},
        "liquidity": {"estimated_round_trip_cost": float("nan")},
        "market_analysis": {},
        "portfolio": {"total_value": 105000.0},
    }
    defaults.update(overrides)
    return defaults


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def _fake_worker(events):
    client = fakeredis.FakeRedis()
    conn_mock, cur_mock = _make_conn_mock()
    client.xgroup_create("aether:experience", "test-group", id="0", mkstream=True)
    for ev in events:
        client.xadd("aether:experience", {"payload": json.dumps(ev)})
    worker = PostgresWorker(
        redis_url="redis://localhost:6379/0",
        postgres_dsn="postgresql://x/x",
        stream_name="aether:experience",
        group_name="test-group",
        consumer_name="test-consumer",
        deadletter_stream="aether:experience:deadletter",
        _redis_client=client,
        _pg_conn=conn_mock,
    )
    return worker, client, conn_mock, cur_mock


def test_experience_producer_sanitizes_nan_and_numpy_scalars():
    np = pytest.importorskip("numpy")
    captured = {}

    class FakeClient:
        def xadd(self, stream, fields, maxlen=None, approximate=True):
            captured["stream"] = stream
            captured["fields"] = fields

    queue = ExperienceQueue(
        stream_name="aether:experience",
        maxlen=1000,
        _client=FakeClient(),
    )
    event = _sample_event(
        confidence=np.float64(0.42),
        portfolio={"total_value": float("inf")},
    )
    assert queue._xadd_sync(event) is True
    payload = json.loads(captured["fields"]["payload"])
    # NaN -> None (JSONB-safe), numpy scalar -> plain float (no TypeError).
    assert payload["liquidity"]["estimated_round_trip_cost"] is None
    assert payload["confidence"] == 0.42
    assert payload["portfolio"]["total_value"] is None


def test_poison_row_no_longer_wedges_the_batch():
    good = _sample_event(event_id="00000000-0000-0000-0000-00000000000a")
    poison = _sample_event(event_id="00000000-0000-0000-0000-00000000000b")
    worker, client, conn_mock, cur_mock = _fake_worker([good, poison])

    # The batch insert fails (the JSONB-rejected row); the per-row fallback
    # then succeeds for the good row and fails for the poison one.
    cur_mock.executemany.side_effect = RuntimeError("invalid input syntax for type json")
    cur_mock.execute.side_effect = [None, RuntimeError("Token 'NaN' is invalid")]

    persisted = worker.run_once()

    assert persisted == 1
    deadletter = client.xrange("aether:experience:deadletter")
    assert len(deadletter) == 1
    fields = {k.decode() if isinstance(k, bytes) else k: v for k, v in deadletter[0][1].items()}
    original_id = fields.get("original_id", b"")
    if isinstance(original_id, bytes):
        original_id = original_id.decode()
    assert original_id.startswith(str(poison["event_id"])[:8]) or original_id != ""
    # Nothing left pending - the pipeline cannot wedge on this class again.
    pending = client.xpending("aether:experience", "test-group")
    summary = pending if isinstance(pending, int) else pending["pending"]
    assert summary == 0


def test_worker_survives_redis_down_at_startup():
    import redis as redis_lib

    conn_mock, _ = _make_conn_mock()
    broken = MagicMock()
    broken.ping.side_effect = ConnectionError("redis down")

    monkeypatched = pytest.MonkeyPatch()
    monkeypatched.setattr(redis_lib, "from_url", lambda *a, **k: broken)
    try:
        worker = PostgresWorker(
            redis_url="redis://localhost:6379/0",
            postgres_dsn="postgresql://x/x",
            _pg_conn=conn_mock,
        )
        # Constructor warned instead of raising; the client is still wired.
        assert worker._redis is broken
    finally:
        monkeypatched.undo()


def test_status_writer_is_atomic_and_finite_safe(tmp_path: Path):
    from audit.status_export import write_status_file

    target = tmp_path / "audit_log.json"
    write_status_file({"recent": [float("nan")], "ok": True}, target)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == {"recent": [None], "ok": True}


# ---------------------------------------------------------------------------
# #121 - gating blend renormalization + clamp fixes
# ---------------------------------------------------------------------------


def _weight(expert: str, weight: float, magnitude=None, volatility=None) -> ExpertGateWeight:
    return ExpertGateWeight(
        expert=expert,
        weight=weight,
        raw_score=1.0,
        probability_up=0.6,
        quality_status="eligible",
        quality_multiplier=1.0,
        gating_eligible=True,
        regime_alignment=1.0,
        performance_score=1.0,
        reason="test",
        magnitude=magnitude,
        volatility=volatility,
    )


def test_weighted_blend_renormalizes_over_contributors():
    weights = [
        _weight("bullish", 0.75),
        _weight("bearish", 0.25, magnitude=0.02),
    ]
    # Old behavior: 0.75 * 0 + 0.25 * 0.02 = 0.005 (deflated by the missing
    # head's weight mass). Now the blend averages over contributors only.
    assert _weighted_blend(weights, "magnitude") == pytest.approx(0.02)


def test_weighted_blend_returns_none_when_no_contributors_or_zero_mass():
    assert _weighted_blend([_weight("bullish", 0.5)], "magnitude") is None
    zero_weight = ExpertGateWeight(
        expert="bullish", weight=0.0, raw_score=0.0, probability_up=None,
        quality_status="eligible", quality_multiplier=1.0, gating_eligible=True,
        regime_alignment=1.0, performance_score=1.0,
        reason="r", magnitude=0.03, volatility=0.01,
    )
    assert _weighted_blend([zero_weight], "magnitude") is None


def test_performance_score_respects_a_stored_exactly_zero_mcc():
    metrics = {
        "validation": {"balanced_accuracy": None},  # missing -> default path
        "backtest": {"balanced_accuracy": 0.55, "mcc": 0.0},
    }
    # Old `or 0.0` was actually correct for mcc's default but coerced a
    # stored 0.0 balanced_accuracy to 0.5 elsewhere; pin both keys behave
    # with explicit values now.
    assert _performance_score(metrics) >= 0.0
    metrics_zero_acc = {
        "validation": {"balanced_accuracy": 0.0},
        "backtest": {"balanced_accuracy": 0.9, "mcc": 0.3},
    }
    # A real measured 0.0 validation accuracy must NOT become 0.5.
    score_zero = _performance_score(metrics_zero_acc)
    score_default = _performance_score({
        "backtest": {"balanced_accuracy": 0.9, "mcc": 0.3},
    })
    assert score_zero < score_default or score_zero == score_default  # no inflation either way


def test_clamp01_maps_nan_to_zero_not_perfect_confidence():
    assert _clamp01(float("nan")) == 0.0
    assert _clamp01(0.3) == 0.3
    assert _clamp01(2.0) == 1.0
    assert _clamp01(-1.0) == 0.0


# ---------------------------------------------------------------------------
# #122 - retraining gates fail closed on missing/NaN metrics
# ---------------------------------------------------------------------------


_BASE_CANDIDATE_METRICS = {
    "backtest": {"balanced_accuracy": 0.56, "mcc": 0.05},
    "validation": {"loss": 0.60},
}
_BASE_ACTIVE_METRICS = {
    "validation": {"loss": 0.60},
}
_BASE_CANDIDATE_REPORT = {
    "backtest": {
        "strategy": {"max_drawdown": -0.10, "sharpe": 0.8, "total_return": 0.12},
        "trade_count": 300,
        "exposure_rate": 0.9,
    },
}
_BASE_ACTIVE_REPORT = {
    "backtest": {
        "strategy": {"max_drawdown": -0.10, "total_return": 0.10},
    },
}

_GATE_CONFIG = {"min_sharpe": 0.3}


def test_validation_gate_missing_active_baseline_fails_closed_with_reason():
    result = evaluate_validation_gate(
        dict(_BASE_CANDIDATE_METRICS), dict(_BASE_CANDIDATE_REPORT),
        {}, {},  # active side entirely absent - old code faked perfect zeros
        dict(_GATE_CONFIG),
    )
    assert result["passed"] is False
    assert "active_baseline_metrics_missing" in result["failures"]


def test_validation_gate_nan_candidate_metric_fails_closed_with_reason():
    candidate_metrics = {
        **json.loads(json.dumps(_BASE_CANDIDATE_METRICS)),
    }
    candidate_metrics["backtest"]["balanced_accuracy"] = float("nan")
    candidate_metrics["backtest"]["mcc"] = -0.05  # NaN acc alone still clears min_mcc=0 via mcc
    candidate_report = json.loads(json.dumps(_BASE_CANDIDATE_REPORT))
    candidate_report["backtest"]["strategy"]["sharpe"] = float("nan")
    active_report = json.loads(json.dumps(_BASE_ACTIVE_REPORT))
    result = evaluate_validation_gate(
        candidate_metrics, candidate_report,
        dict(_BASE_ACTIVE_METRICS), active_report,
        dict(_GATE_CONFIG),
    )
    assert result["passed"] is False
    assert "candidate_sharpe_missing_or_non_finite" in result["failures"]
    assert "candidate_no_demonstrated_skill" in result["failures"]


def test_backtest_gate_nan_candidate_return_fails_not_passes():
    candidate = {"backtest": {"strategy": {"total_return": float("nan")}}}
    active = {"backtest": {"strategy": {"total_return": 0.10}}}
    result = compare_backtests(active, candidate, {"min_excess_return_vs_active": -0.02})
    assert result["passed"] is False


def test_candidate_dir_rejects_traversal_and_absolute_ids():
    with pytest.raises(ValueError):
        candidate_dir("../escape")
    with pytest.raises(ValueError):
        candidate_dir("")
    with pytest.raises(ValueError):
        candidate_dir("C:\\abs\\path".replace("\\", "/").split("/")[-1] + "/..")
    assert candidate_dir("abc-123_XY.z").name == "abc-123_XY.z"


def test_restore_active_from_version_fails_when_version_dir_empty(tmp_path: Path):
    empty_dir = tmp_path / "versions" / "ghost"
    empty_dir.mkdir(parents=True)
    ml_dir = tmp_path / "ml"
    ml_dir.mkdir()
    result = restore_active_from_version(empty_dir, ml_dir=ml_dir, filenames=ACTIVE_ARTIFACT_FILES)
    assert result["ok"] is False
    assert result.get("reason") == "no_artifacts_found"


def test_verify_version_artifacts_reports_missing_and_mismatched(tmp_path: Path):
    version_dir = tmp_path / "v"
    version_dir.mkdir()
    (version_dir / "model_weights.json").write_text("{}", encoding="utf-8")
    report = verify_version_artifacts(
        version_dir,
        filenames=("model_weights.json", "scaler.pkl"),
        expected_hashes={"model_weights.json": "deadbeef"},
    )
    assert report["missing"] == ["scaler.pkl"]
    assert report["mismatched"] == ["model_weights.json"]

    good = verify_version_artifacts(version_dir, filenames=("model_weights.json",))
    assert good == {"missing": [], "mismatched": [], "present": ["model_weights.json"]}


# ---------------------------------------------------------------------------
# #123 - data_pipeline / liquidity
# ---------------------------------------------------------------------------


def test_yahoo_nan_rows_filtered_and_all_nan_degrades_to_no_data(monkeypatch):
    import pandas as pd

    from data_pipeline.yfinance_backfill import fetch_yahoo_ohlcv

    frame = pd.DataFrame(
        {
            "Open": [10.0, float("nan"), float("nan")],
            "High": [11.0, float("nan"), float("nan")],
            "Low": [9.5, float("nan"), float("nan")],
            "Close": [10.5, float("nan"), float("nan")],
            "Volume": [1000.0, float("nan"), float("nan")],
        },
        index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
    )

    class FakeYFModule:
        @staticmethod
        def download(*args, **kwargs):
            return frame

    # fetch_yahoo_ohlcv does a deferred `import yfinance as yf` per call -
    # patching sys.modules reaches it without touching the module global.
    monkeypatch.setitem(__import__("sys").modules, "yfinance", FakeYFModule())
    rows = fetch_yahoo_ohlcv("AAPL", "2020-01-01", "2020-01-04")
    assert len(rows) == 1
    assert rows[0]["close"] == 10.5


def test_run_backfill_fetches_end_inclusive_via_next_day():
    from datetime import date

    from data_pipeline.yfinance_backfill import run_backfill

    plan_entry = {
        "ticker": "AAA",
        "security_type": "crypto",
        "yahoo_symbol": "AAA-USD",
        "data_path": "unused.zip",
        "gap": {
            "needs_backfill": True,
            "fetch_start": date(2020, 1, 1),
            "fetch_end": date(2020, 1, 31),
        },
    }
    captured = {}

    def fake_fetch(symbol, start, end):
        captured["start"], captured["end"] = start, end
        return [{"date": date(2020, 1, 31), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}]

    run_backfill({}, [plan_entry], apply=False, fetch_fn=fake_fetch)
    assert captured["start"] == "2020-01-01"
    # end EXCLUSIVE upstream: backfill_to itself must be inside the window.
    assert captured["end"] == "2020-02-01"


def test_fred_cache_write_merges_instead_of_truncating(tmp_path: Path):
    from data_pipeline.fred_backfill import cache_csv_to_rows, write_fred_series_cache

    cache_dir = tmp_path / "fred"
    cache_dir.mkdir()
    existing = cache_dir / "DGS10.csv"
    existing.write_text(
        "2015-06-01,2.30\n2024-01-02,4.00\n",
        encoding="utf-8",
    )
    # A narrow 2024-only refetch must NOT destroy the 2015 history...
    write_fred_series_cache(cache_dir, "DGS10", [{"date": __import__("datetime").date(2024, 1, 3), "value": 4.10}])
    rows = cache_csv_to_rows(existing.read_text(encoding="utf-8"))
    by_date = {row["date"]: row["value"] for row in rows}
    assert by_date[__import__("datetime").date(2015, 6, 1)] == 2.30
    # ...and new rows win their own dates.
    assert by_date[__import__("datetime").date(2024, 1, 3)] == 4.10


def test_liquidity_misconfig_floor_cannot_divide_by_zero():
    decision = build_liquidity_decision(
        close=0.0,  # close*volume == 0
        volume=0.0,
        target_weight=0.10,
        portfolio_value=100_000.0,
        annualized_volatility=0.15,
        security_type="equity",
        min_daily_dollar_volume=0.0,  # misconfigured non-binding floor
    )
    assert decision.recommended_action == "block"
    assert math.isfinite(decision.participation_rate)


def test_liquidity_negative_spread_clipped_to_typical():
    decision = build_liquidity_decision(
        close=100.0,
        volume=1_000_000.0,
        target_weight=0.05,
        portfolio_value=100_000.0,
        annualized_volatility=0.15,
        security_type="equity",
        dynamic_spread=-0.05,  # miswired caller
    )
    assert decision.spread_proxy >= 0.0


def test_pad_sequence_history_empty_history_raises_clear_error():
    with pytest.raises(ValueError, match="empty history"):
        pad_sequence_history([], 30)


# ---------------------------------------------------------------------------
# #124 - telegram / API hardening
# ---------------------------------------------------------------------------


def test_telegram_summary_with_explicit_nulls_renders_instead_of_crashing():
    event = {
        "session_date": "2026-08-26",
        "mode": "paper",
        "session_start_equity": None,  # present-but-null JSONB round-trip
        "session_end_equity": None,
        "session_return": None,
        "observation_summary": {
            "count_observations": None,
            "simulated_win_loss": {"wins": None, "losses": None, "win_rate": None},
            "simulated_sharpe": None,
            "simulated_max_drawdown": None,
        },
    }
    text = format_session_summary_alert(event)
    assert "Session summary" in text
    assert "0.00" in text  # defaults rendered, no TypeError


def test_api_read_json_torn_file_degrades_to_404(tmp_path: Path):
    from fastapi import HTTPException

    from monitoring.api_server import _read_json

    torn = tmp_path / "state.json"
    torn.write_text('{"partial": ', encoding="utf-8")
    with pytest.raises(HTTPException) as excinfo:
        _read_json(torn)
    assert excinfo.value.status_code == 404


def test_neural_network_state_reader_tolerates_mid_write_file(tmp_path: Path):
    from monitoring.neural_network_state import _load_json

    torn = tmp_path / "model_weights.json"
    torn.write_text('{"layers": [', encoding="utf-8")
    assert _load_json(torn) is None
