"""Tests for finnhub_metric_lookup.load_latest_finnhub_metric."""
from __future__ import annotations

import json

from stock_swing.risk.finnhub_metric_lookup import load_latest_finnhub_metric


def _write_snapshot(tmp_path, filename, fetched_at, metric):
    (tmp_path / filename).write_text(
        json.dumps({
            "fetched_at": fetched_at,
            "request_params": {"symbol": filename.split("_")[1].upper()},
            "payload": {"metric": metric},
        }),
        encoding="utf-8",
    )


def test_returns_none_when_dir_missing(tmp_path):
    result = load_latest_finnhub_metric("NBIS", tmp_path / "does_not_exist")
    assert result is None


def test_returns_none_when_no_matching_files(tmp_path):
    result = load_latest_finnhub_metric("NBIS", tmp_path)
    assert result is None


def test_returns_metric_from_single_snapshot(tmp_path):
    _write_snapshot(tmp_path, "finnhub_nbis_2026-08-06_230420257935.json",
                     "2026-08-06T23:04:20+00:00", {"3MonthADReturnStd": 132.56})
    result = load_latest_finnhub_metric("NBIS", tmp_path)
    assert result == {"3MonthADReturnStd": 132.56}


def test_picks_most_recent_by_fetched_at(tmp_path):
    _write_snapshot(tmp_path, "finnhub_nbis_2026-08-04_030424603790.json",
                     "2026-08-04T03:04:24+00:00", {"3MonthADReturnStd": 100.0})
    _write_snapshot(tmp_path, "finnhub_nbis_2026-08-06_230420257935.json",
                     "2026-08-06T23:04:20+00:00", {"3MonthADReturnStd": 132.56})
    _write_snapshot(tmp_path, "finnhub_nbis_2026-08-05_070424696780.json",
                     "2026-08-05T07:04:24+00:00", {"3MonthADReturnStd": 133.79})
    result = load_latest_finnhub_metric("NBIS", tmp_path)
    assert result == {"3MonthADReturnStd": 132.56}


def test_excludes_news_files():
    pass  # covered below with real dir


def test_excludes_news_files_from_matching(tmp_path):
    (tmp_path / "finnhub_nbis_news_2026-08-06_230420487343.json").write_text(
        json.dumps({
            "fetched_at": "2026-08-06T23:04:20+00:00",
            "request_params": {"symbol": "NBIS"},
            "payload": {"news": [{"headline": "x"}]},
        }),
        encoding="utf-8",
    )
    result = load_latest_finnhub_metric("NBIS", tmp_path)
    assert result is None


def test_is_case_insensitive_for_symbol(tmp_path):
    _write_snapshot(tmp_path, "finnhub_nbis_2026-08-06_230420257935.json",
                     "2026-08-06T23:04:20+00:00", {"3MonthADReturnStd": 132.56})
    result = load_latest_finnhub_metric("nbis", tmp_path)
    assert result == {"3MonthADReturnStd": 132.56}


def test_empty_symbol_returns_none(tmp_path):
    result = load_latest_finnhub_metric("", tmp_path)
    assert result is None


def test_malformed_json_file_skipped_not_raised(tmp_path):
    (tmp_path / "finnhub_nbis_2026-08-06_230420257935.json").write_text(
        "not valid json {{{", encoding="utf-8"
    )
    result = load_latest_finnhub_metric("NBIS", tmp_path)
    assert result is None


def test_missing_metric_key_in_payload_skipped(tmp_path):
    (tmp_path / "finnhub_nbis_2026-08-06_230420257935.json").write_text(
        json.dumps({
            "fetched_at": "2026-08-06T23:04:20+00:00",
            "request_params": {"symbol": "NBIS"},
            "payload": {"news": []},
        }),
        encoding="utf-8",
    )
    result = load_latest_finnhub_metric("NBIS", tmp_path)
    assert result is None


def test_does_not_match_other_symbols(tmp_path):
    _write_snapshot(tmp_path, "finnhub_nbis_2026-08-06_230420257935.json",
                     "2026-08-06T23:04:20+00:00", {"3MonthADReturnStd": 132.56})
    result = load_latest_finnhub_metric("NB", tmp_path)
    assert result is None
