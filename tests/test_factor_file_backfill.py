"""Tests for data_pipeline.factor_file_backfill - pure factor-math and
write/read round-trip tests only. yfinance is never imported/invoked in
this file (fetch_corporate_actions() is exercised only via mocking the
deferred `import yfinance` at the call site, matching
test_dividend_backfill.py's own convention) - no real network access
happens here."""

import pandas as pd
import pytest

import train
from data_pipeline.factor_file_backfill import (
    compute_lean_factor_rows,
    configured_equity_tickers,
    fetch_corporate_actions,
    tickers_missing_factor_file,
    write_factor_file,
)


# ---------------------------------------------------------------------------
# compute_lean_factor_rows - pure factor-math, no network
# ---------------------------------------------------------------------------


def _history(rows: dict) -> pd.DataFrame:
    """rows: {date_str: (close, dividend, split)}. Builds a DatetimeIndex
    frame matching yfinance's own Ticker.history(actions=True) column
    names/shape exactly."""
    index = pd.to_datetime(list(rows.keys()))
    return pd.DataFrame(
        {
            "Close": [v[0] for v in rows.values()],
            "Dividends": [v[1] for v in rows.values()],
            "Stock Splits": [v[2] for v in rows.values()],
        },
        index=index,
    )


def test_compute_lean_factor_rows_zero_events_returns_empty():
    history = _history({"2020-01-01": (100.0, 0.0, 0.0), "2020-01-02": (101.0, 0.0, 0.0)})
    assert compute_lean_factor_rows(history) == []


def test_compute_lean_factor_rows_single_dividend_event():
    history = _history(
        {
            "2020-01-01": (100.0, 0.0, 0.0),
            "2020-01-02": (98.0, 2.0, 0.0),  # ex-div: $2 dividend, prior close $100
        }
    )
    rows = compute_lean_factor_rows(history)
    assert len(rows) == 2  # the one real event + terminal sentinel
    event_row = rows[0]
    assert event_row["factor_date"] == "20200102"
    assert event_row["price_factor"] == pytest.approx(1.0 - 2.0 / 100.0)
    assert event_row["split_factor"] == pytest.approx(1.0)
    assert event_row["reference_price"] == pytest.approx(98.0)
    assert rows[-1] == {"factor_date": "20501231", "price_factor": 1.0, "split_factor": 1.0, "reference_price": 0.0}


def test_compute_lean_factor_rows_single_split_event():
    history = _history(
        {
            "2020-01-01": (400.0, 0.0, 0.0),
            "2020-01-02": (100.0, 0.0, 4.0),  # 4-for-1 split
        }
    )
    rows = compute_lean_factor_rows(history)
    assert len(rows) == 2
    event_row = rows[0]
    assert event_row["factor_date"] == "20200102"
    assert event_row["price_factor"] == pytest.approx(1.0)
    assert event_row["split_factor"] == pytest.approx(0.25)


def test_compute_lean_factor_rows_accumulates_newest_to_oldest():
    # An older dividend's cumulative price_factor must include a NEWER
    # split's contribution too - a raw price at the older date needs
    # adjusting for every corporate action between it and today.
    history = _history(
        {
            "2020-01-01": (100.0, 0.0, 0.0),
            "2020-01-02": (98.0, 2.0, 0.0),  # older: dividend only
            "2020-06-01": (200.0, 0.0, 0.0),
            "2020-06-02": (50.0, 0.0, 4.0),  # newer: 4-for-1 split
        }
    )
    rows = compute_lean_factor_rows(history)
    # 2 real events (oldest-first output order) + terminal sentinel
    assert len(rows) == 3
    dividend_row = next(r for r in rows if r["factor_date"] == "20200102")
    split_row = next(r for r in rows if r["factor_date"] == "20200602")
    # The older dividend row's price_factor must already include the
    # newer split's split_factor being applied to price_factor's own
    # dividend-only computation is untouched by the split (separate
    # columns) - but its split_factor must equal the newer split's own
    # cumulative split_factor, since no split occurred between them.
    assert dividend_row["split_factor"] == pytest.approx(split_row["split_factor"])
    assert dividend_row["split_factor"] == pytest.approx(0.25)
    assert dividend_row["price_factor"] == pytest.approx(1.0 - 2.0 / 100.0)


def test_compute_lean_factor_rows_output_is_oldest_first_with_sentinel_last():
    history = _history(
        {
            "2019-01-01": (100.0, 0.0, 0.0),
            "2019-01-02": (98.0, 2.0, 0.0),
            "2021-01-01": (100.0, 0.0, 0.0),
            "2021-01-02": (98.0, 2.0, 0.0),
        }
    )
    rows = compute_lean_factor_rows(history)
    dates = [row["factor_date"] for row in rows]
    assert dates == ["20190102", "20210102", "20501231"]


def test_compute_lean_factor_rows_zero_dividend_and_zero_split_rows_ignored():
    history = _history(
        {
            "2020-01-01": (100.0, 0.0, 0.0),
            "2020-01-02": (100.5, 0.0, 0.0),  # ordinary trading day, no event
            "2020-01-03": (98.0, 2.0, 0.0),
        }
    )
    rows = compute_lean_factor_rows(history)
    assert len(rows) == 2  # only the real event + sentinel
    assert rows[0]["factor_date"] == "20200103"


def test_compute_lean_factor_rows_first_row_dividend_falls_back_to_own_close():
    # An event on the very first row of history has no prior session to
    # look up - must degrade gracefully (use its own close), never raise
    # or crash on an empty prior-close slice.
    history = _history({"2020-01-01": (98.0, 2.0, 0.0)})
    rows = compute_lean_factor_rows(history)
    assert len(rows) == 2
    assert rows[0]["price_factor"] == pytest.approx(1.0 - 2.0 / 98.0)


# ---------------------------------------------------------------------------
# configured_equity_tickers / tickers_missing_factor_file
# ---------------------------------------------------------------------------


def test_configured_equity_tickers_resolves_equity_assets_only():
    config = {
        "phase1": {
            "universe": {
                "assets": [
                    {"ticker": "AAPL_OPT", "security_type": "option", "underlying_ticker": "AAPL"},
                    {"ticker": "MSFT", "security_type": "equity"},
                    {"ticker": "EURUSD", "security_type": "forex"},
                    {"ticker": "MSFT", "security_type": "equity"},  # duplicate
                ]
            }
        }
    }
    assert configured_equity_tickers(config) == ["MSFT"]


def test_configured_equity_tickers_empty_config_returns_empty():
    assert configured_equity_tickers({}) == []


def test_configured_equity_tickers_skips_malformed_entries_without_raising():
    config = {"phase1": {"universe": {"assets": [{"security_type": "equity"}, {"ticker": "MSFT", "security_type": "equity"}]}}}
    assert configured_equity_tickers(config) == ["MSFT"]


def test_tickers_missing_factor_file_filters_to_absent_files(tmp_path):
    (tmp_path / "aapl.csv").write_text("20501231,1,1,0\n", encoding="utf-8")
    result = tickers_missing_factor_file(["AAPL", "NVDA", "GE"], tmp_path)
    assert result == ["NVDA", "GE"]


# ---------------------------------------------------------------------------
# write_factor_file - round-tripped directly against train.py's own reader,
# the real consumer contract this whole module exists to satisfy.
# ---------------------------------------------------------------------------


def test_write_factor_file_round_trips_through_train_load_factor_file(tmp_path, monkeypatch):
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", tmp_path)
    rows = [
        {"factor_date": "20200102", "price_factor": 0.98, "split_factor": 1.0, "reference_price": 98.0},
        {"factor_date": "20501231", "price_factor": 1.0, "split_factor": 1.0, "reference_price": 0.0},
    ]
    write_factor_file(tmp_path, "TEST", rows)

    factors = train.load_factor_file("TEST")
    assert factors is not None
    assert len(factors) == 2
    assert factors.iloc[0]["price_factor"] == pytest.approx(0.98)
    assert factors.iloc[0]["split_factor"] == pytest.approx(1.0)
    assert factors.iloc[1]["price_factor"] == pytest.approx(1.0)


def test_write_factor_file_writes_lowercase_ticker_filename(tmp_path):
    path = write_factor_file(tmp_path, "NVDA", [dict(factor_date="20501231", price_factor=1.0, split_factor=1.0, reference_price=0.0)])
    assert path.name == "nvda.csv"
    assert path.exists()


# ---------------------------------------------------------------------------
# fetch_corporate_actions - deferred `import yfinance` mocked, never real
# network access.
# ---------------------------------------------------------------------------


def test_fetch_corporate_actions_never_raises_when_yfinance_unavailable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    assert fetch_corporate_actions("AAPL") is None


# ---------------------------------------------------------------------------
# V5.5.0 (Problems.md #130) - double-adjustment detection and repair
# ---------------------------------------------------------------------------

import json  # noqa: E402
from zipfile import ZipFile  # noqa: E402

from data_pipeline import factor_file_backfill as ffb  # noqa: E402


def _write_zip(path, rows, *, float_volume):
    """Lean daily CSV rows: (YYYYMMDD, close). Volume is float-formatted the way
    yfinance_backfill writes it, or integer-formatted the way QuantConnect does."""
    lines = []
    for date, close in rows:
        volume = "98898000.0" if float_volume else "98898000"
        deci = int(round(close * 10000))
        lines.append(f"{date} 00:00,{deci},{deci},{deci},{deci},{volume}")
    with ZipFile(path, "w") as archive:
        archive.writestr("x.csv", "\n".join(lines))


def _rows(factor_rows):
    return [dict(zip(("factor_date", "price_factor", "split_factor", "reference_price"), r)) for r in factor_rows]


def test_a_float_formatted_volume_fingerprints_the_yfinance_backfill_writer(tmp_path):
    adjusted, raw = tmp_path / "a.zip", tmp_path / "r.zip"
    _write_zip(adjusted, [("20190603", 84.63), ("20190604", 85.0)], float_volume=True)
    _write_zip(raw, [("20190603", 84.63), ("20190604", 85.0)], float_volume=False)
    assert ffb.zip_written_by_yfinance_backfill(ffb.read_zip_daily_rows(adjusted)) is True
    assert ffb.zip_written_by_yfinance_backfill(ffb.read_zip_daily_rows(raw)) is False
    assert ffb.zip_written_by_yfinance_backfill([]) is False
    assert ffb.read_zip_daily_rows(tmp_path / "missing.zip") == []


def test_a_merged_zip_keeping_real_integer_rows_is_not_treated_as_backfill_written(tmp_path):
    path = tmp_path / "m.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("x.csv", "20190603 00:00,1,1,1,1,1000.0\n20190604 00:00,1,1,1,1,5000")
    assert ffb.zip_written_by_yfinance_backfill(ffb.read_zip_daily_rows(path)) is False


def test_reference_ratio_is_one_on_a_raw_zip_and_below_one_on_a_dividend_adjusted_one():
    factor_rows = _rows([("20200102", 0.98, 1.0, 100.0), ("20200402", 0.99, 1.0, 100.0)])
    raw_zip = [["20200102 00:00", "0", "0", "0", "1000000", "1"], ["20200402 00:00", "0", "0", "0", "1000000", "1"]]
    adjusted_zip = [["20200102 00:00", "0", "0", "0", "970000", "1"], ["20200402 00:00", "0", "0", "0", "980000", "1"]]
    assert ffb.reference_ratio_median(raw_zip, factor_rows) == pytest.approx(1.0)
    assert ffb.reference_ratio_median(adjusted_zip, factor_rows) == pytest.approx(0.975)
    assert ffb.reference_ratio_median([], factor_rows) is None
    assert ffb.reference_ratio_median(raw_zip, _rows([("20991231", 1.0, 1.0, 100.0)])) is None


def test_audit_flags_only_the_proven_double_adjustment():
    adjusted_zip = [["20200102 00:00", "0", "0", "0", "970000", "98898000.0"]]
    raw_zip = [["20200102 00:00", "0", "0", "0", "1000000", "98898000"]]
    real_file = _rows([("20200102", 0.98, 0.05, 100.0), ("20501231", 1.0, 1.0, 0.0)])
    identity = _rows([("20501231", 1.0, 1.0, 0.0)])

    double = ffb.audit_factor_file(adjusted_zip, real_file)
    assert double["needs_repair"] is True
    assert double["zip_written_by_yfinance_backfill"] is True

    legitimate = ffb.audit_factor_file(raw_zip, real_file)  # a genuine QuantConnect raw zip + its factor file
    assert legitimate["needs_repair"] is False

    # A sentinel-only "identity" file is NOT a fix: Lean reads its zero reference price as a numerical-precision
    # problem and moves the symbol's data start to 12/30/2050 (V5.5.0's first backtest attempt logged exactly that).
    sentinel_only = ffb.audit_factor_file(adjusted_zip, identity)
    assert sentinel_only["needs_repair"] is True
    assert "2050" in sentinel_only["reason"]


def test_a_split_only_file_with_no_dividend_evidence_is_still_flagged_for_a_backfill_zip():
    """AMZN/CRM/ADBE pay no dividends, so the reference ratio is uninformative (None) - the
    writer fingerprint alone must carry the verdict."""
    zip_rows = [["20190603 00:00", "0", "0", "0", "846345", "98898000.0"]]
    split_file = _rows([("20220606", 1.0, 0.05, 124.79), ("20501231", 1.0, 1.0, 0.0)])
    verdict = ffb.audit_factor_file(zip_rows, split_file)
    assert verdict["needs_repair"] is True and verdict["zip_to_reference_ratio_median"] is None


def test_repair_backs_up_the_original_once_then_removes_the_file(tmp_path):
    factor_dir = tmp_path / "factor_files"
    original = _rows([("20200102", 0.98, 0.05, 100.0), ("20501231", 1.0, 1.0, 0.0)])
    ffb.write_factor_file(factor_dir, "AMZN", original)
    original_text = (factor_dir / "amzn.csv").read_text(encoding="utf-8")

    assert ffb.repair_factor_file(factor_dir, "AMZN", apply=False) is None  # dry run touches nothing
    assert (factor_dir / "amzn.csv").read_text(encoding="utf-8") == original_text

    backup = ffb.repair_factor_file(factor_dir, "AMZN", apply=True)
    assert backup == tmp_path / ffb.BACKUP_DIR_NAME / "amzn.csv"  # OUTSIDE factor_files/: Lean reads that directory
    assert backup.read_text(encoding="utf-8") == original_text
    assert not (factor_dir / "amzn.csv").exists()  # removed, NOT replaced by a sentinel-only stub (see #130)
    assert [path.name for path in factor_dir.iterdir()] == []  # no stray subfolder next to the files Lean reads

    ffb.write_factor_file(factor_dir, "AMZN", _rows([("20501231", 1.0, 1.0, 0.0)]))  # a later stub must not clobber the TRUE backup
    ffb.repair_factor_file(factor_dir, "AMZN", apply=True)
    assert backup.read_text(encoding="utf-8") == original_text


def test_a_removed_factor_file_is_an_identity_through_the_training_pipeline_reader(tmp_path, monkeypatch):
    factor_dir = tmp_path / "factor_files"
    ffb.write_factor_file(factor_dir, "AMZN", _rows([("20220606", 1.0, 0.05, 124.79), ("20501231", 1.0, 1.0, 0.0)]))
    ffb.repair_factor_file(factor_dir, "AMZN", apply=True)
    monkeypatch.setattr(train, "FACTOR_FILES_DIR", factor_dir)
    assert train.load_factor_file("AMZN") is None
    frame = pd.DataFrame(
        {"date": pd.to_datetime(["2019-06-03", "2019-06-04"]), "open": [84.0, 85.0], "high": [86.0, 86.0],
         "low": [83.0, 84.0], "close": [84.63, 85.5], "volume": [1000.0, 2000.0]}
    )
    adjusted = train.apply_split_adjustments(frame, "AMZN")
    assert adjusted["close"].tolist() == pytest.approx([84.63, 85.5])  # NOT x0.05
    assert adjusted["volume"].tolist() == pytest.approx([1000.0, 2000.0])


def test_cli_audit_and_repair_report_and_apply(tmp_path, monkeypatch, capsys):
    factor_dir = tmp_path / "factor_files"
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    _write_zip(daily_dir / "amzn.zip", [("20190603", 84.63)], float_volume=True)
    _write_zip(daily_dir / "aapl.zip", [("20190603", 200.0)], float_volume=False)
    ffb.write_factor_file(factor_dir, "AMZN", _rows([("20220606", 1.0, 0.05, 124.79), ("20501231", 1.0, 1.0, 0.0)]))
    ffb.write_factor_file(factor_dir, "AAPL", _rows([("20200828", 0.99, 0.25, 499.23), ("20501231", 1.0, 1.0, 0.0)]))
    config = {
        "phase1": {"universe": {"assets": [
            {"ticker": "AMZN", "security_type": "equity", "data_path": str(daily_dir / "amzn.zip")},
            {"ticker": "AAPL", "security_type": "equity", "data_path": str(daily_dir / "aapl.zip")},
        ]}}
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(ffb, "ROOT", tmp_path)  # data_path is joined onto ROOT; absolute paths stay absolute

    base = ["factor_file_backfill", "--config-path", str(config_path), "--output-dir", str(factor_dir)]
    monkeypatch.setattr("sys.argv", base + ["--audit"])
    assert ffb.main() == 1  # a double-adjusted file exists -> non-zero, so a CI step can gate on it
    out = capsys.readouterr().out
    assert "AMZN: DOUBLE-ADJUSTED" in out and "AAPL: ok" in out

    monkeypatch.setattr("sys.argv", base + ["--repair-adjusted-zips"])
    assert ffb.main() == 0
    assert "would_repair" in capsys.readouterr().out
    assert "0.05" in (factor_dir / "amzn.csv").read_text(encoding="utf-8")  # dry run changed nothing

    monkeypatch.setattr("sys.argv", base + ["--repair-adjusted-zips", "--apply"])
    assert ffb.main() == 0
    assert not (factor_dir / "amzn.csv").exists()
    assert (tmp_path / ffb.BACKUP_DIR_NAME / "amzn.csv").exists()
    assert "0.25" in (factor_dir / "aapl.csv").read_text(encoding="utf-8")  # the genuine QC file is untouched

    monkeypatch.setattr("sys.argv", base + ["--audit"])
    assert ffb.main() == 0


def test_generation_skips_tickers_whose_zip_is_already_adjusted(tmp_path, monkeypatch, capsys):
    factor_dir = tmp_path / "factor_files"
    zip_path = tmp_path / "amzn.zip"
    _write_zip(zip_path, [("20190603", 84.63)], float_volume=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"phase1": {"universe": {"assets": [{"ticker": "AMZN", "security_type": "equity", "data_path": str(zip_path)}]}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ffb, "ROOT", tmp_path)
    monkeypatch.setattr(ffb, "fetch_corporate_actions", lambda _t: pytest.fail("must not fetch for an already-adjusted zip"))
    monkeypatch.setattr("sys.argv", ["factor_file_backfill", "--config-path", str(config_path), "--output-dir", str(factor_dir), "--apply"])
    assert ffb.main() == 0
    assert "skipped_zip_already_adjusted" in capsys.readouterr().out
    assert not (factor_dir / "amzn.csv").exists()
